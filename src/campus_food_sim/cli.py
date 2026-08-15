"""Command-line interface for the campus food pickup simulation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .config import load_config
from .reporting import ExperimentResult, run_experiment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campus-food-sim",
        description="Run the assumption-driven campus food pickup simulation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "reproduce"):
        command_parser = subparsers.add_parser(
            command,
            help=(
                "run the experiment" if command == "run" else "regenerate deterministic artifacts"
            ),
        )
        command_parser.add_argument("--config", required=True, type=Path)
        command_parser.add_argument("--replications", type=int)
        command_parser.add_argument("--output-dir", type=Path, default=Path("results"))
    return parser


def _headline(result: ExperimentResult) -> list[str]:
    lines: list[str] = []
    for scenario in ("Baseline", "Scenario 2", "Scenario 3"):
        row = next(
            item
            for item in result.summary_rows
            if item["scenario"] == scenario and item["metric"] == "avg_waiting_min"
        )
        lines.append(
            f"{scenario}: average pickup wait {row['mean']:.3f} min "
            f"(95% CI {row['ci95_low']:.3f}, {row['ci95_high']:.3f})"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config: dict[str, Any] = load_config(args.config)
    result = run_experiment(
        config,
        output_dir=args.output_dir,
        replications=args.replications,
    )
    print(f"Wrote deterministic artifacts to {args.output_dir}")
    for line in _headline(result):
        print(line)
    if args.command == "reproduce":
        print("Reproduction uses the same seed for each replication index across scenarios.")
    return 0
