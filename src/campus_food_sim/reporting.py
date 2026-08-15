"""Replication, summary, paired-comparison, and plot output helpers."""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

os.environ["MPLBACKEND"] = "Agg"
os.environ["MPLCONFIGDIR"] = "/tmp/mpl"
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

from .config import EXPECTED_SCENARIOS, validate_config
from .simulation import prepare_order_plans, run_replication


METRIC_SPECS = (
    ("orders_generated", "Orders generated", "orders"),
    ("completed_orders", "Completed orders", "orders"),
    ("censored_orders", "Censored orders", "orders"),
    ("completed_in_window", "Completed orders in data window", "orders"),
    ("avg_waiting_min", "Average pickup waiting time", "minutes"),
    ("avg_turnaround_min", "Average order turnaround", "minutes"),
    ("w90_waiting_min", "90th percentile pickup waiting time", "minutes"),
    ("avg_dwell_min", "Average ready-to-pickup dwell", "minutes"),
    ("p_stale_pct", "Stale completed orders", "percent"),
    ("kitchen_utilization", "Kitchen utilization", "proportion"),
    ("avg_kitchen_queue", "Average kitchen queue", "orders"),
)
METRIC_NAMES = tuple(spec[0] for spec in METRIC_SPECS)

REPLICATION_FIELDS = (
    "replication",
    "seed",
    "scenario",
    *METRIC_NAMES,
)
SUMMARY_FIELDS = (
    "scenario",
    "metric",
    "unit",
    "replications",
    "n",
    "mean",
    "std",
    "ci95_low",
    "ci95_high",
)
PAIRED_FIELDS = (
    "scenario",
    "metric",
    "unit",
    "replications",
    "n",
    "baseline_mean",
    "scenario_mean",
    "difference_mean",
    "ci95_low",
    "ci95_high",
)


@dataclass(frozen=True)
class ExperimentResult:
    """In-memory representation of the files written by one experiment."""

    replication_rows: tuple[dict[str, Any], ...]
    summary_rows: tuple[dict[str, Any], ...]
    paired_rows: tuple[dict[str, Any], ...]


def seed_for_replication(config: dict[str, Any], replication: int) -> int:
    """Return the shared seed for a one-based replication index."""

    if replication < 1:
        raise ValueError("replication index must be one-based")
    return int(config["random"]["seed_base"]) + replication - 1


def _finite_values(values: Iterable[Any]) -> list[float]:
    return [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]


def _statistics(values: Iterable[Any]) -> tuple[int, float, float, float, float]:
    finite = _finite_values(values)
    n = len(finite)
    if n == 0:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    mean = float(np.mean(finite))
    if n == 1:
        return 1, mean, 0.0, mean, mean
    std = float(np.std(finite, ddof=1))
    margin = float(stats.t.ppf(0.975, df=n - 1) * std / math.sqrt(n))
    return n, mean, std, mean - margin, mean + margin


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "nan"
        return f"{value:.12g}"
    return str(value)


