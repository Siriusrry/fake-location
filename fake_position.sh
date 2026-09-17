#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=$(command -v python || command -v python3)
exec "$python_bin" -B "$project_dir/fake_position.py" "$@"
