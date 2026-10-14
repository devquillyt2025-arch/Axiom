#!/usr/bin/env bash
# One command: set up (first run only) and boot the API (:8000) + web app (:3000).
#   ./start.sh          dev mode (hot reload)
#   ./start.sh --prod   production build + start
# Works in Git Bash on Windows as well as macOS/Linux. Needs Node 18+ and Python 3.10+.
set -euo pipefail
cd "$(dirname "$0")"

command -v node >/dev/null || { echo "✖ Node.js 18+ is required (https://nodejs.org)"; exit 1; }

node scripts/setup.mjs
exec node scripts/dev.mjs "$@"
