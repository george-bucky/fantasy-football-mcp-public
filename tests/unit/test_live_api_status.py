"""Tests for truthful live API script exit status."""

import runpy
from pathlib import Path


LIVE_SCRIPT = Path(__file__).resolve().parents[1] / "test_live_api.py"
live_test_exit_code = runpy.run_path(str(LIVE_SCRIPT))["live_test_exit_code"]


def test_live_api_succeeds_only_when_every_check_passes():
    assert live_test_exit_code([{"success": True}, {"success": True}]) == 0
    assert live_test_exit_code([{"success": True}, {"success": False}]) == 1
    assert live_test_exit_code([]) == 1
