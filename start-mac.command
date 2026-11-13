#!/bin/bash
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then echo 'Python 3 requis (https://python.org)'; read -r; exit 1; fi
if [ ! -d .venv ]; then python3 -m venv .venv || exit 1; fi
source .venv/bin/activate
if [ -f .env.appwrite ]; then
  set -a
  source .env.appwrite
  set +a
fi
python -m pip install -r requirements.txt || exit 1
open http://127.0.0.1:8000
uvicorn server:app --host 127.0.0.1 --port 8000
