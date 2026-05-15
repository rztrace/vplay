#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${PYTHON:-python3}"

if [[ -x "$root/.venv/bin/python" ]]; then
  python="$root/.venv/bin/python"
fi

if ! "$python" -m pip show pyinstaller >/dev/null 2>&1; then
  "$python" -m pip install pyinstaller
fi

arch="$(uname -m)"
case "$arch" in
  arm64) asset_arch="arm64" ;;
  x86_64) asset_arch="x86_64" ;;
  *) asset_arch="$arch" ;;
esac

rm -rf "$root/build" "$root/dist"
"$python" -m PyInstaller \
  --clean \
  --onefile \
  --name vplay \
  --collect-submodules vplay.modules \
  --add-data "$root/vplay/mpv/vplay.lua:vplay/mpv" \
  "$root/packaging/portable/launcher.py"

asset="vplay-macos-${asset_arch}.tar.gz"
tar -C "$root/dist" -czf "$root/dist/$asset" vplay
shasum -a 256 "$root/dist/$asset" > "$root/dist/$asset.sha256"

echo "$root/dist/$asset"
