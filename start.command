#!/bin/zsh
set -u

cd "$(dirname "$0")"
clear

echo "NTU Nursing Line Bot"
echo

export PYTHONIOENCODING=utf-8

if [ -f .env ]; then
  while IFS='=' read -r key value; do
    if [ "$key" = "LMS_CLI_PATH" ]; then
      export LMS_CLI_PATH="$value"
    elif [ "$key" = "LM_STUDIO_HOST" ]; then
      export LM_STUDIO_HOST="$value"
    fi
  done < .env
fi

LMS_PATH="${LMS_CLI_PATH:-$HOME/.lmstudio/bin/lms}"
VENV_DIR="${NTU_LINE_BOT_VENV:-/private/tmp/ntu-nursing-line-bot-venv}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/private/tmp/ntu-nursing-line-bot-pip-cache}"

if [ ! -x "$LMS_PATH" ]; then
  echo "Cannot find LM Studio CLI at: $LMS_PATH"
  echo "Set LMS_CLI_PATH in .env if LM Studio installed it somewhere else."
  echo
  echo "Press Enter to close..."
  read -r _
  exit 1
fi

lm_studio_ready() {
  curl -fsS --max-time 3 "${LM_STUDIO_HOST:-http://127.0.0.1:1234}/v1/models" >/dev/null 2>&1
}

if ! lm_studio_ready; then
  echo "LM Studio API server is not reachable. Starting it..."
  "$LMS_PATH" server start >/dev/null 2>&1 &
  for attempt in {1..15}; do
    sleep 2
    if lm_studio_ready; then
      break
    fi
  done
  if lm_studio_ready; then
    echo "LM Studio API server is ready."
  else
    echo "LM Studio API server is still not reachable; the bot will start, but model calls may fail."
  fi
else
  echo "LM Studio API server is already running."
fi

echo
if [ -x "$VENV_DIR/bin/python" ]; then
  PYTHON_CMD="$VENV_DIR/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_CMD="python3.12"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_CMD="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
else
  echo "Cannot find python3. Install Python 3.12+ and try again."
  echo
  echo "Press Enter to close..."
  read -r _
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_CMD" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"

case "$PYTHON_VERSION" in
  3.11|3.12|3.13|3.14)
    ;;
  *)
    echo "Unsupported Python version: $PYTHON_VERSION"
    echo "Install Python 3.11+ and try again. The macOS system Python 3.9 is too old for this project."
    echo
    echo "Press Enter to close..."
    read -r _
    exit 1
    ;;
esac

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creating local Python environment..."
  "$PYTHON_CMD" -m venv "$VENV_DIR"
  PYTHON_CMD="$VENV_DIR/bin/python"
fi

if ! "$PYTHON_CMD" - <<'PY' >/dev/null 2>&1
import flask
import requests
import faiss
import numpy
import fitz
PY
then
  echo "Installing Python dependencies..."
  if ! "$PYTHON_CMD" -m pip --disable-pip-version-check install -r requirements.txt; then
    echo
    echo "Failed to install Python dependencies."
    echo "Check your internet connection, then run this launcher again."
    echo
    echo "Press Enter to close..."
    read -r _
    exit 1
  fi
fi

echo
echo "Choose a mode:"
echo "1 = CLI test mode"
echo "2 = Flask webhook mode"
echo "3 = Both"

while true; do
  printf "> "
  read -r mode
  case "$mode" in
    1|2|3)
      break
      ;;
    *)
      echo "Invalid option. Please enter 1, 2, or 3."
      ;;
  esac
done

"$PYTHON_CMD" -X utf8 LB.py "$mode"

exit_code=$?
echo
echo "Bot exited with status $exit_code."
echo "Press Enter to close..."
read -r _
exit "$exit_code"
