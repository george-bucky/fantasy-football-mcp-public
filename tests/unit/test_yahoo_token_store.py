"""Synthetic-only persistence and rotation checks; never use provider credentials."""

import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api import yahoo_client
from src.api.yahoo_token_store import TokenPair, TokenStoreError, YahooTokenStore


@pytest.fixture(autouse=True)
def isolated_token_state(monkeypatch, tmp_path):
    home = tmp_path / "synthetic-home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("YAHOO_TOKEN_STORE", raising=False)
    monkeypatch.delenv("FANTASY_CLOUD_RUNTIME", raising=False)
    monkeypatch.setenv("YAHOO_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(yahoo_client, "_YAHOO_ACCESS_TOKEN", None)
    monkeypatch.setenv("YAHOO_ACCESS_TOKEN", "synthetic-access")
    monkeypatch.setenv("YAHOO_REFRESH_TOKEN", "synthetic-refresh")


@pytest.fixture
def store(tmp_path, monkeypatch):
    directory = tmp_path.resolve() / "private"
    directory.mkdir(mode=0o700)
    path = directory / "tokens.json"
    path.write_text(
        json.dumps({"version": 1, "access_token": "old-access", "refresh_token": "old-refresh"})
    )
    path.chmod(0o600)
    monkeypatch.setenv("YAHOO_TOKEN_STORE", str(path))
    monkeypatch.setenv("YAHOO_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(yahoo_client, "_YAHOO_ACCESS_TOKEN", None)
    return YahooTokenStore(path)


def mock_http(payload=None, status=200):
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(
        return_value=payload
        or {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}
    )
    response.text = AsyncMock(return_value="synthetic-secret-provider-error")
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.post.return_value.__aenter__ = AsyncMock(return_value=response)
    session.post.return_value.__aexit__ = AsyncMock(return_value=False)
    return session


def test_fresh_process_loads_store_over_stale_environment(store):
    env = {
        **os.environ,
        "YAHOO_ACCESS_TOKEN": "stale-injection",
        "YAHOO_REFRESH_TOKEN": "stale-refresh",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    code = (
        "from src.api.yahoo_client import get_access_token; import os; "
        "assert get_access_token() == 'old-access'; "
        "assert os.environ['YAHOO_REFRESH_TOKEN'] == 'old-refresh'"
    )
    subprocess.run([sys.executable, "-B", "-c", code], env=env, check=True, capture_output=True)
    assert not store.lock_path.exists()


async def test_rotation_persists_before_publish_and_fresh_read(store, monkeypatch):
    session = mock_http()
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "success"
    assert store.read() == TokenPair("new-access", "new-refresh")
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert session.post.call_args.kwargs["data"]["refresh_token"] == "old-refresh"
    monkeypatch.setenv("YAHOO_ACCESS_TOKEN", "stale")
    monkeypatch.setattr(yahoo_client, "_YAHOO_ACCESS_TOKEN", None)
    assert yahoo_client.get_access_token() == "new-access"


async def test_stale_failed_request_reuses_rotation_without_network(store):
    with store.locked():
        store.write(TokenPair("other-access", "other-refresh"))
    with patch("src.api.yahoo_client.aiohttp.ClientSession") as network:
        result = await yahoo_client.refresh_yahoo_token(rejected_access_token="old-access")
    assert result["status"] == "success"
    network.assert_not_called()
    assert os.environ["YAHOO_REFRESH_TOKEN"] == "other-refresh"


async def test_two_waiters_only_rotate_once(store):
    session = mock_http()
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session):
        results = await asyncio.gather(
            *[
                yahoo_client.refresh_yahoo_token(rejected_access_token="old-access")
                for _ in range(2)
            ]
        )
    assert all(r["status"] == "success" for r in results)
    assert session.post.call_count == 1


async def test_failed_persistence_does_not_publish(store, monkeypatch):
    monkeypatch.setenv("YAHOO_ACCESS_TOKEN", "before-access")
    monkeypatch.setenv("YAHOO_REFRESH_TOKEN", "before-refresh")
    monkeypatch.setattr(yahoo_client, "_YAHOO_ACCESS_TOKEN", "before-access")
    with (
        patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http()),
        patch("src.api.yahoo_token_store.os.replace", side_effect=OSError("sensitive-message")),
    ):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert "recovery" in result["message"]
    assert "sensitive-message" not in str(result)
    assert store.read() == TokenPair("old-access", "old-refresh")
    assert os.environ["YAHOO_ACCESS_TOKEN"] == "before-access"
    assert os.environ["YAHOO_REFRESH_TOKEN"] == "before-refresh"
    assert list(store.path.parent.glob(".yahoo-*")) == []


@pytest.mark.parametrize(
    "payload", [{"access_token": None}, {"access_token": "x", "refresh_token": ""}]
)
async def test_bad_provider_tokens_do_not_overwrite(store, payload):
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http(payload)):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert store.read().access_token == "old-access"


