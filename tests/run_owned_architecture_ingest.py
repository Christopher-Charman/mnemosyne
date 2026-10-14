#!/usr/bin/env python3
"""Run synthetic ingestion regressions with isolated data and an explicit Git preflight.

Invoke with the intended Python interpreter, e.g. `python3.12 tests/run_owned_architecture_ingest.py`.
No production memory bank is opened by this launcher.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ENVIRONMENT_ERROR = 2


def resolve_git() -> Path:
    """Find an executable Git; an explicit override must be an absolute path."""
    override = os.environ.get("MNEMOSYNE_TEST_GIT")
    if override:
        candidate = Path(override)
        if not candidate.is_absolute():
            raise RuntimeError("MNEMOSYNE_TEST_GIT must be an absolute executable path")
    else:
        found = shutil.which("git")
        candidate = Path(found) if found else Path(sys.executable).parent / "git"
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError(
            "git is unavailable to the test environment; set MNEMOSYNE_TEST_GIT "
            "to a trusted absolute Git executable, or use Python from a toolchain "
            "with a sibling Git binary"
        )
    try:
        result = subprocess.run(
            [str(candidate), "--version"], capture_output=True, text=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("git executable preflight failed") from exc
    if result.returncode != 0:
        raise RuntimeError("git --version failed in the test environment")
    return candidate


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    test_file = root / "tests" / "test_owned_architecture_ingest.py"
    if not test_file.is_file():
        print("TEST_ENVIRONMENT_ERROR: ingestion regression file is missing", file=sys.stderr)
        return ENVIRONMENT_ERROR
    try:
        git_binary = resolve_git()
    except RuntimeError as exc:
        print(f"TEST_ENVIRONMENT_ERROR: {exc}", file=sys.stderr)
        return ENVIRONMENT_ERROR

    with tempfile.TemporaryDirectory(prefix="mnemosyne-ingest-tests-") as td:
        env = os.environ.copy()
        env.update({
            "PATH": str(git_binary.parent) + os.pathsep + env.get("PATH", ""),
            "PYTHONPATH": str(root) + os.pathsep + env.get("PYTHONPATH", ""),
            "MNEMOSYNE_NO_EMBEDDINGS": "1",
            "MNEMOSYNE_EMBEDDINGS_VIA_API": "0",
            "MNEMOSYNE_DATA_DIR": str(Path(td) / "data"),
            "HERMES_HOME": str(Path(td) / "hermes"),
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        print(f"TEST_ENVIRONMENT_OK: git={git_binary}, isolated_data=true", flush=True)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"),
                 "-p", "test_owned_architecture_ingest.py", "-v"],
                cwd=root, env=env, check=False,
            )
        except OSError as exc:
            print(f"TEST_ENVIRONMENT_ERROR: Python test launch failed: {exc}", file=sys.stderr)
            return ENVIRONMENT_ERROR
        return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
