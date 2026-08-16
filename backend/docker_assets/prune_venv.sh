#!/bin/sh
# Strips build- and test-only payload from an installed venv, for the image only.
# Runs in Dockerfile.prod's builder stage, so it feeds both the prod and dev images.
set -eu

VENV="${1:-/opt/venv}"
SITE="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"

find "$SITE" -type d \( -name test -o -name tests \) -prune -exec rm -rf {} +
find "$SITE" -type d -name __pycache__ -prune -exec rm -rf {} +
