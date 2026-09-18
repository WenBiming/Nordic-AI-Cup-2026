"""Exp 6: how much does the standing spot change an idle agent's kill rate?

For each seed and spot type, one idle agent (500 energy, no ageing) is placed and 20 predators roam
for up to `max_ticks`. Records time to death. Spot types:
  open           - random point >= 150 from every obstacle and wall
  wall           - 8 units off a random boundary wall, facing away from it
  corner         - a map corner (38, 38), facing the diagonal
  obstacle_side  - 8 units off the midpoint of a random side of a random obstacle, facing away
  nook           - obstacle side facing a boundary wall closer than 70 (a concave pocket), if one exists

    python -m experiments.hiding --seeds 0-19 --workers 2
"""
import argparse
import json
import math
import os
import random
import statistics
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from experiments.harness import RESULTS_DIR  # noqa: E402
from experiments.run import parse_seeds  # noqa: E402

SPOTS = ["open", "wall", "corner", "obstacle_side", "nook"]


def _free(env, x, y):
    return 8 < x < env.width - 8 and 8 < y < env.height - 8 and \
        not env._in_obstacle((x, y), radius=6, obstacles=env.obstacles)


def pick_spot(env, kind, rng):
    W, H = env.width, env.height
    interior = [o for o in env.obstacles if o.width < W and o.height < H]
    if kind == "open":
        for _ in range(500):
            x, y = rng.uniform(200, W - 200), rng.uniform(200, H - 200)
            if all(x < o.x - 100 or x > o.x + o.width + 100 or y < o.y - 100 or y > o.y + o.height + 100
                   for o in interior):
                return x, y, rng.uniform(0, 2 * math.pi)
        return None
    if kind == "wall":
        side = rng.choice("NSEW")
        for _ in range(200):
            if side == "N":
                x, y, d = rng.uniform(100, W - 100), 38, math.pi / 2
            elif side == "S":
                x, y, d = rng.uniform(100, W - 100), H - 38, -math.pi / 2
            elif side == "W":
                x, y, d = 38, rng.uniform(100, H - 100), 0.0
            else:
                x, y, d = W - 38, rng.uniform(100, H - 100), math.pi
            if _free(env, x, y):
                return x, y, d
        return None
    if kind == "corner":
        cx, cy = rng.choice([(38, 38), (W - 38, 38), (38, H - 38), (W - 38, H - 38)])
        return cx, cy, math.atan2(H / 2 - cy, W / 2 - cx)
    if kind in ("obstacle_side", "nook"):
        cands = []
        for o in interior:
            sides = [  # (x, y, facing)
                (o.x + o.width / 2, o.y - 8, -math.pi / 2),
                (o.x + o.width / 2, o.y + o.height + 8, math.pi / 2),
                (o.x - 8, o.y + o.height / 2, math.pi),
                (o.x + o.width + 8, o.y + o.height / 2, 0.0),
            ]
            for (x, y, d) in sides:
                if not _free(env, x, y):
                    continue
                if kind == "nook":
                    # facing direction must hit a boundary wall within 70
                    hit = (d == -math.pi / 2 and y < 30 + 70) or (d == math.pi / 2 and y > H - 30 - 70) or \
                          (d == math.pi and x < 30 + 70) or (d == 0.0 and x > W - 30 - 70)
                    if not hit:
                        continue
                cands.append((x, y, d))
        if not cands:
            return None
        return rng.choice(cands)
    raise ValueError(kind)


def run_one(seed, kind, max_ticks=3000, predators=20):
    from src.core import SimulationCore
    sim = SimulationCore(seed=seed, starting_agents=0, starting_predators=predators)
    env = sim.env
    rng = random.Random(seed * 7 + 1)
    spot = pick_spot(env, kind, rng)
    if spot is None:
        return {"seed": seed, "spot": kind, "skipped": True}
    x, y, facing = spot
    if not _free(env, x, y):
        return {"seed": seed, "spot": kind, "skipped": True}
    from src.elements.agent import Agent
    agent = Agent(x=x, y=y, rng=env.rng, energy=500.0)
    agent.agent_id = env._next_agent_id
    env._next_agent_id += 1
    env.agents.append(agent)
    env._update_agent_grid()
    agent.energy = 500.0
    agent.max_age = 1e9
    agent.direction = facing
    env.agents_dict = {a.agent_id: a for a in env.agents}
    death_tick = None
    for tick in range(1, max_ticks + 1):
        state = sim.step([])
        if state["num_agents"] == 0:
            death_tick = tick
            break
    return {"seed": seed, "spot": kind, "skipped": False, "death_tick": death_tick,
            "x": round(x), "y": round(y)}


def _star(args):
    return run_one(*args)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", default="0-19")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--max-ticks", type=int, default=3000)
    p.add_argument("--predators", type=int, default=20)
    args = p.parse_args()
    seeds = parse_seeds(args.seeds)
    jobs = [(s, k, args.max_ticks, args.predators) for s in seeds for k in SPOTS]
    with Pool(args.workers) as pool:
        results = pool.map(_star, jobs)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "exp6_hiding.json"), "w") as f:
        json.dump({"max_ticks": args.max_ticks, "predators": args.predators, "runs": results}, f)
    print(f"{'spot':14}{'n':>4}{'survived':>9}{'median_death_s':>15}{'mean_alive_s':>13}")
    for k in SPOTS:
        rs = [r for r in results if r["spot"] == k and not r["skipped"]]
        if not rs:
            print(f"{k:14}   0")
            continue
        alive = [r["death_tick"] if r["death_tick"] else args.max_ticks for r in rs]
        deaths = [r["death_tick"] for r in rs if r["death_tick"]]
        print(f"{k:14}{len(rs):>4}{sum(1 for r in rs if not r['death_tick']):>9}"
              f"{(statistics.median(deaths) / 10 if deaths else float('nan')):>15.1f}"
              f"{statistics.fmean(alive) / 10:>13.1f}")
