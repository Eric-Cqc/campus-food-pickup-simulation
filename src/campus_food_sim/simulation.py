"""Assumption-driven SimPy model for campus food ordering and pickup.

Simulation time is measured in minutes from opening at 08:00.  Random order
plans are generated once per replication and reused by every scenario, which
implements common random numbers for paired comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import simpy


@dataclass(frozen=True)
class ArrivalSegment:
    """A half-open piecewise-Poisson arrival-rate segment."""

    start_minute: float
    end_minute: float
    rate_per_hour: float

    @property
    def rate_per_minute(self) -> float:
        return self.rate_per_hour / 60.0


@dataclass(frozen=True)
class OrderPlan:
    """Random inputs for one order, shared across all scenarios."""

    order_id: int
    order_time: float
    order_type: str
    prep_time_min: float
    transfer_time_min: float
    customer_delay_min: float
    pickup_time_min: float
    fast_pickup_time_min: float


@dataclass
class OrderRecord:
    """Event timestamps for one order in one scenario."""

    plan: OrderPlan
    t_start_prep: float | None = None
    t_ready: float | None = None
    t_arrival: float | None = None
    t_begin_pickup: float | None = None
    t_pickup: float | None = None


@dataclass(frozen=True)
class ReplicationOutput:
    """Metrics and pooled plot samples from one scenario replication."""

    metrics: dict[str, float | int]
    ready_times: tuple[float, ...]
    waiting_times: tuple[float, ...]


class BusyTimeTracker:
    """Track actual kitchen occupancy intervals, including close censoring."""

    def __init__(self) -> None:
        self._active: dict[int, float] = {}
        self.intervals: list[tuple[float, float]] = []

    def start(self, key: int, time: float) -> None:
        if key in self._active:
            raise ValueError(f"busy interval already active for {key}")
        self._active[key] = time

    def finish(self, key: int, time: float) -> None:
        start = self._active.pop(key, None)
        if start is None:
            raise ValueError(f"no active busy interval for {key}")
        if time < start:
            raise ValueError("busy interval ended before it started")
        self.intervals.append((start, time))

    def close(self, time: float) -> None:
        """Right-censor any active kitchen work at the simulation close."""

        for key in list(self._active):
            self.finish(key, time)

    def overlap(self, start: float, end: float) -> float:
        return sum(
            max(0.0, min(interval_end, end) - max(interval_start, start))
            for interval_start, interval_end in self.intervals
        )


class QueueAreaTracker:
    """Integrate a piecewise-constant kitchen queue length exactly."""

    def __init__(self, start: float) -> None:
        self._last_time = start
        self._last_value = 0
        self.intervals: list[tuple[float, float, int]] = []

    def update(self, time: float, value: int) -> None:
        if time < self._last_time:
            raise ValueError("queue time moved backwards")
        if time > self._last_time:
            self.intervals.append((self._last_time, time, self._last_value))
        self._last_time = time
        self._last_value = value

    def area(self, start: float, end: float) -> float:
        return sum(
            max(0.0, min(interval_end, end) - max(interval_start, start)) * value
            for interval_start, interval_end, value in self.intervals
        )


def generate_arrival_times(
    rng: Any, segments: Iterable[ArrivalSegment]
) -> list[float]:
    """Generate a non-homogeneous Poisson process without crossing boundaries.

    Each segment starts a fresh exponential draw.  This is exact for the
    piecewise-constant process and prevents an interarrival drawn under one
    rate from being carried into the next rate segment.
    """

    arrival_times: list[float] = []
    previous_end: float | None = None
    for segment in segments:
        if segment.end_minute <= segment.start_minute:
            raise ValueError("arrival segment must have positive duration")
        if previous_end is not None and segment.start_minute < previous_end:
            raise ValueError("arrival segments must not overlap")
        if segment.rate_per_hour < 0.0:
            raise ValueError("arrival rate must be nonnegative")
        previous_end = segment.end_minute
        if segment.rate_per_hour == 0.0:
            continue

        current = segment.start_minute
        while True:
            current += float(rng.exponential(1.0 / segment.rate_per_minute))
            if current >= segment.end_minute:
                break
            arrival_times.append(current)

    return arrival_times


def _sample_truncated_lognormal(
    rng: np.random.Generator, distribution: dict[str, Any]
) -> float:
    upper = float(distribution["truncation_min"])
    while True:
        value = float(
            rng.lognormal(
                mean=float(distribution["mu"]),
                sigma=float(distribution["sigma"]),
            )
        )
        if value <= upper:
            return value


def _sample_triangular_minutes(
    rng: np.random.Generator, distribution: dict[str, Any]
) -> float:
    unit = distribution.get("unit", "minutes")
    value = float(
        rng.triangular(
            float(distribution["min"]),
            float(distribution["mode"]),
            float(distribution["max"]),
        )
    )
    if unit == "seconds":
        return value / 60.0
    if unit != "minutes":
        raise ValueError(f"unsupported triangular unit: {unit}")
    return value


def arrival_segments(config: dict[str, Any]) -> list[ArrivalSegment]:
    return [
        ArrivalSegment(
            start_minute=float(segment["start_minute"]),
            end_minute=float(segment["end_minute"]),
            rate_per_hour=float(segment["rate_per_hour"]),
        )
        for segment in config["arrivals"]["segments"]
    ]


def prepare_order_plans(config: dict[str, Any], seed: int) -> list[OrderPlan]:
    """Create one scenario-independent random input stream for a replication."""

    end_minute = float(config["simulation"]["end_minute"])
    seed_sequence = np.random.SeedSequence(int(seed))
    arrival_sequence, attribute_sequence = seed_sequence.spawn(2)
    arrival_rng = np.random.default_rng(arrival_sequence)
    attribute_rng = np.random.default_rng(attribute_sequence)

    arrival_times = [
        time
        for time in generate_arrival_times(arrival_rng, arrival_segments(config))
        if time < end_minute
    ]
    order_cfg = config["orders"]
    prep_cfg = config["preparation"]
    transfer_cfg = config["transfer"]
    delay_cfg = config["customer_delay"]
    pickup_cfg = config["pickup"]

    plans: list[OrderPlan] = []
    for order_id, order_time in enumerate(arrival_times):
        order_type = (
            "simple"
            if attribute_rng.random() < float(order_cfg["simple_probability"])
            else "custom"
        )
        prep_time = _sample_truncated_lognormal(
            attribute_rng, prep_cfg[order_type]
        )
        transfer_time = _sample_triangular_minutes(
            attribute_rng, transfer_cfg["distribution"]
        )
        if attribute_rng.random() < float(delay_cfg["immediate_probability"]):
            delay_time = _sample_triangular_minutes(
                attribute_rng, delay_cfg["immediate"]
            )
        else:
            delay_time = _sample_triangular_minutes(
                attribute_rng, delay_cfg["delayed"]
            )
        pickup_time = _sample_triangular_minutes(
            attribute_rng, pickup_cfg["standard"]
        )
        fast_pickup_time = _sample_triangular_minutes(
            attribute_rng, pickup_cfg["fast_simple"]
        )
        plans.append(
            OrderPlan(
                order_id=order_id,
                order_time=order_time,
                order_type=order_type,
                prep_time_min=prep_time,
                transfer_time_min=transfer_time,
                customer_delay_min=delay_time,
                pickup_time_min=pickup_time,
                fast_pickup_time_min=fast_pickup_time,
            )
        )
    return plans


def _customer_journey(
    env: simpy.Environment,
    record: OrderRecord,
    kitchen: simpy.Resource,
    pickup: simpy.Resource,
    scenario: dict[str, Any],
    queue_tracker: QueueAreaTracker,
    busy_tracker: BusyTimeTracker,
) -> Any:
    kitchen_request = kitchen.request()
    queue_tracker.update(env.now, len(kitchen.queue))
    yield kitchen_request
    queue_tracker.update(env.now, len(kitchen.queue))

    record.t_start_prep = env.now
    busy_tracker.start(record.plan.order_id, env.now)
    yield env.timeout(record.plan.prep_time_min)
    busy_tracker.finish(record.plan.order_id, env.now)
    kitchen.release(kitchen_request)
    queue_tracker.update(env.now, len(kitchen.queue))

    transfer_scale = float(scenario["transfer_scale"])
    yield env.timeout(record.plan.transfer_time_min * transfer_scale)
    record.t_ready = env.now
    record.t_arrival = env.now + record.plan.customer_delay_min
    yield env.timeout(record.plan.customer_delay_min)

    pickup_request = pickup.request()
    yield pickup_request
    record.t_begin_pickup = env.now
    if bool(scenario["fast_simple_pickup"]) and record.plan.order_type == "simple":
        pickup_time = record.plan.fast_pickup_time_min
    else:
        pickup_time = record.plan.pickup_time_min
    yield env.timeout(pickup_time)
    record.t_pickup = env.now
    pickup.release(pickup_request)


def _order_generator(
    env: simpy.Environment,
    records: list[OrderRecord],
    kitchen: simpy.Resource,
    pickup: simpy.Resource,
    scenario: dict[str, Any],
    queue_tracker: QueueAreaTracker,
    busy_tracker: BusyTimeTracker,
) -> Any:
    for record in records:
        delay = record.plan.order_time - env.now
        if delay < 0.0:
            raise ValueError("order plans must be sorted by order time")
        yield env.timeout(delay)
        env.process(
            _customer_journey(
                env,
                record,
                kitchen,
                pickup,
                scenario,
                queue_tracker,
                busy_tracker,
            )
        )


def _mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


def _valid_completed_records(
    records: list[OrderRecord], config: dict[str, Any]
) -> list[OrderRecord]:
    simulation_cfg = config["simulation"]
    data_start = float(simulation_cfg["data_start_minute"])
    data_end = float(simulation_cfg["data_end_minute"])
    return [
        record
        for record in records
        if record.t_pickup is not None
        and data_start <= record.t_pickup <= data_end
    ]


def completed_waiting_times(
    records: list[OrderRecord], config: dict[str, Any]
) -> list[float]:
    """Return pickup-queue waits for completed orders in the data window."""

    return [
        max(0.0, float(record.t_begin_pickup) - float(record.t_arrival))
        for record in _valid_completed_records(records, config)
    ]


def compute_replication_metrics(
    records: list[OrderRecord],
    busy_tracker: BusyTimeTracker,
    queue_tracker: QueueAreaTracker,
    config: dict[str, Any],
) -> dict[str, float | int]:
    """Compute one replication's metrics with explicit close censoring."""

    simulation_cfg = config["simulation"]
    data_start = float(simulation_cfg["data_start_minute"])
    data_end = float(simulation_cfg["data_end_minute"])
    threshold = float(config["freshness_threshold_min"])
    capacity = int(config["resources"]["kitchen_capacity"])
    valid = _valid_completed_records(records, config)
    waiting = completed_waiting_times(records, config)
    turnaround = [
        float(record.t_pickup) - record.plan.order_time for record in valid
    ]
    # Preserve the coursework freshness semantics: this is the delay from
    # ready time to customer arrival, not the full time-to-pickup.
    ready_to_arrival_delays = [
        max(0.0, float(record.t_arrival) - float(record.t_ready))
        for record in valid
    ]
    completed_orders = sum(record.t_pickup is not None for record in records)
    generated_orders = len(records)
    window_length = data_end - data_start

    return {
        "orders_generated": generated_orders,
        "completed_orders": completed_orders,
        "censored_orders": generated_orders - completed_orders,
        "completed_in_window": len(valid),
        "avg_waiting_min": _mean(waiting),
        "avg_turnaround_min": _mean(turnaround),
        "w90_waiting_min": (
            float(np.percentile(waiting, 90)) if waiting else float("nan")
        ),
        "avg_ready_to_arrival_delay_min": _mean(ready_to_arrival_delays),
        "p_stale_pct": (
            100.0
            * sum(value > threshold for value in ready_to_arrival_delays)
            / len(ready_to_arrival_delays)
            if ready_to_arrival_delays
            else float("nan")
        ),
        "kitchen_utilization": busy_tracker.overlap(data_start, data_end)
        / (capacity * window_length),
        "avg_kitchen_queue": queue_tracker.area(data_start, data_end)
        / window_length,
    }


