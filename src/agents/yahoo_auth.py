"""
Yahoo Fantasy Sports API Authentication Implementation

This module provides comprehensive OAuth2 authentication for Yahoo's Fantasy Sports API,
handling their non-standard implementation with proper token management and refresh logic.

Yahoo API peculiarities handled:
- Non-standard OAuth2 flow with specific redirect URI requirements
- Tokens expire after 1 hour and must be refreshed
- Auth codes are only valid for 10 minutes
- Exact redirect URI matching required
- Specific scope format requirements
"""

import asyncio
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, Callable
from urllib.parse import urlencode, parse_qs

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from config.settings import Settings


class AuthState(str, Enum):
    """OAuth authentication states."""
    UNAUTHENTICATED = "unauthenticated"
    PENDING_AUTHORIZATION = "pending_authorization"
    AUTHENTICATED = "authenticated"
    TOKEN_EXPIRED = "token_expired"
    REFRESH_FAILED = "refresh_failed"


class YahooTokens(BaseModel):
    """Yahoo API tokens with metadata."""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    scope: str = ""
    
    @property
    def is_expired(self) -> bool:
        """Check if the access token is expired with 5-minute buffer."""
        return datetime.now() >= (self.expires_at - timedelta(minutes=5))
    
    @property
    def expires_in_seconds(self) -> int:
        """Get seconds until token expiration."""
        delta = self.expires_at - datetime.now()
        return max(0, int(delta.total_seconds()))


class YahooAuthError(Exception):
    """Base exception for Yahoo authentication errors."""
    pass


class YahooTokenExpiredError(YahooAuthError):
    """Raised when Yahoo token is expired and refresh failed."""
    pass


class YahooAuthTimeoutError(YahooAuthError):
    """Raised when Yahoo auth flow times out."""
    pass


