#!/usr/bin/env bash
# Non-secret dependency setup. Does not register MCP or provision credentials/state.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -L .venv ]]; then
  echo 'Refusing symlink .venv; setup must not modify an external environment.' >&2
  exit 1
fi
python_bin="${PYTHON_BIN:-python3.11}"
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else "Python 3.11 is required")'
if [[ -e .venv && ( ! -d .venv || ! -x .venv/bin/python || -L .venv/bin || -L .venv/pyvenv.cfg ) ]]; then
  echo 'Existing .venv is not a usable Python environment; refusing to overwrite it.' >&2
  exit 1
fi
if [[ ! -e .venv ]]; then
  "$python_bin" -m venv .venv
fi
# A real local venv may symlink its interpreter to the base Python binary.
# Verify sys.prefix before pip so a linked external environment cannot be edited.
.venv/bin/python - <<'PYTHON'
import pathlib
import sys
import sysconfig

expected = pathlib.Path.cwd() / ".venv"
valid = (
    sys.version_info[:2] == (3, 11)
    and sys.prefix != sys.base_prefix
    and pathlib.Path(sys.prefix).resolve() == expected.resolve()
    and all(pathlib.Path(sysconfig.get_path(key)).resolve().is_relative_to(expected.resolve())
            for key in ("purelib", "platlib", "scripts", "data"))
)
sys.exit(0 if valid else "Existing .venv must be a local Python 3.11 venv; it was not changed")
PYTHON
# Disable every pip config source, including global/site files ignored by neither
# --isolated alone, and avoid writing to a shared HOME package cache.
PIP_CONFIG_FILE=/dev/null .venv/bin/python -m pip --isolated install --no-cache-dir --disable-pip-version-check \
  --index-url https://pypi.org/simple -r requirements.txt
.venv/bin/python scripts/cloud_mcp.py --check
echo 'Dependencies and local MCP contract verified. No credentials or MCP registration created.'
