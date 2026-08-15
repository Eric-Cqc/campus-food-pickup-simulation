# Campus Food Pickup Simulation

An assumption-driven discrete-event simulation of a hypothetical campus food ordering and pickup system.

Results are simulation estimates under documented assumptions, not measurements of actual campus operations.

This small Python package reconstructs an assumption-driven SimPy DES from graduate operations coursework. It models orders arriving between 08:00 and 20:00, kitchen preparation, transfer to a pickup point, customer arrival, and one-capacity pickup service.

## Assumptions

Simulation time is measured in minutes from 08:00. The first 120 minutes are a warm-up/data exclusion period for performance metrics; the simulation still generates orders from opening. Orders that have not completed pickup by 20:00 are explicitly right-censored and are not treated as completed.

| Component | Assumption |
| --- | --- |
| Run and data window | 08:00–20:00; metrics use 120–720 minutes |
| Replications | 50, with a fixed seed per replication index |
| Arrivals | Piecewise Poisson: 5 orders/hour off-peak, 30 orders/hour 11:30–13:00, 25 orders/hour 17:00–18:30 |
| Order mix | 65% simple, 35% custom |
| Simple preparation | Truncated lognormal, μ=1.047, σ=0.324, upper bound 20 minutes |
| Custom preparation | Truncated lognormal, μ=2.003, σ=0.363, upper bound 30 minutes |
| Transfer | Triangular (0.5, 1.5, 3.0) minutes |
| Customer arrival | 30% triangular (0, 1, 3) minutes; otherwise triangular (3, 8, 20) minutes |
| Standard pickup | Triangular (10, 25, 60) seconds |
| Fast simple pickup | Triangular (5, 15, 30) seconds |
| Resources | Kitchen capacity 4; pickup capacity 1 |
| Freshness | Stale when ready-to-arrival delay exceeds 10 minutes (`t_arrival − t_ready`) |

The exact machine-readable assumptions are in [`configs/portfolio.json`](configs/portfolio.json).

The reported ready-to-arrival delay is the time from food being ready (`t_ready`) to the customer arriving (`t_arrival`); it is not time-to-pickup. Freshness/staleness is based on this delay exceeding 10 minutes.

## Scenarios

- **Baseline:** standard transfer and pickup service.
- **Scenario 2:** faster pickup for simple orders; pickup capacity stays at 1.
- **Scenario 3:** transfer-time proxy scaled by 0.6; this is not literal batching.

The same random order plan and seed are used for all scenarios within each replication. The paired-difference table reports Scenario 2 or Scenario 3 minus Baseline with a two-sided paired 95% t confidence interval.

## How to run

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"

MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl campus-food-sim run \
  --config configs/portfolio.json --replications 3 --output-dir /tmp/cfs-smoke

MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl campus-food-sim reproduce \
  --config configs/portfolio.json --replications 50 --output-dir results
```

The `run` and `reproduce` subcommands use the same deterministic pipeline; `reproduce` names the intended artifact-regeneration workflow. Each output directory contains replication-level metrics, a 50-replication summary with confidence intervals when run at the default size, a paired-difference table, and two headless PNG figures. The plots are pooled over replications and labelled as pooled. Figures regenerate with the environment's installed Matplotlib version, so verification checks their existence rather than byte identity.

In the result CSVs, `avg_ready_to_arrival_delay_min` is the mean ready-to-arrival delay, and `p_stale_pct` is the percentage of completed orders whose ready-to-arrival delay exceeds 10 minutes.

For local checks:

```bash
python -m pytest -q
python scripts/verify_results.py --expected results --actual /tmp/cfs-verify
python scripts/audit_public_tree.py
```

## Sample results

The following values are generated from the committed 50-replication artifacts in `results/`. Waiting time is the average pickup-queue wait among completed orders in the data window; paired differences are treatment minus Baseline.

| Scenario | Average wait (min) | Completed orders (mean) | Kitchen utilization (mean) |
| --- | ---: | ---: | ---: |
| Baseline | 0.072 (0.065–0.078) | 129.36 | 0.237 |
| Scenario 2 | 0.033 (0.030–0.037) | 129.40 | 0.237 |
| Scenario 3 | 0.071 (0.065–0.077) | 129.42 | 0.237 |

| Paired comparison | Wait difference (min) | Paired 95% CI (min) |
| --- | ---: | ---: |
| Scenario 2 − Baseline | −0.038 | [−0.043, −0.034] |
| Scenario 3 − Baseline | −0.001 | [−0.003, 0.002] |

Values are rounded to three decimals in this table; the CSV artifacts retain more precision.

The paired 95% confidence intervals for average pickup waiting time are recorded in [`results/paired_differences.csv`](results/paired_differences.csv), and all headline values remain traceable to [`results/summary.csv`](results/summary.csv).

## Differences from the original coursework

1. Arrival generation is boundary-correct: each piecewise-rate segment starts its own exponential interarrival stream, so an old-rate draw cannot cross a lunch or dinner boundary.
2. End-of-day censoring is explicit. Orders unfinished at 20:00 are counted as censored, and completed-order counts are reported separately.
3. Kitchen utilization comes from actual kitchen-resource busy intervals, including work crossing the data-window or close boundary, rather than a sum of preparation times for selected completed orders.
4. Common random numbers use the same seed for the same replication index across all scenarios. Scenario comparisons therefore include paired-difference 95% confidence intervals.
5. Plots are headless, saved under `results/`, and label pooled replication data.

## Limitations

This is a hypothetical, assumption-driven model with no operational calibration or field validation. It does not model order abandonment, staffing variation, travel-network detail, finite storage, or capacity changes beyond the two resources. Preparation and service distributions are independent draws. The close policy censors unfinished journeys instead of extending the clock, so late-day completion performance should be read with that limitation in mind.

## License

MIT; see [`LICENSE`](LICENSE).
