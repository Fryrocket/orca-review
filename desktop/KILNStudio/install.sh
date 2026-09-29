#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "$0")" && pwd)"
app_dir="${HOME}/.local/lib/kiln-studio"
launcher_dir="${HOME}/.local/share/applications"
icon_dir="${HOME}/.local/share/icons/hicolor/scalable/apps"
desktop_dir="${HOME}/Desktop"

install -d -m 0755 "$app_dir" "$launcher_dir" "$icon_dir" "$desktop_dir"
install -m 0755 "$root_dir/kiln-studio.py" "$app_dir/kiln-studio.py"
install -m 0644 "$root_dir/project_builder.py" "$app_dir/project_builder.py"
install -m 0755 "$root_dir/kicad10-launch" "$app_dir/kicad10-launch"
install -m 0644 "$root_dir/kiln-studio.svg" "$icon_dir/kiln-studio.svg"
install -m 0755 "$root_dir/kiln-studio.desktop" "$launcher_dir/kiln-studio.desktop"
install -m 0755 "$root_dir/kiln-studio.desktop" "$desktop_dir/KILN Studio.desktop"
for launcher in "$root_dir"/kicad10/*.desktop; do
  install -m 0644 "$launcher" "$launcher_dir/$(basename "$launcher")"
done

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$launcher_dir" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi
gio set "$desktop_dir/KILN Studio.desktop" metadata::trusted true >/dev/null 2>&1 || true
