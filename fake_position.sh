#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$project_dir/venv/bin/python" ]; then
    python_bin="$project_dir/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    python_bin=$(command -v python3)
else
    printf '%s\n' '未找到 Python 3，请按 README 安装运行环境。' >&2
    exit 1
fi
exec "$python_bin" -B "$project_dir/fake_position.py" "$@"
