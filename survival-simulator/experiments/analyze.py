"""Print a timeline averaged over the runs of a result file.

    python -m experiments.analyze exp0_env_dynamics [--every 300]
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.harness import RESULTS_DIR, format_table  # noqa: E402

FIELDS = ["agents", "energy", "mean_age", "predators", "predators_active", "trees", "mature_trees", "fruits", "score", "speed", "max_speed", "hearing", "vision"]


def timeline_table(out, every=300.0):
    runs = out["runs"]
    times = sorted({s["t"] for r in runs for s in r["timeline"]})
    # samples sit at k*10 + 0.1 (one warm-up step before the loop); take the one nearest each multiple of `every`
    picks = []
    k = 1
    while times and k * every <= times[-1] + every / 2:
        picks.append(min(times, key=lambda t: abs(t - k * every)))
        k += 1
    header = f"{'t':>6} {'alive':>5} " + " ".join(f"{f:>9}" for f in FIELDS)
    lines = [header]
    for t in picks:
        samples = [s for r in runs for s in r["timeline"] if s["t"] == t]
        if not samples:
            continue
        row = f"{t:>6.0f} {len(samples):>5} "
        row += " ".join(f"{statistics.fmean(s.get(f, 0.0) for s in samples):>9.1f}" for f in FIELDS)
        lines.append(row)
    return "\n".join(lines)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--every", type=float, default=300.0)
    args = p.parse_args()
    with open(os.path.join(RESULTS_DIR, f"{args.name}.json")) as f:
        out = json.load(f)
    print(format_table(out))
    print()
    print("timeline (mean over runs still alive at t):")
    print(timeline_table(out, args.every))
