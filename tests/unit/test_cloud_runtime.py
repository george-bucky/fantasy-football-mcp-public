"""Cloud entrypoint checks use synthetic values and never call a provider."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "cloud_mcp.py"


def clean_environment():
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("YAHOO_", "PROPLINE_", "REDDIT_", "OPENAI_", "FANTASY_CLOUD_"))
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_config_preview_contains_names_not_credentials(tmp_path):
    env = clean_environment()
    env["YAHOO_CLIENT_SECRET"] = "synthetic-do-not-print"
    result = subprocess.run(
        [sys.executable, "-B", str(LAUNCHER), "--config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)["mcp_servers"]["yahoo-fantasy-football"]
    assert config["args"] == ["-B", str(LAUNCHER)]
    assert config["cwd"] == str(ROOT)
    assert "YAHOO_TOKEN_STORE" in config["env_vars"]
    assert "synthetic-do-not-print" not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


def test_root_cloud_mode_does_not_read_dotenv(tmp_path):
    # The real root module is imported in a fresh process. Any dotenv read fails the test.
    code = f"""
import dotenv, os, runpy, sys
def forbidden(*a, **kw):
    raise AssertionError('dotenv read in cloud mode')
dotenv.load_dotenv = forbidden
sys.path.insert(0, {str(ROOT)!r})
os.environ['FANTASY_CLOUD_RUNTIME'] = '1'
runpy.run_path({str(ROOT / 'fantasy_football_multi_league.py')!r}, run_name='cloud_test')
print('cloud-import-ok')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env=clean_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "cloud-import-ok"


def test_real_cloud_stdio_contract_in_fresh_process(tmp_path):
    env = clean_environment()
    env.update({"YAHOO_ACCESS_TOKEN": "synthetic-do-not-use", "YAHOO_TOKEN_STORE": "/missing"})
    result = subprocess.run(
        [sys.executable, "-B", str(LAUNCHER), "--check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    assert "all 23 tools (network disabled)" in result.stdout
    assert "synthetic-do-not-use" not in result.stdout + result.stderr


def test_contract_check_network_guard():
    # Use a subprocess so the socket guard cannot affect other tests.
    code = f"""
import runpy, socket
m = runpy.run_path({str(LAUNCHER)!r})
m['block_network']()
try:
    socket.create_connection(('127.0.0.1', 1))
except OSError as exc:
    assert str(exc) == 'Network disabled during local MCP contract check'
else:
    raise AssertionError('network guard missing')
"""
    subprocess.run([sys.executable, "-B", "-c", code], check=True, env=clean_environment())


def test_setup_rejects_symlink_venv_without_running_external_python(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    setup = scripts / "cloud_setup.sh"
    setup.write_bytes((ROOT / "scripts" / "cloud_setup.sh").read_bytes())
    external = tmp_path / "external-environment"
    external.mkdir()
    sentinel = external / "python"
    marker = external / "executed"
    sentinel.write_text('#!/bin/sh\ntouch "$(dirname "$0")/executed"\nexit 1\n')
    sentinel.chmod(0o700)
    original = sentinel.read_bytes()
    (checkout / ".venv").symlink_to(external, target_is_directory=True)
    env = clean_environment()
    env["PYTHON_BIN"] = str(sentinel)

    result = subprocess.run(
        ["bash", str(setup)], env=env, capture_output=True, text=True, check=False
    )

    assert result.returncode == 1
    assert "Refusing symlink .venv" in result.stderr
    assert not marker.exists()
    assert sentinel.read_bytes() == original
    assert list(external.iterdir()) == [sentinel]


# Frozen from the current main 23-tool contract, including every nested schema.
# Update deliberately only with an independently reviewed public tool change.
SCHEMA_SHA256 = "a8a4e47e502f404f3cec78c6f3067c9e99bec2e0035c93abb5b750451c2f9563"


def test_actual_cloud_tool_diagnostics_do_not_corrupt_protocol(tmp_path):
    code = f"""
import asyncio, runpy
launcher = runpy.run_path({str(LAUNCHER)!r})
launcher['prepare_runtime']()
launcher['block_network']()
import fantasy_football_multi_league as root
async def noisy(arguments):
    print('synthetic-provider-diagnostic')
    return {{'status':'success','synthetic':True}}
root.TOOL_HANDLERS['ff_get_api_status'] = noisy
asyncio.run(root.main())
"""

    async def exercise():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-c",
            code,
            cwd=tmp_path,
            env=clean_environment(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def send(payload):
            process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()

        async def response(identifier):
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), 20)
                assert line, "MCP subprocess closed before response"
                # Every stdout line must be JSON-RPC, including during tool IO.
                payload = json.loads(line)
                assert payload["jsonrpc"] == "2.0"
                if payload.get("id") == identifier:
                    return payload

        try:
            await send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "synthetic-test", "version": "1"},
                    },
                }
            )
            assert "result" in await response(1)
            await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tools = (await response(2))["result"]["tools"]
            assert len(tools) == 23
            schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
            digest = hashlib.sha256(
                json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            assert digest == SCHEMA_SHA256
            await send(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "ff_get_api_status", "arguments": {}},
                }
            )
            result = await response(3)
            text = result["result"]["content"][0]["text"]
            assert json.loads(text) == {"status": "success", "synthetic": True}
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 20)
            stderr = (await process.stderr.read()).decode()
            assert "synthetic-provider-diagnostic" in stderr
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(exercise())