async def test_provider_error_is_redacted(store):
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http(status=400)):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert "synthetic-secret-provider-error" not in str(result)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666])
def test_public_store_rejected(store, mode):
    store.path.chmod(mode)
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


def test_public_directory_rejected(store):
    store.path.parent.chmod(0o755)
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


def test_symlink_store_rejected(store):
    original = store.path.with_name("original.json")
    store.path.rename(original)
    store.path.symlink_to(original)
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


def test_symlink_lock_rejected(store):
    store.lock_path.symlink_to(store.path)
    with pytest.raises(TokenStoreError):
        with store.locked():
            pass


def test_hardlink_store_rejected(store):
    os.link(store.path, store.path.with_name("hardlink"))
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


@pytest.mark.parametrize(
    "payload",
    ["not json", "{}", '{"version":2}', '{"version":1,"access_token":"","refresh_token":"r"}'],
)
def test_corruption_fails_closed(store, payload, monkeypatch):
    store.path.write_text(payload)
    monkeypatch.setenv("YAHOO_ACCESS_TOKEN", "fallback-must-not-be-used")
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


async def test_missing_store_not_seeded(store):
    store.path.unlink()
    result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert not store.path.exists()
    assert not store.lock_path.exists()


def test_relative_path_rejected():
    with pytest.raises(TokenStoreError):
        YahooTokenStore("tokens.json")


async def test_lock_wait_does_not_block_event_loop(store):
    entered = asyncio.Event()

    async def holder():
        async with store.async_locked():
            entered.set()
            await asyncio.sleep(0.1)

    async def waiter():
        await entered.wait()
        async with store.async_locked():
            return store.read()

    _, pair = await asyncio.gather(holder(), waiter())
    assert pair.access_token == "old-access"


async def test_cross_process_lock_serializes_refresh(store):
    code = (
        "import time; from src.api.yahoo_token_store import configured_store; "
        "store=configured_store(); "
        "context=store.locked(); context.__enter__(); "
        "print('LOCKED', flush=True); time.sleep(0.2); context.__exit__(None,None,None)"
    )
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert await asyncio.to_thread(child.stdout.readline) == "LOCKED\n"
        with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http()):
            result = await yahoo_client.refresh_yahoo_token()
        assert result["status"] == "success"
        assert child.wait(timeout=3) == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)


async def test_cancellation_releases_refresh_lock(store):
    entered = asyncio.Event()

    async def holder():
        async with store.async_locked():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(holder())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with store.async_locked():
        assert store.read().access_token == "old-access"


