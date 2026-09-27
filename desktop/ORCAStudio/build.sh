#!/bin/zsh
set -euo pipefail

root_dir="${0:A:h}"
output_dir="${1:-${root_dir}/build}"
profile="${2:-orca}"

case "${profile}" in
  orca)
    app_name="ORCA Studio"
    executable_name="ORCAStudio"
    bundle_id="com.fryrocket.orca-studio"
    studio_node_id="ANVIL"
    studio_url="http://127.0.0.1:8788/"
    ;;
  kiln)
    app_name="KILN Studio"
    executable_name="KILNStudio"
    bundle_id="com.fryrocket.kiln-studio"
    studio_node_id="KILN"
    studio_url="http://127.0.0.1:18788/"
    ;;
  *)
    printf 'Unknown Studio profile: %s (expected orca or kiln)\n' "${profile}" >&2
    exit 2
    ;;
esac

app_dir="${output_dir}/${app_name}.app"

mkdir -p "${app_dir}/Contents/MacOS" "${app_dir}/Contents/Resources"
module_cache="${output_dir}/ModuleCache"
mkdir -p "${module_cache}"
SWIFT_MODULECACHE_PATH="${module_cache}" CLANG_MODULE_CACHE_PATH="${module_cache}" \
xcrun swiftc -O -module-cache-path "${module_cache}" -framework AppKit -framework WebKit -framework Security \
  "${root_dir}/main.swift" -o "${app_dir}/Contents/MacOS/${executable_name}"
cp "${root_dir}/Info.plist" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName ${app_name}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable ${executable_name}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier ${bundle_id}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName ${app_name}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :StudioName ${app_name}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :StudioNodeID ${studio_node_id}" "${app_dir}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :StudioURL ${studio_url}" "${app_dir}/Contents/Info.plist"
if [[ "${profile}" == "kiln" ]]; then
  /usr/libexec/PlistBuddy -c "Add :StudioSSHTunnelHost string kiln-ts" "${app_dir}/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :StudioSSHTunnelLocalPort integer 18788" "${app_dir}/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c "Add :StudioSSHTunnelRemotePort integer 8788" "${app_dir}/Contents/Info.plist"
  iconset="${output_dir}/KILNStudio.iconset"
  rm -rf "${iconset}"
  xcrun swift "${root_dir}/make-kiln-icon.swift" "${iconset}"
  iconutil -c icns "${iconset}" -o "${app_dir}/Contents/Resources/KILNStudio.icns"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string KILNStudio" "${app_dir}/Contents/Info.plist"
fi
codesign --force --deep --sign - "${app_dir}"
printf '%s\n' "${app_dir}"
