#!/usr/bin/env bash
# Back-compat wrapper — use ./demo.sh from the repo root.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/demo.sh" "$@"
