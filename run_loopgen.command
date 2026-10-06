#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/bin/activate ]; then
  echo "Chưa setup. Đang chạy setup..."
  ./setup_loopgen.command
fi
source .venv/bin/activate
exec loopgen-studio
