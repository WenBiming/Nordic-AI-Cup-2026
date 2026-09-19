"""Random search over policy parameters, each candidate scored on the same seeds.

    python -m experiments.search --name s1 --seeds 10-29 --workers 8 --n 20 \
        --base sprint_zone=130 aware=true select=true old_always=true \
        --space charge_dist=80:110 sprint_zone=100:160 threat_ttl=20:60 spawn_energy=250:400 \
                old_age=60:90 crowd_dist=40:100 hungry_energy=250:400

Each `--space k=lo:hi` samples uniformly (integers if both bounds are integers). Results append to
experiments/results/search_<name>.csv (one row per candidate: mean, median, min, kwargs) so a run
can be interrupted and resumed with a different --n. `--base` values are fixed kwargs.
"""
import argparse
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.harness import RESULTS_DIR, run_batch  # noqa: E402
from experiments.run import parse_kw, parse_seeds  # noqa: E402


def sample(space, rng):
    out = {}
    for k, (lo, hi) in space.items():
        if float(lo).is_integer() and float(hi).is_integer():
            out[k] = rng.randint(int(lo), int(hi))
        else:
            out[k] = round(rng.uniform(lo, hi), 3)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--policy", default="policies.camper2:Camper2Policy")
    p.add_argument("--seeds", default="10-29")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--rng", type=int, default=0)
    p.add_argument("--base", nargs="*", default=[])
    p.add_argument("--space", nargs="*", default=[])
    args = p.parse_args()
    base = parse_kw(args.base)
    space = {}
    for item in args.space:
        k, rng_ = item.split("=")
        lo, hi = rng_.split(":")
        space[k] = (float(lo), float(hi))
    rng = random.Random(args.rng)
    path = os.path.join(RESULTS_DIR, f"search_{args.name}.csv")
    done = 0
    if os.path.exists(path):
        with open(path) as f:
            done = sum(1 for _ in f) - 1
    for _ in range(done):  # advance the rng past candidates already evaluated
        sample(space, rng)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["idx", "mean", "median", "min", "max", "starved", "eaten", "spawned", "kwargs"])
        for i in range(done, done + args.n):
            cand = sample(space, rng)
            kw = {**base, **cand}
            out = run_batch(f"search_{args.name}_{i}", args.policy, parse_seeds(args.seeds), policy_kwargs=kw,
                            workers=args.workers)
            s = out["summary"]
            w.writerow([i, s["score_mean"], s["score_median"], s["score_min"], s["score_max"], s["starved"],
                        s["eaten"], s["spawned"], json.dumps(cand)])
            f.flush()
            print(f"[{i}] mean={s['score_mean']:.1f} med={s['score_median']:.1f} min={s['score_min']:.1f} {cand}", flush=True)
