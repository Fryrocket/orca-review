#!/bin/zsh
set -euo pipefail

root_dir="${0:A:h}"
exec "${root_dir}/build.sh" "${1:-${root_dir}/build}" kiln