def test_setup_normal_flow_in_mock_checkout_never_installs(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    setup = scripts / "cloud_setup.sh"
    setup.write_bytes((ROOT / "scripts" / "cloud_setup.sh").read_bytes())
    mock_python = tmp_path / "mock-python"
    log = tmp_path / "commands"
    # All setup invocations are a synthetic shell stub, including pip/venv/check.
    mock_python.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SETUP_LOG"\nif [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n mkdir -p .venv/bin\n cp "$0" .venv/bin/python\n chmod 700 .venv/bin/python\nfi\nexit 0\n'
    )
    # Record the effective setting specifically at the synthetic pip boundary.
    stub = mock_python.read_text().replace(
        "exit 0\n",
        'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
        ' printf "pip-config=%s\\n" "$PIP_CONFIG_FILE" >> "$SETUP_LOG"\n'
        "fi\nexit 0\n",
    )
    mock_python.write_text(stub)
    mock_python.chmod(0o700)
    hostile_config = tmp_path / "inherited-pip.conf"
    hostile_config.write_text("[global]\ntarget = /synthetic-forbidden-target\n")
    env = clean_environment()
    env.update(
        PYTHON_BIN=str(mock_python),
        SETUP_LOG=str(log),
        PIP_CONFIG_FILE=str(hostile_config),
    )
    result = subprocess.run(
        ["bash", str(setup)], cwd=tmp_path, env=env, capture_output=True, text=True, check=True
    )
    commands = log.read_text().splitlines()
    assert "-m venv .venv" in commands
    assert any(
        "-m pip --isolated install --no-cache-dir --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt"
        == c
        for c in commands
    )
    assert "pip-config=/dev/null" in commands
    assert hostile_config.read_text() == "[global]\ntarget = /synthetic-forbidden-target\n"
    assert "scripts/cloud_mcp.py --check" in commands
    assert "No credentials or MCP registration created" in result.stdout
    assert not (tmp_path / ".venv").exists()


def test_setup_rejects_linked_bin_before_executing_external_interpreter(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    setup = scripts / "cloud_setup.sh"
    setup.write_bytes((ROOT / "scripts" / "cloud_setup.sh").read_bytes())
    external = tmp_path / "external"
    external.mkdir()
    (external / "python").write_text('#!/bin/sh\ntouch "$(dirname "$0")/executed"\nexit 0\n')
    (external / "python").chmod(0o700)
    (checkout / ".venv").mkdir()
    (checkout / ".venv" / "bin").symlink_to(external, target_is_directory=True)
    env = clean_environment()
    env["PYTHON_BIN"] = sys.executable
    result = subprocess.run(
        ["bash", str(setup)], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "refusing to overwrite" in result.stderr
    assert list(external.iterdir()) == [external / "python"]


def test_pip_devnull_disables_hostile_global_and_site_configs(tmp_path, monkeypatch):
    # Exercise pip's real config loader, never its installer or any network path.
    from pip._internal import configuration

    paths = {}
    for kind in (configuration.kinds.GLOBAL, configuration.kinds.USER, configuration.kinds.SITE):
        path = tmp_path / f"{kind}.conf"
        path.write_text(
            "[global]\n"
            "target = /synthetic-forbidden-target\n"
            "prefix = /synthetic-forbidden-prefix\n"
            "extra-index-url = https://synthetic.invalid/simple\n"
        )
        paths[kind] = [str(path)]
    monkeypatch.setattr(configuration, "get_configuration_files", lambda: paths)
    monkeypatch.delenv("PIP_CONFIG_FILE", raising=False)
    control = configuration.Configuration(isolated=True)
    control.load()
    # Regression precondition: --isolated alone still consumes global/site files.
    assert control.get_value("global.target") == "/synthetic-forbidden-target"
    assert control.get_value("global.extra-index-url") == "https://synthetic.invalid/simple"
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    isolated = configuration.Configuration(isolated=True)
    isolated.load()
    assert list(isolated.items()) == []
