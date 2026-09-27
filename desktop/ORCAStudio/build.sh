#!/bin/zsh
set -euo pipefail

root_dir="${0:A:h}"
output_dir="${1:-${root_dir}/build}"
app_dir="${output_dir}/ORCA Studio.app"

mkdir -p "${app_dir}/Contents/MacOS" "${app_dir}/Contents/Resources"
module_cache="${output_dir}/ModuleCache"
mkdir -p "${module_cache}"
SWIFT_MODULECACHE_PATH="${module_cache}" CLANG_MODULE_CACHE_PATH="${module_cache}" \
xcrun swiftc -O -module-cache-path "${module_cache}" -framework AppKit -framework WebKit -framework Security \
  "${root_dir}/main.swift" -o "${app_dir}/Contents/MacOS/ORCAStudio"
cp "${root_dir}/Info.plist" "${app_dir}/Contents/Info.plist"
codesign --force --deep --sign - "${app_dir}"
printf '%s\n' "${app_dir}"
