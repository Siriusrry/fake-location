#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Siriusrry

set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$project_dir/.fake_position/launcher.sh" ]; then
    exec /bin/sh "$project_dir/.fake_position/launcher.sh" "$project_dir/fake_position.py" "$@"
fi
python_bin=$(command -v python || command -v python3)
exec "$python_bin" -B "$project_dir/fake_position.py" "$@"
