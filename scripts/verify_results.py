#!/usr/bin/env python3
"""Compare committed result artifacts with a fresh deterministic reproduction."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


RESULT_FILES = (
    "replications.csv",
    "summary.csv",
    "paired_differences.csv",
    "orders_ready_by_hour.png",
    "waiting_time_distribution.png",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seed_keys(path: Path) -> list[tuple[str, str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            (row["replication"], row["scenario"], row["seed"])
            for row in rows
        ]


def verify(expected: Path, actual: Path) -> None:
    for filename in RESULT_FILES:
        expected_file = expected / filename
        actual_file = actual / filename
        if not expected_file.is_file():
            raise AssertionError(f"missing expected artifact: {expected_file}")
        if not actual_file.is_file():
            raise AssertionError(f"missing reproduced artifact: {actual_file}")
        if _sha256(expected_file) != _sha256(actual_file):
            raise AssertionError(f"artifact differs: {filename}")

    expected_keys = _seed_keys(expected / "replications.csv")
    actual_keys = _seed_keys(actual / "replications.csv")
    if expected_keys != actual_keys:
        raise AssertionError("replication seed/scenario rows differ")
    seeds_by_replication: dict[str, set[str]] = {}
    for replication, _scenario, seed in actual_keys:
        seeds_by_replication.setdefault(replication, set()).add(seed)
    if any(len(seeds) != 1 for seeds in seeds_by_replication.values()):
        raise AssertionError("common random numbers are not shared by replication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.expected, args.actual)
    except (AssertionError, OSError, KeyError) as error:
        print(f"FAIL: {error}")
        return 1
    print("OK: committed results match fresh reproduction and share replication seeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
