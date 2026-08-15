#!/usr/bin/env python3
"""Reject private source paths, report files, and CJK filenames in the tree."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
}
PRIVATE_PATH_MARKER = bytes((47,)) + b"Users" + bytes((47,))


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def audit(root: Path) -> list[str]:
    violations: list[str] = []
    for directory, directory_names, filenames in os.walk(root):
        directory_names[:] = sorted(
            name for name in directory_names if name not in EXCLUDED_DIRECTORIES
        )
        directory_path = Path(directory)
        for filename in sorted(filenames):
            path = directory_path / filename
            relative = path.relative_to(root)
            if _contains_cjk(str(relative)):
                violations.append(f"CJK filename: {relative}")
            if path.suffix.lower() in {".docx", ".pdf"}:
                violations.append(f"report file: {relative}")
            try:
                content = path.read_bytes()
            except OSError as error:
                violations.append(f"unreadable file {relative}: {error}")
                continue
            if PRIVATE_PATH_MARKER in content:
                violations.append(f"private absolute user path: {relative}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    violations = audit(args.root.resolve())
    if violations:
        for violation in violations:
            print(f"FAIL: {violation}")
        return 1
    print(f"OK: public tree audit passed for {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
