#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Once kurulum yapin: python3 -m venv .venv' '.venv/bin/python -m pip install -e .'
  exit 1
fi
exec .venv/bin/python app.py