class YahooInvalidGrantError(YahooAuthError):
    """Raised when Yahoo returns invalid_grant error."""
    pass


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""
    
    def __init__(self, auth_callback: Callable[[str, Optional[str]], None], *args, **kwargs):
        self.auth_callback = auth_callback
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET request for OAuth callback."""
        try:
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = parse_qs(parsed_path.query)
            
            # Extract authorization code or error
            auth_code = query_params.get('code', [None])[0]
            error = query_params.get('error', [None])[0]
            state = query_params.get('state', [None])[0]
            
            # Send response to browser
            if auth_code:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"""
                <html>
                <head><title>Yahoo Authentication</title></head>
                <body>
                    <h2>Authentication Successful!</h2>
                    <p>You can close this window and return to your application.</p>
                    <script>window.close();</script>
                </body>
                </html>
                """)
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f"""
                <html>
                <head><title>Yahoo Authentication Error</title></head>
                <body>
                    <h2>Authentication Failed</h2>
                    <p>Error: {error or 'Unknown error'}</p>
                    <p>You can close this window.</p>
                </body>
                </html>
                """.encode())
            
            # Notify the auth manager
            self.auth_callback(auth_code, error)
            
        except Exception as e:
            logger.error(f"Error in callback handler: {e}")
            self.send_response(500)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        pass


class YahooAuth:
    """
    Comprehensive Yahoo Fantasy Sports API authentication manager.
    
    Handles OAuth2 flow, token management, refresh logic, and all Yahoo-specific
    requirements and edge cases.
    """
    
    # Yahoo OAuth2 endpoints
    YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
    YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
    
    # Yahoo API base URL
    YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
    
    # Default scopes for fantasy sports
    DEFAULT_SCOPES = "fspt-r"  # Fantasy sports read permission
    
    def __init__(
        self,
        settings: Settings,
        callback_host: str = "localhost",
        callback_port: int = 8080,
        token_storage_path: Optional[Path] = None
    ):
        """
        Initialize Yahoo authentication manager.
        
        Args:
            settings: Application settings with Yahoo credentials
            callback_host: Host for OAuth callback server
            callback_port: Port for OAuth callback server
            token_storage_path: Path to store tokens (defaults to cache_dir/yahoo_tokens.json)
        """
        self.settings = settings
        self.callback_host = callback_host or getattr(settings, 'yahoo_callback_host', 'localhost')
        self.callback_port = callback_port or getattr(settings, 'yahoo_callback_port', 8090)
        
        # Token storage
        self.token_storage_path = (
            token_storage_path or 
            settings.cache_dir / "yahoo_tokens.json"
        )
        
        # Authentication state
        self.tokens: Optional[YahooTokens] = None
        self.auth_state: AuthState = AuthState.UNAUTHENTICATED
        self._auth_server: Optional[HTTPServer] = None
        self._auth_event: Optional[threading.Event] = None
        self._auth_result: Optional[Tuple[Optional[str], Optional[str]]] = None
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds
        
        # Load existing tokens
        self._load_tokens()
        
        logger.info(f"Yahoo Auth initialized with callback {callback_host}:{callback_port}")
    
    @property
    def redirect_uri(self) -> str:
        """Get the OAuth redirect URI."""
        return f"http://{self.callback_host}:{self.callback_port}/callback"
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with valid tokens."""
        return (
            self.tokens is not None and 
            not self.tokens.is_expired and
            self.auth_state == AuthState.AUTHENTICATED
        )
    
    def _load_tokens(self) -> None:
        """Load tokens from storage if available."""
        if not self.token_storage_path.exists():
            logger.debug("No stored tokens found")
            return
        
        try:
            with open(self.token_storage_path, 'r') as f:
                token_data = json.load(f)
            
            # Parse stored tokens
            token_data['expires_at'] = datetime.fromisoformat(token_data['expires_at'])
            self.tokens = YahooTokens(**token_data)
            
            # Set auth state based on token validity
            if self.tokens.is_expired:
                self.auth_state = AuthState.TOKEN_EXPIRED
                logger.info("Loaded expired tokens")
            else:
                self.auth_state = AuthState.AUTHENTICATED
                logger.info(f"Loaded valid tokens (expires in {self.tokens.expires_in_seconds}s)")
                
        except Exception as e:
            logger.warning(f"Failed to load stored tokens: {e}")
            self.tokens = None
            self.auth_state = AuthState.UNAUTHENTICATED
    
    def _save_tokens(self) -> None:
        """Save tokens to storage."""
        if not self.tokens:
            return
        
        try:
            # Ensure directory exists
            self.token_storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Serialize tokens
            token_data = self.tokens.model_dump()
            token_data['expires_at'] = self.tokens.expires_at.isoformat()
            
            with open(self.token_storage_path, 'w') as f:
                json.dump(token_data, f, indent=2)
            
            logger.debug("Tokens saved to storage")
            
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
    
    def _generate_pkce_challenge(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge for OAuth2."""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')
        
        return code_verifier, code_challenge
    
    def get_authorization_url(
        self,
        state: Optional[str] = None,
        scopes: str = DEFAULT_SCOPES
    ) -> Tuple[str, str]:
        """
        Get Yahoo OAuth2 authorization URL.
        
        Args:
            state: Optional state parameter for security
            scopes: OAuth scopes to request
            
        Returns:
            Tuple of (authorization_url, state)
        """
        if state is None:
            state = secrets.token_urlsafe(32)
        
        params = {
            'client_id': self.settings.yahoo_client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'state': state,
            'scope': scopes
        }
        
        auth_url = f"{self.YAHOO_AUTH_URL}?{urlencode(params)}"
        logger.debug(f"Generated auth URL with redirect_uri: {self.redirect_uri}")
        
        return auth_url, state
    
    def _start_callback_server(self) -> None:
        """Start the OAuth callback server."""
        if self._auth_server:
            return
        
        self._auth_event = threading.Event()
        self._auth_result = None
        
        def callback_handler_factory(*args, **kwargs):
            return CallbackHandler(self._handle_callback, *args, **kwargs)
        
        try:
            self._auth_server = HTTPServer(
                (self.callback_host, self.callback_port),
                callback_handler_factory
            )
            
            # Start server in separate thread
            server_thread = threading.Thread(
                target=self._auth_server.serve_forever,
                daemon=True
            )
            server_thread.start()
            
            logger.info(f"OAuth callback server started at {self.redirect_uri}")
            
        except Exception as e:
            logger.error(f"Failed to start callback server: {e}")
            raise YahooAuthError(f"Cannot start callback server: {e}")
    
    def _stop_callback_server(self) -> None:
        """Stop the OAuth callback server."""
        if self._auth_server:
            self._auth_server.shutdown()
            self._auth_server = None
            logger.debug("OAuth callback server stopped")
    
    def _handle_callback(self, auth_code: Optional[str], error: Optional[str]) -> None:
        """Handle OAuth callback result."""
        self._auth_result = (auth_code, error)
        if self._auth_event:
            self._auth_event.set()
    
    async def authenticate(
        self,
        timeout: int = 300,
        scopes: str = DEFAULT_SCOPES,
        auto_open_browser: bool = True
    ) -> YahooTokens:
        """
        Perform complete OAuth2 authentication flow.
        
        Args:
            timeout: Timeout in seconds for user authorization
            scopes: OAuth scopes to request
            auto_open_browser: Whether to automatically open browser
            
        Returns:
            YahooTokens object with access and refresh tokens
            
        Raises:
            YahooAuthError: If authentication fails
            YahooAuthTimeoutError: If user doesn't authorize in time
        """
        logger.info("Starting Yahoo OAuth2 authentication flow")
        
        # Check if we have valid tokens
        if self.is_authenticated:
            logger.info("Already authenticated with valid tokens")
            return self.tokens
        
        # Try to refresh if we have expired tokens
        if self.tokens and self.auth_state == AuthState.TOKEN_EXPIRED:
            try:
                return await self.refresh_tokens()
            except Exception as e:
                logger.warning(f"Token refresh failed, proceeding with new auth: {e}")
        
        self.auth_state = AuthState.PENDING_AUTHORIZATION
        
        try:
            # Start callback server
            self._start_callback_server()
            
            # Generate authorization URL
            state = secrets.token_urlsafe(32)
            auth_url, _ = self.get_authorization_url(state=state, scopes=scopes)
            
            logger.info(f"Please visit the following URL to authorize the application:")
            logger.info(f"{auth_url}")
            
            if auto_open_browser:
                try:
                    import webbrowser
                    webbrowser.open(auth_url)
                    logger.info("Browser opened automatically")
                except Exception as e:
                    logger.warning(f"Failed to open browser: {e}")
            
            # Wait for callback
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self._auth_event and self._auth_event.wait(timeout=1):
                    break
                await asyncio.sleep(0.1)
            else:
                raise YahooAuthTimeoutError(f"Authentication timeout after {timeout} seconds")
            
            # Process callback result
            if not self._auth_result:
                raise YahooAuthError("No callback result received")
            
            auth_code, error = self._auth_result
            
            if error:
                raise YahooAuthError(f"Authorization failed: {error}")
            
            if not auth_code:
                raise YahooAuthError("No authorization code received")
            
            # Exchange code for tokens
            tokens = await self._exchange_code_for_tokens(auth_code)
            
            self.tokens = tokens
            self.auth_state = AuthState.AUTHENTICATED
            self._save_tokens()
            
            logger.info("Authentication successful!")
            return tokens
            
        finally:
            self._stop_callback_server()
    
    async def _exchange_code_for_tokens(self, auth_code: str) -> YahooTokens:
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            auth_code: Authorization code from callback
            
        Returns:
            YahooTokens object
            
        Raises:
            YahooAuthError: If token exchange fails
        """
        logger.debug("Exchanging authorization code for tokens")
        
        # Prepare token request
        auth_header = base64.b64encode(
            f"{self.settings.yahoo_client_id}:{self.settings.yahoo_client_secret}".encode()
        ).decode('utf-8')
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': self.redirect_uri
        }
        
        # Make token request with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.YAHOO_TOKEN_URL,
                        headers=headers,
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        response_data = await response.json()
                        
                        if response.status != 200:
                            error_desc = response_data.get('error_description', 'Unknown error')
                            error_code = response_data.get('error', 'unknown_error')
                            
                            if error_code == 'invalid_grant':
                                raise YahooInvalidGrantError(f"Invalid grant: {error_desc}")
                            
                            raise YahooAuthError(f"Token exchange failed: {error_desc}")
                        
                        # Parse token response
                        access_token = response_data['access_token']
                        refresh_token = response_data['refresh_token']
                        expires_in = response_data.get('expires_in', 3600)
                        token_type = response_data.get('token_type', 'Bearer')
                        scope = response_data.get('scope', '')
                        
                        expires_at = datetime.now() + timedelta(seconds=expires_in)
                        
                        tokens = YahooTokens(
                            access_token=access_token,
                            refresh_token=refresh_token,
                            token_type=token_type,
                            expires_at=expires_at,
                            scope=scope
                        )
                        
                        logger.debug(f"Tokens obtained, expires at {expires_at}")
                        return tokens
                        
            except YahooInvalidGrantError:
                raise  # Don't retry invalid grant errors
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise YahooAuthError(f"Failed to exchange code for tokens: {e}")
                
                logger.warning(f"Token exchange attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
        
        raise YahooAuthError("All token exchange attempts failed")
    
    async def refresh_tokens(self) -> YahooTokens:
        """
        Refresh access token using refresh token.
        
        Returns:
            Updated YahooTokens object
            
        Raises:
            YahooTokenExpiredError: If refresh fails and new auth is needed
        """
        if not self.tokens or not self.tokens.refresh_token:
            raise YahooTokenExpiredError("No refresh token available")
        
        logger.debug("Refreshing access token")
        
        # Prepare refresh request
        auth_header = base64.b64encode(
            f"{self.settings.yahoo_client_id}:{self.settings.yahoo_client_secret}".encode()
        ).decode('utf-8')
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.tokens.refresh_token
        }
        
        # Attempt refresh with retries
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.YAHOO_TOKEN_URL,
                        headers=headers,
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        response_data = await response.json()
                        
                        if response.status != 200:
                            error_desc = response_data.get('error_description', 'Unknown error')
                            error_code = response_data.get('error', 'unknown_error')
                            
                            if error_code == 'invalid_grant':
                                self.auth_state = AuthState.REFRESH_FAILED
                                raise YahooTokenExpiredError(
                                    "Refresh token expired, re-authentication required"
                                )
                            
                            raise YahooAuthError(f"Token refresh failed: {error_desc}")
                        
                        # Update tokens
                        access_token = response_data['access_token']
                        refresh_token = response_data.get('refresh_token', self.tokens.refresh_token)
                        expires_in = response_data.get('expires_in', 3600)
                        token_type = response_data.get('token_type', 'Bearer')
                        scope = response_data.get('scope', self.tokens.scope)
                        
                        expires_at = datetime.now() + timedelta(seconds=expires_in)
                        
                        self.tokens = YahooTokens(
                            access_token=access_token,
                            refresh_token=refresh_token,
                            token_type=token_type,
                            expires_at=expires_at,
                            scope=scope
                        )
                        
                        self.auth_state = AuthState.AUTHENTICATED
                        self._save_tokens()
                        
                        logger.info(f"Tokens refreshed, expires at {expires_at}")
                        return self.tokens
                        
            except YahooTokenExpiredError:
                raise  # Don't retry refresh token expired errors
            except Exception as e:
                if attempt == self.max_retries - 1:
                    self.auth_state = AuthState.REFRESH_FAILED
                    raise YahooTokenExpiredError(f"Failed to refresh tokens: {e}")
                
                logger.warning(f"Token refresh attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
        
        self.auth_state = AuthState.REFRESH_FAILED
        raise YahooTokenExpiredError("All token refresh attempts failed")
    
    async def ensure_authenticated(self) -> YahooTokens:
        """
        Ensure we have valid authentication tokens.
        
        This method will:
        1. Return existing tokens if valid
        2. Refresh tokens if expired but refresh token is available
        3. Raise exception if re-authentication is needed
        
        Returns:
            Valid YahooTokens object
            
        Raises:
            YahooTokenExpiredError: If re-authentication is required
        """
        if self.is_authenticated:
            return self.tokens
        
        if self.tokens and self.tokens.refresh_token:
            try:
                return await self.refresh_tokens()
            except YahooTokenExpiredError:
                pass  # Fall through to raise re-auth required
        
        raise YahooTokenExpiredError("Re-authentication required")
    
    async def get_authenticated_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers with valid authentication.
        
        Returns:
            Dictionary with Authorization header
            
        Raises:
            YahooTokenExpiredError: If re-authentication is required
        """
        tokens = await self.ensure_authenticated()
        return {
            'Authorization': f'{tokens.token_type} {tokens.access_token}',
            'User-Agent': 'Fantasy Football MCP/1.0.0'
        }
    
    @asynccontextmanager
    async def authenticated_session(self):
        """
        Context manager for authenticated HTTP session.
        
        Usage:
            async with auth.authenticated_session() as session:
                async with session.get(url) as response:
                    data = await response.json()
        """
        headers = await self.get_authenticated_headers()
        
        async with aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            yield session
    
    def revoke_tokens(self) -> None:
        """
        Revoke stored tokens and clear authentication state.
        
        This doesn't make an API call to Yahoo but clears local state.
        """
        self.tokens = None
        self.auth_state = AuthState.UNAUTHENTICATED
        
        # Remove stored tokens
        if self.token_storage_path.exists():
            try:
                self.token_storage_path.unlink()
                logger.info("Stored tokens removed")
            except Exception as e:
                logger.warning(f"Failed to remove stored tokens: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current authentication status.
        
        Returns:
            Dictionary with authentication status information
        """
        status = {
            'state': self.auth_state.value,
            'authenticated': self.is_authenticated,
            'has_tokens': self.tokens is not None,
            'redirect_uri': self.redirect_uri
        }
        
        if self.tokens:
            status.update({
                'token_type': self.tokens.token_type,
                'scope': self.tokens.scope,
                'expires_at': self.tokens.expires_at.isoformat(),
                'expires_in_seconds': self.tokens.expires_in_seconds,
                'is_expired': self.tokens.is_expired
            })
        
        return status


# Convenience functions for common usage patterns

async def get_yahoo_auth_instance(settings: Settings) -> YahooAuth:
    """
    Get a configured Yahoo auth instance.
    
    Args:
        settings: Application settings
        
    Returns:
        Configured YahooAuth instance
    """
    auth = YahooAuth(settings)
    return auth


async def quick_authenticate(
    settings: Settings,
    timeout: int = 300,
    auto_open_browser: bool = True
) -> YahooTokens:
    """
    Perform quick authentication with default settings.
    
    Args:
        settings: Application settings
        timeout: Authentication timeout in seconds
        auto_open_browser: Whether to open browser automatically
        
    Returns:
        Valid tokens
    """
    auth = YahooAuth(settings)
    return await auth.authenticate(
        timeout=timeout,
        auto_open_browser=auto_open_browser
    )


# Example usage and testing
if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    
    from config.settings import Settings
    
    async def main():
        """Example usage of Yahoo authentication."""
        settings = Settings()
        auth = YahooAuth(settings)
        
        print("Yahoo Auth Status:")
        status = auth.get_status()
        for key, value in status.items():
            print(f"  {key}: {value}")
        
        if not auth.is_authenticated:
            print("\nStarting authentication flow...")
            try:
                tokens = await auth.authenticate(timeout=300)
                print(f"✅ Authentication successful!")
                print(f"   Access token: {tokens.access_token[:20]}...")
                print(f"   Expires at: {tokens.expires_at}")
            except Exception as e:
                print(f"❌ Authentication failed: {e}")
                return
        
        # Test authenticated request
        try:
            async with auth.authenticated_session() as session:
                # Example: Get user profile
                url = f"{auth.YAHOO_API_BASE}/users;use_login=1"
                async with session.get(url) as response:
                    if response.status == 200:
                        print(f"✅ Authenticated API request successful!")
                        data = await response.text()
                        print(f"   Response length: {len(data)} characters")
                    else:
                        print(f"❌ API request failed: {response.status}")
        except Exception as e:
            print(f"❌ Authenticated request failed: {e}")
    
    # Run example
    asyncio.run(main())