#!/bin/bash
set -e
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Không tìm thấy python3. Hãy cài Python 3.11+."; exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Không tìm thấy ffmpeg. Trên macOS: brew install ffmpeg"; exit 1
fi
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e '.[full]'
echo "\nCài xong LoopGen Studio v0.9.0"
echo "Chạy: ./run_loopgen.command"
