#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
import uuid
import venv
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
RUNTIME_ROOT = SKILL_DIR / ".runtime"
REQUIREMENTS = SCRIPT_DIR / "requirements.lock"
PYSOCKS_WHEEL = SKILL_DIR / "assets" / "wheels" / "PySocks-1.7.1-py3-none-any.whl"


class BootstrapError(RuntimeError):
    pass


def host_is_compatible() -> bool:
    return (
        sys.version_info >= (3, 9)
        and platform.python_implementation() == "CPython"
        and struct.calcsize("P") * 8 == 64
    )


def find_compatible_python() -> Path | None:
    candidates: list[Path] = []
    for name in ("python3.14", "python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3", "python"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))

    runtime_root = Path.home() / ".cache" / "codex-runtimes"
    if runtime_root.is_dir():
        candidates.extend(runtime_root.glob("*/dependencies/python/bin/python3"))
        candidates.extend(runtime_root.glob("*/dependencies/python/python.exe"))

    probe = (
        "import platform,struct,sys;"
        "raise SystemExit(0 if sys.version_info >= (3,9) "
        "and platform.python_implementation() == 'CPython' "
        "and struct.calcsize('P')*8 == 64 else 1)"
    )
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
            if candidate in seen or candidate == Path(sys.executable).resolve():
                continue
            seen.add(candidate)
            if subprocess.run(
                [str(candidate), "-c", probe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0:
                return candidate
        except OSError:
            continue
    return None


def _check_host() -> None:
    if not host_is_compatible():
        raise BootstrapError("Requires 64-bit CPython 3.9 or newer.")


def _runtime_tag() -> str:
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower().replace(" ", "-") or "unknown"
    return f"cpython-{sys.version_info.major}{sys.version_info.minor}-{system}-{machine}"


def _runtime_python(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "Scripts" / "python.exe"
    return runtime_dir / "bin" / "python"


def _lock_digest() -> str:
    digest = hashlib.sha256()
    digest.update(REQUIREMENTS.read_bytes())
    digest.update(PYSOCKS_WHEEL.read_bytes())
    return digest.hexdigest()


def _runtime_is_valid(runtime_dir: Path, digest: str) -> bool:
    marker = runtime_dir / "runtime.json"
    python = _runtime_python(runtime_dir)
    if not marker.is_file() or not python.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if data.get("lock_digest") != digest:
        return False
    probe = (
        "import rawpy,numpy,PIL,tifffile;"
        "assert rawpy.__version__=='0.27.0';"
        "assert numpy.__version__=='1.26.4';"
        "assert PIL.__version__=='11.3.0';"
        "assert tifffile.__version__=='2024.8.30'"
    )
    return subprocess.run(
        [str(python), "-c", probe],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise BootstrapError(f"Dependency command failed with exit code {completed.returncode}: {' '.join(command)}")


def ensure_runtime() -> Path:
    _check_host()
    if not REQUIREMENTS.is_file() or not PYSOCKS_WHEEL.is_file():
        raise BootstrapError("The skill installation is incomplete: runtime lock files are missing.")

    digest = _lock_digest()
    runtime_dir = RUNTIME_ROOT / _runtime_tag()
    if _runtime_is_valid(runtime_dir, digest):
        return _runtime_python(runtime_dir)

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    lock_dir = RUNTIME_ROOT / f"{_runtime_tag()}.bootstrap-lock"
    deadline = time.monotonic() + 300
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            if _runtime_is_valid(runtime_dir, digest):
                return _runtime_python(runtime_dir)
            if time.monotonic() >= deadline:
                raise BootstrapError("Timed out waiting for another dependency bootstrap process.")
            time.sleep(0.25)

    build_dir = RUNTIME_ROOT / f".build-{_runtime_tag()}-{uuid.uuid4().hex}"
    try:
        if _runtime_is_valid(runtime_dir, digest):
            return _runtime_python(runtime_dir)

        venv.EnvBuilder(with_pip=True, clear=True).create(build_dir)
        python = _runtime_python(build_dir)
        _run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-deps", str(PYSOCKS_WHEEL),
        ])
        _run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "-r", str(REQUIREMENTS),
        ])

        marker = {
            "lock_digest": digest,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        }
        (build_dir / "runtime.json").write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not _runtime_is_valid(build_dir, digest):
            raise BootstrapError("The isolated runtime failed its import/version verification.")

        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        build_dir.replace(runtime_dir)
        return _runtime_python(runtime_dir)
    except Exception:
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        raise
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        print(ensure_runtime())
    except BootstrapError as exc:
        print(f"bootstrap error: {exc}", file=sys.stderr)
        raise SystemExit(2)