def run_replication(
    config: dict[str, Any], scenario: dict[str, Any], plans: list[OrderPlan]
) -> ReplicationOutput:
    """Run one scenario using a pre-generated common-random-number plan."""

    simulation_cfg = config["simulation"]
    start = float(simulation_cfg["start_minute"])
    end = float(simulation_cfg["end_minute"])
    if start != 0.0:
        raise ValueError("the model expects start_minute to be zero")

    env = simpy.Environment()
    kitchen = simpy.Resource(
        env, capacity=int(config["resources"]["kitchen_capacity"])
    )
    pickup = simpy.Resource(
        env, capacity=int(config["resources"]["pickup_capacity"])
    )
    records = [OrderRecord(plan=plan) for plan in plans]
    queue_tracker = QueueAreaTracker(start)
    busy_tracker = BusyTimeTracker()
    env.process(
        _order_generator(
            env,
            records,
            kitchen,
            pickup,
            scenario,
            queue_tracker,
            busy_tracker,
        )
    )
    env.run(until=end)

    # Events after close are deliberately not executed.  Active prep is
    # right-censored and unfinished orders remain counted as censored.
    queue_tracker.update(end, len(kitchen.queue))
    busy_tracker.close(end)
    metrics = compute_replication_metrics(
        records, busy_tracker, queue_tracker, config
    )
    ready_times = tuple(
        float(record.t_ready)
        for record in records
        if record.t_ready is not None
    )
    waiting_times = tuple(completed_waiting_times(records, config))
    return ReplicationOutput(metrics, ready_times, waiting_times)


def simulate_replication(
    config: dict[str, Any], scenario: dict[str, Any], plans: list[OrderPlan]
) -> tuple[dict[str, float | int], list[float]]:
    """Compatibility wrapper returning metrics and ready timestamps."""

    output = run_replication(config, scenario, plans)
    return output.metrics, list(output.ready_times)
