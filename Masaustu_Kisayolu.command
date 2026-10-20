#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
  .venv/bin/python scripts/install_desktop_shortcut.py
else
  python3 scripts/install_desktop_shortcut.py
fi
result=$?
if [ "$result" -ne 0 ]; then
  printf '\n%s\n' 'Python 3.11 veya uzeri gerekli. Cikmak icin Enter tusuna basin.'
  read -r answer
fi
exit "$result"
