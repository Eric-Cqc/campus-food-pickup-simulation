from __future__ import annotations

import csv

from campus_food_sim.config import load_config
from campus_food_sim.reporting import run_experiment


def test_reporting_writes_replications_summary_pairs_and_two_plots(tmp_path) -> None:
    config = load_config("configs/portfolio.json")
    result = run_experiment(config, tmp_path, replications=2)
    assert len(result.replication_rows) == 6
    assert len(result.summary_rows) == 33
    assert len(result.paired_rows) == 22
    for filename in (
        "replications.csv",
        "summary.csv",
        "paired_differences.csv",
        "orders_ready_by_hour.png",
        "waiting_time_distribution.png",
    ):
        assert (tmp_path / filename).is_file()
        assert (tmp_path / filename).stat().st_size > 0

    with (tmp_path / "replications.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for replication in ("1", "2"):
        seeds = {
            row["seed"] for row in rows if row["replication"] == replication
        }
        assert len(seeds) == 1
