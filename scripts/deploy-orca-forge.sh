#!/usr/bin/env bash
set -euo pipefail

release_id="28340bdaabb65d673352c9b0df1f51f52754b459"
archive="/tmp/orca-release-28340bd.tar"
archive_sha="24739afde586780b5cb946d0cdf097a941768660a0576a6e5a7634b6f733b8fe"
release_dir="/opt/orca/releases/${release_id}"
state_dir="/var/lib/orca"

actual_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
[ "$actual_sha" = "$archive_sha" ] || {
  echo "release archive checksum mismatch" >&2
  exit 1
}

sudo install -d -m 0755 /opt/orca/releases
if [ ! -d "$release_dir" ]; then
  sudo install -d -m 0755 "$release_dir"
  sudo tar -xf "$archive" -C "$release_dir"
  sudo chown -R root:root "$release_dir"
  sudo find "$release_dir" -type d -exec chmod 0755 {} +
  sudo find "$release_dir" -type f -exec chmod 0644 {} +
fi

sudo install -d -o fryrocket -g fryrocket -m 0700 "$state_dir"
if [ ! -f "$state_dir/identity-tokens.json" ]; then
  sudo -u fryrocket /usr/bin/python3 -c 'import json,secrets; from pathlib import Path; p=Path("/var/lib/orca/identity-tokens.json"); p.write_text(json.dumps({name: secrets.token_urlsafe(48) for name in ("orca","smith","quench","security_gate","fry")}, sort_keys=True), encoding="utf-8"); p.chmod(0o600)'
fi

if [ -L /opt/orca/current ]; then
  previous="$(readlink /opt/orca/current)"
  printf '%s\n' "$previous" | sudo -u fryrocket tee "$state_dir/previous-release" >/dev/null
fi
sudo ln -sfn "$release_dir" /opt/orca/current
sudo install -o root -g root -m 0644 /tmp/orca.service /etc/systemd/system/orca.service

sudo systemctl daemon-reload
sudo systemctl enable --now orca.service
