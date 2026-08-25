#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON:-python3}

(
  cd "$REPOSITORY_ROOT/backend"
  PYTHONPATH=. "$PYTHON_BIN" -m unittest discover -s tests -v
  "$PYTHON_BIN" -m compileall -q app tests
)

(
  cd "$REPOSITORY_ROOT/frontend"
  npm run check
  npm run build
)

(
  cd "$REPOSITORY_ROOT/skills"
  PYTHON="$PYTHON_BIN" bash ./tests/run_smoke_tests.sh
)

echo "All Hoosland-real-estate-research-toolset checks passed"
