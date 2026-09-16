#!/bin/zsh
set -eu
cd -- "${0:A:h}"
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
exec /usr/bin/sandbox-exec -f config/offline.sb .venv/bin/python -m app.cli ui
