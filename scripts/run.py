#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bootstrap import BootstrapError, ensure_runtime, find_compatible_python, host_is_compatible


SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> int:
    if not host_is_compatible():
        compatible = find_compatible_python()
        if compatible is not None:
            return subprocess.run(
                [str(compatible), str(Path(__file__).resolve()), *sys.argv[1:]],
                check=False,
            ).returncode
    try:
        runtime_python = ensure_runtime()
    except (BootstrapError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "ok": False,
            "stage": "bootstrap",
            "error": str(exc),
            "hint": "首次运行需要联网，并要求 64-bit CPython 3.9+。",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    if sys.argv[1:] == ["--bootstrap-only"]:
        print(json.dumps({"ok": True, "runtime_python": str(runtime_python)}, ensure_ascii=False, indent=2))
        return 0

    command = [str(runtime_python), str(SCRIPT_DIR / "pipeline.py"), *sys.argv[1:]]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
