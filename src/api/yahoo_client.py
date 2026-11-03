"""Yahoo Fantasy Sports API client with rate limiting and token refresh."""

import asyncio
import math
import os
import socket

import aiohttp

from src.api.yahoo_token_store import TokenPair, TokenStoreError, configured_store
from src.api.yahoo_utils import rate_limiter, response_cache

# Module-level token cache
_YAHOO_ACCESS_TOKEN = os.getenv("YAHOO_ACCESS_TOKEN")
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Yahoo's 401s carry an oauth_problem that distinguishes recoverable from
# unrecoverable auth failures. additional_authorization_required means the
# token is valid but the app itself is not entitled to the Fantasy Sports
# API — refreshing can never help. See issue #18.
NOT_PROVISIONED_ERROR = (
    "Your Yahoo app is not provisioned for the Fantasy Sports API "
    '(oauth_problem="additional_authorization_required"). This is not a '
    "token problem - refreshing will not help. Yahoo no longer self-serve "
    "provisions Fantasy Sports API access; apply at "
    "https://sports.yahoo.com/developer/access/ and include your existing "
    "Client ID so approval is attached to the app you already have."
)


def get_access_token() -> str:
    """Get the current access token."""
    global _YAHOO_ACCESS_TOKEN
    store = configured_store()
    if store is not None:
        # Atomic replacement makes read-only startup safe without creating a lock.
        pair = store.read()
        _publish_tokens(pair)
    if _YAHOO_ACCESS_TOKEN is None:
        _YAHOO_ACCESS_TOKEN = os.getenv("YAHOO_ACCESS_TOKEN")
    return _YAHOO_ACCESS_TOKEN or ""


def set_access_token(token: str) -> None:
    """Update the access token (used after refresh)."""
    global _YAHOO_ACCESS_TOKEN
    _YAHOO_ACCESS_TOKEN = token
    os.environ["YAHOO_ACCESS_TOKEN"] = token


def _publish_tokens(pair: TokenPair) -> None:
    set_access_token(pair.access_token)
    os.environ["YAHOO_REFRESH_TOKEN"] = pair.refresh_token


def initialize_token_store() -> None:
    """Load an explicitly configured store after dotenv/injected settings."""
    if configured_store() is not None:
        get_access_token()


def _private_errors() -> bool:
    return bool(os.getenv("YAHOO_TOKEN_STORE")) or os.getenv("FANTASY_CLOUD_RUNTIME") == "1"


class YahooResponseError(Exception):
    """Provider status error whose cloud message is already credential-free."""


async def yahoo_api_call(
    endpoint: str, retry_on_auth_fail: bool = True, use_cache: bool = True
) -> dict:
    """Make Yahoo API request with rate limiting, caching, and automatic token refresh.

    Args:
        endpoint: Yahoo API endpoint (e.g., "users;use_login=1/games")
        retry_on_auth_fail: If True, will attempt token refresh on 401 errors
        use_cache: If True, will check cache before making API call

    Returns:
        dict: JSON response from Yahoo API

    Raises:
        Exception: On API errors or authentication failures
    """
    # Check cache first (if enabled)
    if use_cache:
        cached_response = await response_cache.get(endpoint)
        if cached_response is not None:
            return cached_response

    # Apply rate limiting
    await rate_limiter.acquire()

    access_token = get_access_token()
    url = f"{YAHOO_API_BASE}/{endpoint}?format=json"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    try:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector, trust_env=True) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Cache successful response
                    if use_cache:
                        await response_cache.set(endpoint, data)
                    return data
                elif response.status == 401:
                    text = await response.text()
                    # A provisioning failure is not recoverable by refresh: the
                    # token authenticates fine, the APP lacks Fantasy API access.
                    if "additional_authorization_required" in text:
                        raise YahooResponseError(NOT_PROVISIONED_ERROR)
                    if retry_on_auth_fail:
                        # token_rejected / expired token - refreshing helps here
                        refresh_result = await refresh_yahoo_token(
                            rejected_access_token=access_token
                        )
                        if refresh_result.get("status") == "success":
                            # Token refreshed, retry the API call with new token
                            return await yahoo_api_call(
                                endpoint, retry_on_auth_fail=False, use_cache=use_cache
                            )
                        detail = "" if _private_errors() else f": {text[:200]}"
                        raise YahooResponseError(
                            f"Yahoo API auth failed and token refresh failed{detail}"
                        )
                    detail = "" if _private_errors() else f": {text[:200]}"
                    raise YahooResponseError(f"Yahoo API error 401 after token refresh{detail}")
                else:
                    text = await response.text()
                    detail = "" if _private_errors() else f": {text[:200]}"
                    raise YahooResponseError(f"Yahoo API error {response.status}{detail}")
    except YahooResponseError:
        raise
    except Exception:
        if _private_errors():
            raise YahooResponseError("Yahoo API request failed") from None
        raise


