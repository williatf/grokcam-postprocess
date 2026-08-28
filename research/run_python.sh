#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment_dir="${RESEARCH_ENV_DIR:-${repo_root}/work/research-venv}"
research_cache="${RESEARCH_CACHE_DIR:-${repo_root}/work/research-cache}"

mkdir -p "${research_cache}/matplotlib" "${research_cache}/xdg"
export MPLCONFIGDIR="${research_cache}/matplotlib"
export XDG_CACHE_HOME="${research_cache}/xdg"
exec "${environment_dir}/bin/python" "$@"

