from __future__ import annotations

from campus_food_sim.config import load_config
from campus_food_sim.simulation import (
    ArrivalSegment,
    BusyTimeTracker,
    OrderPlan,
    generate_arrival_times,
    prepare_order_plans,
    run_replication,
)


def _config() -> dict:
    return load_config("configs/portfolio.json")


def test_config_contains_frozen_assumptions() -> None:
    config = _config()
    assert config["simulation"]["end_minute"] == 720
    assert config["simulation"]["data_start_minute"] == 120
    assert config["orders"]["simple_probability"] == 0.65
    assert config["resources"] == {"kitchen_capacity": 4, "pickup_capacity": 1}
    assert [scenario["name"] for scenario in config["scenarios"]] == [
        "Baseline",
        "Scenario 2",
        "Scenario 3",
    ]


def test_arrival_generation_restarts_at_each_rate_boundary() -> None:
    class SequenceRng:
        def __init__(self) -> None:
            self.values = iter((1.0, 0.2, 1.0))
            self.scales: list[float] = []

        def exponential(self, scale: float) -> float:
            self.scales.append(scale)
            return next(self.values)

    rng = SequenceRng()
    arrivals = generate_arrival_times(
        rng,
        [
            ArrivalSegment(0.0, 1.0, 60.0),
            ArrivalSegment(1.0, 2.0, 120.0),
        ],
    )
    assert arrivals == [1.2]
    assert rng.scales == [1.0, 0.5, 0.5]


def test_order_plans_are_common_random_numbers() -> None:
    config = _config()
    assert prepare_order_plans(config, 77) == prepare_order_plans(config, 77)
    assert prepare_order_plans(config, 77) != prepare_order_plans(config, 78)


def test_busy_time_tracker_closes_active_work() -> None:
    tracker = BusyTimeTracker()
    tracker.start(1, 2.0)
    tracker.finish(1, 5.0)
    tracker.start(2, 4.0)
    tracker.close(7.0)
    assert tracker.overlap(0.0, 10.0) == 6.0
    assert tracker.overlap(3.0, 4.5) == 2.0


def test_close_censors_unfinished_orders_and_counts_them() -> None:
    config = _config()
    config["simulation"] = {
        "start_minute": 0,
        "end_minute": 10,
        "data_start_minute": 0,
        "data_end_minute": 10,
        "replications": 1,
    }
    plan = OrderPlan(0, 0.0, "simple", 20.0, 0.5, 0.0, 0.5, 0.2)
    output = run_replication(config, config["scenarios"][0], [plan])
    assert output.metrics["orders_generated"] == 1
    assert output.metrics["completed_orders"] == 0
    assert output.metrics["censored_orders"] == 1
    assert output.metrics["kitchen_utilization"] == 10.0 / 40.0


def test_scenarios_change_only_their_documented_levers() -> None:
    config = _config()
    config["simulation"] = {
        "start_minute": 0,
        "end_minute": 10,
        "data_start_minute": 0,
        "data_end_minute": 10,
        "replications": 1,
    }
    plan = OrderPlan(0, 0.0, "simple", 0.1, 1.0, 0.0, 1.0, 0.2)
    baseline = run_replication(config, config["scenarios"][0], [plan])
    scenario_two = run_replication(config, config["scenarios"][1], [plan])
    scenario_three = run_replication(config, config["scenarios"][2], [plan])
    assert baseline.metrics["completed_orders"] == scenario_two.metrics["completed_orders"]
    assert scenario_two.metrics["avg_turnaround_min"] < baseline.metrics["avg_turnaround_min"]
    assert scenario_three.metrics["avg_turnaround_min"] < baseline.metrics["avg_turnaround_min"]
    assert config["resources"]["pickup_capacity"] == 1
