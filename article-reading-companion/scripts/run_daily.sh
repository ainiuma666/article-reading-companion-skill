#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${ARTICLE_DEEP_READING_PYTHON:-python3}"

exec "$python_bin" "$skill_dir/scripts/article_deep_reading.py" "$@"
