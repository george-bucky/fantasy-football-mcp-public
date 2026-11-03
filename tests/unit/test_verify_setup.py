"""Tests for the credential-safe readiness checker."""

import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from utils import verify_setup


def test_is_configured_rejects_blanks_and_placeholders():
    assert verify_setup.is_configured(None) is False
    assert verify_setup.is_configured("") is False
    assert verify_setup.is_configured("your_access_token") is False
    assert verify_setup.is_configured("real-value") is True


def test_yahoo_access_stays_pending_without_token(capsys):
    assert verify_setup.check_yahoo_access({}) == "pending"
    assert "PENDING" in capsys.readouterr().out


def test_yahoo_access_recognizes_pending_approval_without_printing_token(capsys):
    response = Mock(
        status_code=401,
        text='oauth_problem="additional_authorization_required"',
    )
    with patch("requests.get", return_value=response) as request:
        status = verify_setup.check_yahoo_access({"YAHOO_ACCESS_TOKEN": "secret-token"})

    assert status == "pending"
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in capsys.readouterr().out


def test_yahoo_access_reports_success(capsys):
    with patch(
        "requests.get",
        return_value=Mock(status_code=200, text=""),
    ):
        status = verify_setup.check_yahoo_access({"YAHOO_ACCESS_TOKEN": "secret-token"})

    assert status == "ready"
    assert "secret-token" not in capsys.readouterr().out


def test_yahoo_access_reports_request_failure_without_printing_token(capsys):
    import requests

    with patch("requests.get", side_effect=requests.ConnectionError):
        status = verify_setup.check_yahoo_access({"YAHOO_ACCESS_TOKEN": "secret-token"})

    assert status == "failed"
    assert "secret-token" not in capsys.readouterr().out


def test_env_file_rejects_broad_permissions(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("YAHOO_CLIENT_ID=\n")
    env_file.chmod(0o644)
    monkeypatch.setattr(verify_setup, "ENV_FILE", env_file)

    ready, _values = verify_setup.check_env_file()

    assert ready is False
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o644
    assert "chmod 600" in capsys.readouterr().out


def test_codex_registration_rejects_wrong_paths(capsys):
    result = Mock(returncode=0, stdout="command: /wrong/python\nargs: /wrong/server.py")
    with (
        patch("utils.verify_setup.shutil.which", return_value="/usr/bin/codex"),
        patch("utils.verify_setup.subprocess.run", return_value=result),
    ):
        assert verify_setup.check_codex_registration() is False

    assert "different Python or server script" in capsys.readouterr().out


def test_codex_registration_rejects_near_match_paths(capsys):
    expected_python = verify_setup.PROJECT_ROOT / ".venv" / "bin" / "python"
    result = Mock(
        returncode=0,
        stdout=(
            f"command: {expected_python}-old\n"
            f"args: {verify_setup.SERVER_SCRIPT}.bak\n"
        ),
    )
    with (
        patch("utils.verify_setup.shutil.which", return_value="/usr/bin/codex"),
        patch("utils.verify_setup.subprocess.run", return_value=result),
    ):
        assert verify_setup.check_codex_registration() is False

    assert "different Python or server script" in capsys.readouterr().out


def test_dependency_check_reports_missing_package(capsys):
    original_import = verify_setup.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "yfpy":
            raise ImportError
        return original_import(name, *args, **kwargs)

    with patch("utils.verify_setup.importlib.import_module", side_effect=fake_import):
        assert verify_setup.check_dependencies() is False

    assert "yfpy" in capsys.readouterr().out


@pytest.mark.parametrize("missing_tool", [None, "ff_get_roster"])
async def test_mcp_handshake_checks_current_tool_contract(missing_tool, capsys):
    tool_names = {
        "ff_get_leagues",
        "ff_get_league_info",
        "ff_get_standings",
        "ff_get_teams",
        "ff_get_roster",
        "ff_get_matchup",
        "ff_get_players",
        "ff_compare_teams",
        "ff_build_lineup",
        "ff_refresh_token",
        "ff_get_draft_results",
        "ff_get_waiver_wire",
        "ff_get_api_status",
        "ff_clear_cache",
        "ff_get_draft_rankings",
        "ff_get_draft_recommendation",
        "ff_analyze_draft_state",
        "ff_analyze_reddit_sentiment",
        "ff_get_player_news",
        "ff_prepare_manual_draft",
        "ff_get_manual_draft_recommendation",
        "ff_get_espn_nfl_news",
        "ff_get_sportsbook_odds",
    }
    if missing_tool:
        tool_names.remove(missing_tool)

    transport = AsyncMock()
    transport.__aenter__.return_value = (Mock(), Mock())
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.list_tools.return_value = Mock(
        tools=[SimpleNamespace(name=tool_name) for tool_name in tool_names]
    )

    with (
        patch("mcp.client.stdio.stdio_client", return_value=transport),
        patch("mcp.ClientSession", return_value=session),
    ):
        assert await verify_setup.check_mcp_server() is (missing_tool is None)

    output = capsys.readouterr().out
    if missing_tool:
        assert "tool contract mismatch" in output
    else:
        assert "PASS: server initialized with all 23 tools" in output


async def test_main_returns_failure_when_a_local_check_fails(monkeypatch):
    monkeypatch.setattr(verify_setup, "check_env_file", lambda: (True, {}))
    monkeypatch.setattr(verify_setup, "check_dependencies", lambda: True)
    monkeypatch.setattr(verify_setup, "check_codex_registration", lambda: False)
    monkeypatch.setattr(verify_setup, "check_mcp_server", AsyncMock(return_value=True))
    monkeypatch.setattr(verify_setup, "check_yahoo_access", lambda _values: "pending")

    assert await verify_setup.main() == 1


async def test_main_returns_success_while_yahoo_is_pending(monkeypatch):
    monkeypatch.setattr(verify_setup, "check_env_file", lambda: (True, {}))
    monkeypatch.setattr(verify_setup, "check_dependencies", lambda: True)
    monkeypatch.setattr(verify_setup, "check_codex_registration", lambda: True)
    monkeypatch.setattr(verify_setup, "check_mcp_server", AsyncMock(return_value=True))
    monkeypatch.setattr(verify_setup, "check_yahoo_access", lambda _values: "pending")

    assert await verify_setup.main() == 0
