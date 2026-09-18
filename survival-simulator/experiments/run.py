"""CLI: run a policy over seeds and print a summary table.

    python -m experiments.run --name exp1_baseline --policy policies.dummy:DummyPolicy --seeds 0-9
    python -m experiments.run --name exp2_v1 --policy policies.camper:CamperPolicy --seeds 0-9 --kw pop_cap=8
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experiments.harness import run_batch, format_table  # noqa: E402


def parse_seeds(text):
    seeds = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            seeds.extend(range(int(a), int(b) + 1))
        else:
            seeds.append(int(part))
    return seeds


def parse_kw(items):
    kw = {}
    for item in items or []:
        k, v = item.split("=", 1)
        try:
            kw[k] = json.loads(v)
        except json.JSONDecodeError:
            kw[k] = v
    return kw


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--policy", required=True)
    p.add_argument("--seeds", default="0-9")
    p.add_argument("--kw", nargs="*", help="policy kwargs as key=json")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--max-time", type=float, default=3000.0)
    p.add_argument("--starting-agents", type=int, default=5)
    p.add_argument("--no-stop", action="store_true", help="keep simulating after extinction")
    args = p.parse_args()

    out = run_batch(args.name, args.policy, parse_seeds(args.seeds), policy_kwargs=parse_kw(args.kw),
                    workers=args.workers, max_time=args.max_time,
                    starting_agents=args.starting_agents, stop_on_extinct=not args.no_stop)
    print(format_table(out))
    print(f"wrote experiments/results/{args.name}.json in {out['wall_s']} s")