async def refresh_yahoo_token(*, rejected_access_token: str | None = None) -> dict:
    """Serialize opt-in durable refresh; keep legacy environment-only mode unchanged."""
    try:
        store = configured_store()
        if store is None:
            return await _refresh_yahoo_token()
        async with store.async_locked():
            pair = store.read()
            if rejected_access_token is not None and pair.access_token != rejected_access_token:
                _publish_tokens(pair)
                return {"status": "success", "message": "Loaded tokens rotated by another process"}
            # Once Yahoo may rotate credentials, finish persistence before a
            # cancelled caller can release the shared lock. Shielding alone is
            # insufficient: keep waiting even after repeated caller cancellation.
            rotation = asyncio.create_task(_refresh_yahoo_token(store=store, pair=pair))
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(rotation)
                    break
                except asyncio.CancelledError:
                    if rotation.cancelled():
                        raise
                    cancelled = True
                except BaseException:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise
            if cancelled:
                raise asyncio.CancelledError
            return result
    except TokenStoreError as exc:
        return {"status": "error", "message": str(exc)}


async def _refresh_yahoo_token(*, store=None, pair=None) -> dict:
    """Refresh the Yahoo access token using the refresh token.

    Returns:
        dict: Status message with refresh result
            - {"status": "success", "message": "...", "expires_in": 3600}
            - {"status": "error", "message": "...", "details": "..."}
    """
    client_id = os.getenv("YAHOO_CLIENT_ID")
    client_secret = os.getenv("YAHOO_CLIENT_SECRET")
    refresh_token = pair.refresh_token if pair else os.getenv("YAHOO_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return {"status": "error", "message": "Missing credentials in environment"}

    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        timeout = {"timeout": aiohttp.ClientTimeout(total=60)} if store is not None else {}
        async with aiohttp.ClientSession(connector=connector, trust_env=True, **timeout) as session:
            async with session.post(token_url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    new_access_token = token_data.get("access_token")
                    new_refresh_token = token_data.get("refresh_token", refresh_token)
                    expires_in = token_data.get("expires_in", 3600)

                    if not isinstance(new_access_token, str) or not new_access_token.strip():
                        return {
                            "status": "error",
                            "message": "Yahoo returned an invalid token response",
                        }
                    if not isinstance(new_refresh_token, str) or not new_refresh_token.strip():
                        return {
                            "status": "error",
                            "message": "Yahoo returned an invalid token response",
                        }
                    if store is not None:
                        try:
                            valid_expiry = (
                                not isinstance(expires_in, bool)
                                and isinstance(expires_in, (int, float))
                                and math.isfinite(float(expires_in))
                                and expires_in > 0
                            )
                        except (OverflowError, ValueError):
                            valid_expiry = False
                        if not valid_expiry:
                            # Expiry is informational. Never discard a valid
                            # rotated pair because this metadata is malformed.
                            expires_in = None
                        store.write(TokenPair(new_access_token, new_refresh_token))

                    # Update global token
                    set_access_token(new_access_token)

                    # Update environment
                    if new_refresh_token != refresh_token:
                        os.environ["YAHOO_REFRESH_TOKEN"] = new_refresh_token

                    return {
                        "status": "success",
                        "message": (
                            "Token refreshed successfully"
                            if expires_in is not None
                            else "Token refreshed successfully; expiry unavailable"
                        ),
                        "expires_in": expires_in,
                        "expires_in_hours": (
                            round(expires_in / 3600, 1) if expires_in is not None else None
                        ),
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "message": f"Failed to refresh token: {response.status}",
                        "details": (
                            "Yahoo rejected the token refresh"
                            if _private_errors()
                            else error_text[:200]
                        ),
                    }
    except TokenStoreError:
        raise
    except Exception as exc:
        message = (
            "Error refreshing token" if _private_errors() else f"Error refreshing token: {exc}"
        )
        return {"status": "error", "message": message}
