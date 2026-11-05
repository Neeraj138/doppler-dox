#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v ffmpeg >/dev/null; then
  echo "Install ffmpeg first (required for media import)." >&2
  exit 1
fi
exec python -m doppler_dox serve "$@"
