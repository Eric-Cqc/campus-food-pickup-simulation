"""Configuration loading and validation for the public simulation package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXPECTED_SCENARIOS = ("Baseline", "Scenario 2", "Scenario 3")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _probability(value: Any, name: str) -> None:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between zero and one")


def _triangular_distribution(value: Any, name: str) -> None:
    distribution = _mapping(value, name)
    lower = float(distribution["min"])
    mode = float(distribution["mode"])
    upper = float(distribution["max"])
    if not lower <= mode <= upper:
        raise ValueError(f"{name} must satisfy min <= mode <= max")
    if distribution.get("unit", "minutes") not in {"minutes", "seconds"}:
        raise ValueError(f"{name}.unit must be minutes or seconds")


def validate_config(config: dict[str, Any]) -> None:
    """Validate the assumptions needed by the simulation and report writer."""

    required = {
        "simulation",
        "random",
        "arrivals",
        "orders",
        "preparation",
        "transfer",
        "customer_delay",
        "pickup",
        "freshness_threshold_min",
        "resources",
        "scenarios",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"configuration is missing: {', '.join(missing)}")

    simulation = _mapping(config["simulation"], "simulation")
    start = float(simulation["start_minute"])
    end = float(simulation["end_minute"])
    data_start = float(simulation["data_start_minute"])
    data_end = float(simulation["data_end_minute"])
    if start != 0.0:
        raise ValueError("simulation.start_minute must be zero")
    if not start < data_start < data_end <= end:
        raise ValueError("simulation data window must be inside the run")
    if int(simulation["replications"]) < 1:
        raise ValueError("simulation.replications must be positive")

    random_config = _mapping(config["random"], "random")
    int(random_config["seed_base"])

    arrivals = _mapping(config["arrivals"], "arrivals")
    segments = arrivals.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("arrivals.segments must be a non-empty list")
    previous_end = start
    for index, raw_segment in enumerate(segments):
        segment = _mapping(raw_segment, f"arrivals.segments[{index}]")
        segment_start = float(segment["start_minute"])
        segment_end = float(segment["end_minute"])
        rate = float(segment["rate_per_hour"])
        if segment_start != previous_end:
            raise ValueError("arrival segments must be contiguous and ordered")
        if segment_end <= segment_start or rate < 0.0:
            raise ValueError("arrival segments must have positive duration and nonnegative rate")
        previous_end = segment_end
    if previous_end != end:
        raise ValueError("arrival segments must cover the simulation interval")

    orders = _mapping(config["orders"], "orders")
    _probability(orders["simple_probability"], "orders.simple_probability")

    preparation = _mapping(config["preparation"], "preparation")
    for order_type in ("simple", "custom"):
        distribution = _mapping(preparation[order_type], f"preparation.{order_type}")
        if float(distribution["sigma"]) <= 0.0:
            raise ValueError(f"preparation.{order_type}.sigma must be positive")
        if float(distribution["truncation_min"]) <= 0.0:
            raise ValueError(f"preparation.{order_type}.truncation_min must be positive")

    transfer = _mapping(config["transfer"], "transfer")
    _triangular_distribution(transfer["distribution"], "transfer.distribution")

    delay = _mapping(config["customer_delay"], "customer_delay")
    _probability(delay["immediate_probability"], "customer_delay.immediate_probability")
    _triangular_distribution(delay["immediate"], "customer_delay.immediate")
    _triangular_distribution(delay["delayed"], "customer_delay.delayed")

    pickup = _mapping(config["pickup"], "pickup")
    _triangular_distribution(pickup["standard"], "pickup.standard")
    _triangular_distribution(pickup["fast_simple"], "pickup.fast_simple")

    if float(config["freshness_threshold_min"]) < 0.0:
        raise ValueError("freshness_threshold_min must be nonnegative")

    resources = _mapping(config["resources"], "resources")
    if int(resources["kitchen_capacity"]) < 1:
        raise ValueError("resources.kitchen_capacity must be positive")
    if int(resources["pickup_capacity"]) != 1:
        raise ValueError("resources.pickup_capacity must remain one")

    scenarios = config["scenarios"]
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    scenario_names = tuple(_mapping(scenario, "scenario")["name"] for scenario in scenarios)
    if scenario_names != EXPECTED_SCENARIOS:
        raise ValueError(
            f"scenarios must be ordered as {EXPECTED_SCENARIOS}, got {scenario_names}"
        )
    for scenario in scenarios:
        scenario_config = _mapping(scenario, "scenario")
        if float(scenario_config["transfer_scale"]) <= 0.0:
            raise ValueError("scenario transfer_scale must be positive")
        if not isinstance(scenario_config["fast_simple_pickup"], bool):
            raise ValueError("scenario fast_simple_pickup must be boolean")

    baseline, scenario_two, scenario_three = scenarios
    if bool(baseline["fast_simple_pickup"]) or float(baseline["transfer_scale"]) != 1.0:
        raise ValueError("Baseline must use standard pickup and transfer")
    if not bool(scenario_two["fast_simple_pickup"]):
        raise ValueError("Scenario 2 must enable fast simple-order pickup")
    if float(scenario_two["transfer_scale"]) != 1.0:
        raise ValueError("Scenario 2 must retain the baseline transfer scale")
    if bool(scenario_three["fast_simple_pickup"]):
        raise ValueError("Scenario 3 must retain standard pickup")
    if abs(float(scenario_three["transfer_scale"]) - 0.6) > 1e-12:
        raise ValueError("Scenario 3 transfer scale must be 0.6")


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and validate a JSON configuration file."""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    validate_config(config)
    return config
