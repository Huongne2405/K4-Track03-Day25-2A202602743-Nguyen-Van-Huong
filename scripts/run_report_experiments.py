"""Reproduce report ablations without changing the submitted client or config.

    python scripts/run_report_experiments.py --seed 25
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import argparse
import copy
import json
from dataclasses import asdict

from gameday_lab.client import ResilientClient
from gameday_lab.factory import build_client
from gameday_lab.sim.config import LabConfig, load_config
from gameday_lab.sim.engine import evaluate_checks, run_scenario


class UnfilteredExperimentClient(ResilientClient):
    """Deliberately unsafe capability ablation; used only by this experiment script."""

    def ladder(self, task: str) -> list[str]:
        return list(self.order)


def measure(cfg: LabConfig, scenarios: tuple[str, ...], seed: int, unfiltered: bool = False) -> dict:
    runs = {}
    for scenario in scenarios:
        client = (
            UnfilteredExperimentClient(cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=1)
            if unfiltered else build_client("resilient", cfg)
        )
        metrics = run_scenario(cfg, scenario, client, seed).metrics()
        checks = evaluate_checks(metrics, cfg.scenarios[scenario].checks)
        runs[scenario] = {
            **metrics, "checks": checks, "pass": all(checks.values()),
            "breaker_transitions": {name: [asdict(t) for t in breaker.transitions]
                                    for name, breaker in client.breakers.items()},
        }
        print(scenario, {key: metrics[key] for key in (
            "availability", "latency_p95_s", "amplification", "retry_ratio", "recovery_s",
            "give_up_reasons", "incompatible_routes",
        )})
    return {"seed": seed, "client_settings": cfg.client, "unfiltered_tools": unfiltered, "runs": runs}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=25)
    parser.add_argument("--config", default="configs/gameday.yaml")
    parser.add_argument("--out", default="reports/report_experiments.json")
    args = parser.parse_args()
    cfg = load_config(args.config, "configs/scenarios.yaml")
    results = {}
    budget_off = {
        "retry_budget_ratio": 100,
        "retry_budget_max_tokens": 1.0e9,
        "retry_budget_min_per_s": 1.0e6,
    }
    for broken_breaker in (True, False):
        for disable_budget in (False, True):
            variant = copy.deepcopy(cfg)
            variant.client["max_attempts_per_provider"] = 5
            if broken_breaker:
                variant.client["breaker"]["min_calls"] = 1_000_000_000
            if disable_budget:
                variant.client.update(budget_off)
            label = f"breaker_{'disabled' if broken_breaker else 'enabled'}_budget_{'off' if disable_budget else 'on'}"
            print(label)
            results[label] = measure(variant, ("G2_overload_storm", "G3_brownout"), args.seed)
    for timeout in (cfg.client["attempt_timeout_s"], 30):
        variant = copy.deepcopy(cfg)
        variant.client["attempt_timeout_s"] = timeout
        label = f"timeout_{timeout:g}"
        print(label)
        results[label] = measure(variant, ("G6_provider_outage", "G4_slow_region"), args.seed)
    for unfiltered in (False, True):
        label = "tool_filter_off" if unfiltered else "tool_filter_on"
        print(label)
        results[label] = measure(copy.deepcopy(cfg), ("G6_provider_outage",), args.seed, unfiltered)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
