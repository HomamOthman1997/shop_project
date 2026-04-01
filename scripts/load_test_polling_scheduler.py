from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from dataclasses import dataclass, field


@dataclass
class Metrics:
    scheduler_runs: int = 0
    scheduler_failures: int = 0
    poller_ticks: int = 0
    poller_failures: int = 0
    scheduler_latency_ms: list[float] = field(default_factory=list)
    poller_latency_ms: list[float] = field(default_factory=list)


async def _simulate_scheduler_job(name: str, fail_rate: float) -> float:
    start = time.perf_counter()
    await asyncio.sleep(random.uniform(0.005, 0.045))
    if random.random() < fail_rate:
        raise RuntimeError(f"{name} simulated failure")
    return (time.perf_counter() - start) * 1000.0


async def _scheduler_loop(metrics: Metrics, duration_sec: int, fail_rate: float) -> None:
    end_at = time.perf_counter() + duration_sec
    jobs = ("recharge_recovery", "financial_anomaly", "proxy_validation", "lifecycle_cleanup")
    while time.perf_counter() < end_at:
        for name in jobs:
            try:
                latency = await _simulate_scheduler_job(name, fail_rate)
                metrics.scheduler_latency_ms.append(latency)
            except Exception:
                metrics.scheduler_failures += 1
            finally:
                metrics.scheduler_runs += 1
        await asyncio.sleep(0.02)


async def _poller_loop(metrics: Metrics, bots: int, duration_sec: int, fail_rate: float) -> None:
    end_at = time.perf_counter() + duration_sec
    while time.perf_counter() < end_at:
        for _ in range(max(1, bots)):
            try:
                latency = await _simulate_scheduler_job("poll_fetch_updates", fail_rate)
                metrics.poller_latency_ms.append(latency)
            except Exception:
                metrics.poller_failures += 1
            finally:
                metrics.poller_ticks += 1
        await asyncio.sleep(0.02)


def _pct(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * max(0.0, min(1.0, percentile)))
    return float(ordered[idx])


async def run_scenario(*, bots: int, duration_sec: int, fail_rate: float) -> dict:
    metrics = Metrics()
    await asyncio.gather(
        _scheduler_loop(metrics, duration_sec=duration_sec, fail_rate=fail_rate),
        _poller_loop(metrics, bots=bots, duration_sec=duration_sec, fail_rate=fail_rate),
    )
    return {
        "duration_sec": int(duration_sec),
        "bots": int(bots),
        "scheduler_runs": int(metrics.scheduler_runs),
        "scheduler_failures": int(metrics.scheduler_failures),
        "poller_ticks": int(metrics.poller_ticks),
        "poller_failures": int(metrics.poller_failures),
        "scheduler_avg_ms": round(statistics.mean(metrics.scheduler_latency_ms), 2) if metrics.scheduler_latency_ms else 0.0,
        "scheduler_p95_ms": round(_pct(metrics.scheduler_latency_ms, 0.95), 2),
        "poller_avg_ms": round(statistics.mean(metrics.poller_latency_ms), 2) if metrics.poller_latency_ms else 0.0,
        "poller_p95_ms": round(_pct(metrics.poller_latency_ms, 0.95), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic load test for polling loop + scheduler jobs.")
    parser.add_argument("--bots", type=int, default=25)
    parser.add_argument("--duration", type=int, default=20, help="Duration in seconds")
    parser.add_argument("--fail-rate", type=float, default=0.03, help="Simulated per-operation failure rate")
    args = parser.parse_args()
    report = asyncio.run(
        run_scenario(
            bots=max(1, int(args.bots)),
            duration_sec=max(5, int(args.duration)),
            fail_rate=max(0.0, min(0.9, float(args.fail_rate))),
        )
    )
    for k, v in report.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