async def test_root_startup_loads_persisted_pair_after_rotation(store):
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http()):
        assert (await yahoo_client.refresh_yahoo_token())["status"] == "success"
    env = {
        **os.environ,
        "FANTASY_CLOUD_RUNTIME": "1",
        "YAHOO_ACCESS_TOKEN": "stale",
        "YAHOO_REFRESH_TOKEN": "stale",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    code = (
        "import fantasy_football_multi_league; import os; "
        "from src.api.yahoo_client import get_access_token; "
        "assert get_access_token() == 'new-access'; "
        "assert os.environ['YAHOO_REFRESH_TOKEN'] == 'new-refresh'"
    )
    subprocess.run([sys.executable, "-B", "-c", code], env=env, check=True, capture_output=True)


def test_fifo_store_rejected_without_blocking_startup(store):
    store.path.unlink()
    os.mkfifo(store.path, 0o600)
    code = (
        "from src.api.yahoo_client import get_access_token; "
        "from src.api.yahoo_token_store import TokenStoreError; "
        "\ntry: get_access_token()"
        "\nexcept TokenStoreError: pass"
        "\nelse: raise AssertionError('FIFO must be rejected')"
    )
    subprocess.run(
        [sys.executable, "-B", "-c", code],
        env=os.environ.copy(),
        timeout=3,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("status", [401, 500])
async def test_cloud_api_errors_redact_provider_echo(monkeypatch, status):
    monkeypatch.delenv("YAHOO_TOKEN_STORE", raising=False)
    monkeypatch.setenv("FANTASY_CLOUD_RUNTIME", "1")
    monkeypatch.setattr(yahoo_client, "_YAHOO_ACCESS_TOKEN", "synthetic-access")
    session = mock_http(status=status)
    session.get.return_value.__aenter__ = session.post.return_value.__aenter__
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session):
        with pytest.raises(Exception) as caught:
            await yahoo_client.yahoo_api_call(
                "synthetic-endpoint", retry_on_auth_fail=False, use_cache=False
            )
    assert str(status) in str(caught.value)
    assert "synthetic-secret-provider-error" not in str(caught.value)


async def test_cloud_refresh_network_error_redacted(monkeypatch):
    monkeypatch.delenv("YAHOO_TOKEN_STORE", raising=False)
    monkeypatch.setenv("FANTASY_CLOUD_RUNTIME", "1")
    for key in ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET", "YAHOO_REFRESH_TOKEN"):
        monkeypatch.setenv(key, "synthetic-secret")
    with patch(
        "src.api.yahoo_client.aiohttp.ClientSession", side_effect=RuntimeError("synthetic-secret")
    ):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert "synthetic-secret" not in str(result)


def test_environment_only_import_without_posix_lock_support(monkeypatch):
    env = {**os.environ, "FANTASY_CLOUD_RUNTIME": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("YAHOO_TOKEN_STORE", None)
    code = (
        "import sys; sys.modules['fcntl'] = None; "
        "import fantasy_football_multi_league; "
        "from src.api.yahoo_token_store import YahooTokenStore, TokenStoreError; "
        "\ntry: YahooTokenStore('/synthetic/tokens.json')"
        "\nexcept TokenStoreError: pass"
        "\nelse: raise AssertionError('unsupported store must fail')"
    )
    subprocess.run(
        [sys.executable, "-B", "-c", code], env=env, timeout=10, check=True, capture_output=True
    )


async def test_cloud_api_network_exception_redacted(monkeypatch):
    monkeypatch.delenv("YAHOO_TOKEN_STORE", raising=False)
    monkeypatch.setenv("FANTASY_CLOUD_RUNTIME", "1")
    with patch(
        "src.api.yahoo_client.aiohttp.ClientSession", side_effect=RuntimeError("synthetic-secret")
    ):
        with pytest.raises(Exception) as caught:
            await yahoo_client.yahoo_api_call("synthetic-network", use_cache=False)
    assert "synthetic-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "tokens",
    [
        TokenPair("", "r"),
        TokenPair("a", "r\n"),
        TokenPair("a b", "r"),
        TokenPair("a\x00b", "r"),
        TokenPair("a", None),
    ],
)
def test_invalid_pair_write_preserves_previous_store(store, tokens):
    with store.locked():
        with pytest.raises(TokenStoreError, match="pair is invalid"):
            store.write(tokens)
    assert store.read() == TokenPair("old-access", "old-refresh")
    assert list(store.path.parent.glob(".yahoo-*")) == []


def test_oversized_pair_write_cannot_produce_unreadable_store(store):
    with store.locked():
        with pytest.raises(TokenStoreError, match="supported size"):
            store.write(TokenPair("a" * 65536, "r"))
    assert store.read().access_token == "old-access"


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_store_version_requires_integer_schema(store, version):
    store.path.write_text(
        json.dumps({"version": version, "access_token": "a", "refresh_token": "r"})
    )
    with pytest.raises(TokenStoreError):
        store.read()


@pytest.mark.parametrize("expiry", [None, True, "3600", 0, -1, float("nan"), float("inf"), 10**400])
async def test_invalid_expiry_metadata_does_not_discard_valid_rotated_pair(store, expiry):
    with patch(
        "src.api.yahoo_client.aiohttp.ClientSession",
        return_value=mock_http(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": expiry,
            }
        ),
    ):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "success"
    assert result["expires_in"] is None
    assert result["expires_in_hours"] is None
    assert store.read() == TokenPair("new-access", "new-refresh")
    assert os.environ["YAHOO_ACCESS_TOKEN"] == "new-access"
    assert os.environ["YAHOO_REFRESH_TOKEN"] == "new-refresh"


def test_symlink_parent_directory_is_rejected(store, monkeypatch):
    link = store.path.parent.with_name("alias")
    link.symlink_to(store.path.parent, target_is_directory=True)
    monkeypatch.setenv("YAHOO_TOKEN_STORE", str(link / store.path.name))
    with pytest.raises(TokenStoreError):
        yahoo_client.get_access_token()


async def test_invalid_lock_permissions_fail_before_network(store):
    store.lock_path.write_text("")
    store.lock_path.chmod(0o644)
    with patch("src.api.yahoo_client.aiohttp.ClientSession") as network:
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    network.assert_not_called()


