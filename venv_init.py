# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Siriusrry

"""Bind the local launcher to the Python running this script."""

import os
from pathlib import Path
import shlex
import sys
import tempfile


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11+ is required.")

    # Do not resolve symlinks: a venv executable may point to the base Python.
    python = os.path.abspath(sys.executable)
    directory = Path(__file__).resolve().parent / ".fake_position"
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / "launcher.sh"
    content = (
        "#!/bin/sh\n"
        f"python_bin={shlex.quote(python)}\n"
        'if [ ! -x "$python_bin" ]; then\n'
        "    printf '%s\\n' 'Configured Python is unavailable; rerun venv_init.py with your Python.' >&2\n"
        "    exit 1\n"
        "fi\n"
        'exec "$python_bin" -B "$@"\n'
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.chmod(0o700)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print(f"Configured Python: {python}")
    print("Run ./fake_position.sh <latitude> <longitude>; no environment activation needed.")


if __name__ == "__main__":
    main()
