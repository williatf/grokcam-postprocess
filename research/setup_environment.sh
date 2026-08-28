#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
research_python="${RESEARCH_PYTHON:-python3}"
environment_dir="${RESEARCH_ENV_DIR:-${repo_root}/work/research-venv}"

"${research_python}" -m venv "${environment_dir}"
"${environment_dir}/bin/python" -m pip install --upgrade pip setuptools wheel
"${environment_dir}/bin/python" -m pip install -r "${repo_root}/research/requirements-lock.txt"
"${environment_dir}/bin/python" "${repo_root}/research/check_environment.py"

printf 'Research environment ready: %s\n' "${environment_dir}"
printf 'Activate with: source %s/bin/activate\n' "${environment_dir}"