def _write_csv(path: Path, fields: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _summary_rows(
    replication_rows: list[dict[str, Any]], replications: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in EXPECTED_SCENARIOS:
        scenario_rows = [
            row for row in replication_rows if row["scenario"] == scenario
        ]
        for metric, _label, unit in METRIC_SPECS:
            n, mean, std, ci_low, ci_high = _statistics(
                row[metric] for row in scenario_rows
            )
            rows.append(
                {
                    "scenario": scenario,
                    "metric": metric,
                    "unit": unit,
                    "replications": replications,
                    "n": n,
                    "mean": mean,
                    "std": std,
                    "ci95_low": ci_low,
                    "ci95_high": ci_high,
                }
            )
    return rows


def _paired_rows(
    replication_rows: list[dict[str, Any]], replications: int
) -> list[dict[str, Any]]:
    by_replication = {
        (int(row["replication"]), row["scenario"]): row
        for row in replication_rows
    }
    rows: list[dict[str, Any]] = []
    for scenario in EXPECTED_SCENARIOS[1:]:
        for metric, _label, unit in METRIC_SPECS:
            baseline_values: list[float] = []
            scenario_values: list[float] = []
            differences: list[float] = []
            for replication in range(1, replications + 1):
                baseline = float(by_replication[(replication, "Baseline")][metric])
                treatment = float(by_replication[(replication, scenario)][metric])
                if math.isfinite(baseline) and math.isfinite(treatment):
                    baseline_values.append(baseline)
                    scenario_values.append(treatment)
                    differences.append(treatment - baseline)
            n, difference_mean, _std, ci_low, ci_high = _statistics(differences)
            rows.append(
                {
                    "scenario": scenario,
                    "metric": metric,
                    "unit": unit,
                    "replications": replications,
                    "n": n,
                    "baseline_mean": (
                        float(np.mean(baseline_values)) if baseline_values else float("nan")
                    ),
                    "scenario_mean": (
                        float(np.mean(scenario_values)) if scenario_values else float("nan")
                    ),
                    "difference_mean": difference_mean,
                    "ci95_low": ci_low,
                    "ci95_high": ci_high,
                }
            )
    return rows


def _plot_ready_times(
    output_dir: Path,
    pooled_ready_times: dict[str, list[float]],
    replications: int,
    end_minute: float,
) -> None:
    bins = np.arange(0.0, end_minute + 60.0, 60.0)
    figure, axis = plt.subplots(figsize=(9.0, 5.5))
    colors = {"Baseline": "#5f6368", "Scenario 2": "#6a0dad", "Scenario 3": "#2e8b57"}
    for scenario in EXPECTED_SCENARIOS:
        counts, _ = np.histogram(pooled_ready_times[scenario], bins=bins)
        axis.step(
            bins[1:],
            np.cumsum(counts),
            where="mid",
            linewidth=2.0,
            color=colors[scenario],
            label=scenario,
        )
    axis.set_title(f"Pooled ready orders by hour ({replications} replications)")
    axis.set_xlabel("End of clock hour")
    axis.set_ylabel("Cumulative ready orders (pooled)")
    axis.set_xticks(bins[1:])
    axis.set_xticklabels(
        [f"{8 + int(hour // 60):02d}:00" for hour in bins[1:]], rotation=45
    )
    axis.grid(alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_dir / "orders_ready_by_hour.png", dpi=180)
    plt.close(figure)


def _plot_waiting_times(
    output_dir: Path,
    pooled_waiting_times: dict[str, list[float]],
    replications: int,
) -> None:
    figure, axis = plt.subplots(figsize=(8.5, 5.5))
    data = [pooled_waiting_times[scenario] or [0.0] for scenario in EXPECTED_SCENARIOS]
    axis.boxplot(
        data,
        showmeans=True,
        meanline=True,
        patch_artist=True,
        boxprops={"facecolor": "#dfe6e9"},
        medianprops={"color": "#2d3436"},
    )
    axis.set_xticks(range(1, len(EXPECTED_SCENARIOS) + 1))
    axis.set_xticklabels(list(EXPECTED_SCENARIOS))
    axis.set_title(f"Pooled pickup waiting-time distribution ({replications} replications)")
    axis.set_ylabel("Waiting time (minutes)")
    axis.set_xlabel("Scenario")
    axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(output_dir / "waiting_time_distribution.png", dpi=180)
    plt.close(figure)


def run_experiment(
    config: dict[str, Any], output_dir: str | Path, replications: int | None = None
) -> ExperimentResult:
    """Run all scenarios and write deterministic CSV and PNG artifacts."""

    validate_config(config)
    total_replications = int(
        config["simulation"]["replications"] if replications is None else replications
    )
    if total_replications < 1:
        raise ValueError("replications must be positive")

    result_dir = Path(output_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    scenarios = {scenario["name"]: scenario for scenario in config["scenarios"]}
    replication_rows: list[dict[str, Any]] = []
    pooled_ready_times = {scenario: [] for scenario in EXPECTED_SCENARIOS}
    pooled_waiting_times = {scenario: [] for scenario in EXPECTED_SCENARIOS}

    for replication in range(1, total_replications + 1):
        seed = seed_for_replication(config, replication)
        plans = prepare_order_plans(config, seed)
        for scenario_name in EXPECTED_SCENARIOS:
            output = run_replication(config, scenarios[scenario_name], plans)
            row: dict[str, Any] = {
                "replication": replication,
                "seed": seed,
                "scenario": scenario_name,
            }
            row.update(output.metrics)
            replication_rows.append(row)
            pooled_ready_times[scenario_name].extend(output.ready_times)
            pooled_waiting_times[scenario_name].extend(output.waiting_times)

    summary_rows = _summary_rows(replication_rows, total_replications)
    paired_rows = _paired_rows(replication_rows, total_replications)
    _write_csv(result_dir / "replications.csv", REPLICATION_FIELDS, replication_rows)
    _write_csv(result_dir / "summary.csv", SUMMARY_FIELDS, summary_rows)
    _write_csv(result_dir / "paired_differences.csv", PAIRED_FIELDS, paired_rows)
    _plot_ready_times(
        result_dir,
        pooled_ready_times,
        total_replications,
        float(config["simulation"]["end_minute"]),
    )
    _plot_waiting_times(result_dir, pooled_waiting_times, total_replications)
    return ExperimentResult(
        tuple(replication_rows), tuple(summary_rows), tuple(paired_rows)
    )