async def test_directory_sync_failure_reports_uncertain_durability_without_publish(store):
    real_fsync = os.fsync
    calls = 0

    def fail_directory(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic-secret-sync-error")
        real_fsync(fd)

    with (
        patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=mock_http()),
        patch("src.api.yahoo_token_store.os.fsync", side_effect=fail_directory),
    ):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert "recovery" in result["message"]
    assert "synthetic-secret" not in str(result)
    assert os.environ["YAHOO_ACCESS_TOKEN"] == "synthetic-access"
    # Rename completed: the pair may be present despite failed durability confirmation.
    assert store.read() == TokenPair("new-access", "new-refresh")
    assert yahoo_client.get_access_token() == "new-access"


async def test_cloud_provisioning_failure_retains_classification_without_refresh(monkeypatch):
    monkeypatch.setenv("FANTASY_CLOUD_RUNTIME", "1")
    session = mock_http(status=401)
    session.get.return_value.__aenter__ = session.post.return_value.__aenter__
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    response = await session.get.return_value.__aenter__()
    response.text = AsyncMock(return_value="additional_authorization_required synthetic-secret")
    with (
        patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session),
        patch("src.api.yahoo_client.refresh_yahoo_token", AsyncMock()) as refresh,
    ):
        with pytest.raises(Exception) as caught:
            await yahoo_client.yahoo_api_call("synthetic-provisioning", use_cache=False)
    assert str(caught.value) == yahoo_client.NOT_PROVISIONED_ERROR
    refresh.assert_not_awaited()


async def test_explicit_invalid_store_does_not_fall_back_to_environment_or_network(store):
    store.path.unlink()
    with patch("src.api.yahoo_client.aiohttp.ClientSession") as network:
        with pytest.raises(TokenStoreError):
            await yahoo_client.yahoo_api_call("synthetic-store-missing", use_cache=False)
    network.assert_not_called()


async def test_lock_timeout_is_bounded_and_never_calls_provider(store):
    with (
        patch("src.api.yahoo_token_store.fcntl.flock", side_effect=BlockingIOError),
        patch(
            "src.api.yahoo_token_store.time", MagicMock(monotonic=MagicMock(side_effect=[0, 31]))
        ),
        patch("src.api.yahoo_client.aiohttp.ClientSession") as network,
    ):
        result = await yahoo_client.refresh_yahoo_token()
    assert result["status"] == "error"
    assert result["message"] == "Yahoo token store lock timed out"
    network.assert_not_called()


async def test_lock_os_error_is_redacted(store):
    with patch("src.api.yahoo_token_store.fcntl.flock", side_effect=OSError("synthetic-secret")):
        result = await yahoo_client.refresh_yahoo_token()
    assert result == {"status": "error", "message": "Yahoo token lock failed"}


async def test_cancelled_waiter_does_not_release_another_tasks_lock(store):
    async with store.async_locked():
        waiter = asyncio.create_task(yahoo_client.refresh_yahoo_token())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        with pytest.raises(TokenStoreError, match="busy"):
            with store.locked():
                pass
    async with store.async_locked():
        assert store.read().access_token == "old-access"


async def test_cancelled_inflight_rotation_finishes_before_unlock_even_on_repeated_cancel(store):
    issued = asyncio.Event()
    release_response = asyncio.Event()
    session = mock_http()
    response = await session.post.return_value.__aenter__()

    async def rotated_response():
        issued.set()  # Simulate Yahoo having issued the new refresh-token pair.
        await release_response.wait()
        return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}

    response.json = rotated_response
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session) as provider:
        first = asyncio.create_task(
            yahoo_client.refresh_yahoo_token(rejected_access_token="old-access")
        )
        await issued.wait()
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()
        assert store.read() == TokenPair("old-access", "old-refresh")
        with pytest.raises(TokenStoreError, match="busy"):
            with store.locked():
                pass
        second = asyncio.create_task(
            yahoo_client.refresh_yahoo_token(rejected_access_token="old-access")
        )
        release_response.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second)["status"] == "success"
    assert store.read() == TokenPair("new-access", "new-refresh")
    assert os.environ["YAHOO_REFRESH_TOKEN"] == "new-refresh"
    assert session.post.call_count == 1
    assert provider.call_args.kwargs["timeout"].total == 60


async def test_inflight_timeout_releases_store_lock_with_redacted_error(store):
    session = mock_http()
    response = await session.post.return_value.__aenter__()
    response.json = AsyncMock(side_effect=asyncio.TimeoutError("synthetic-secret-timeout"))
    with patch("src.api.yahoo_client.aiohttp.ClientSession", return_value=session):
        result = await yahoo_client.refresh_yahoo_token()
    assert result == {"status": "error", "message": "Error refreshing token"}
    async with store.async_locked():
        assert store.read().access_token == "old-access"
