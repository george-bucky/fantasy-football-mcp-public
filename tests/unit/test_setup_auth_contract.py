"""Static contract checks for the interactive Yahoo setup script."""

import ast
from pathlib import Path


SETUP_SCRIPT = Path(__file__).resolve().parents[2] / "utils" / "setup_yahoo_auth.py"


def test_setup_uses_current_season_and_yfpy_supported_arguments():
    source = SETUP_SCRIPT.read_text()
    tree = ast.parse(source)
    query_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "YahooFantasySportsQuery"
    )
    keywords = {keyword.arg: keyword.value for keyword in query_call.keywords}

    assert isinstance(keywords["game_id"], ast.Constant)
    assert keywords["game_id"].value is None
    assert "yahoo_consumer_key" in keywords
    assert "yahoo_consumer_secret" in keywords
    assert isinstance(keywords["env_file_location"], ast.Name)
    assert keywords["env_file_location"].id == "PROJECT_ROOT"

    league_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get_user_leagues_by_game_key"
    ]
    assert any(
        call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "nfl"
        for call in league_calls
    )

    oauth_fields = {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "query"
        and node.args[0].attr == "oauth"
        and isinstance(node.args[1], ast.Constant)
    }
    assert {"access_token", "refresh_token", "guid"} <= oauth_fields
    stale_token_data_reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "token_data"
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "query"
        and node.value.attr == "oauth"
    ]
    assert stale_token_data_reads == []
