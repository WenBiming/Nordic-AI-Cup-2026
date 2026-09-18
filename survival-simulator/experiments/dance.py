"""Exp 7: can an agent shed predators by keeping an obstacle between itself and them?

Hypothesis: Predator.step is stateless, so breaking line of sight for one tick resets it to wandering,
and edge avoidance then steers it away from the obstacle. A scripted agent next to a random interior
obstacle moves to the perimeter point that is occluded from / farthest from the nearest threatening
predator; otherwise it stays. Variants:
  idle      - never moves (same as Exp 6 obstacle_side)
  cheat     - knows every active predator position (upper bound)
  sensed    - reacts only to predators in its own observations (hearing disc + cone), with 40-tick memory

    python -m experiments.dance --seeds 0-29 --workers 3 --predators 12
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
from experiments.hiding import _free  # noqa: E402
from experiments.run import parse_seeds  # noqa: E402

MODES = ["idle", "cheat", "sensed", "sensed_big"]


def perimeter_points(o, off=8.0):
    x0, y0, x1, y1 = o.x - off, o.y - off, o.x + o.width + off, o.y + o.height + off
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return [(mx, y0), (mx, y1), (x0, my), (x1, my), (x0, y0), (x1, y0), (x0, y1), (x1, y1)]


def occluded(o, p, q, samples=12):
    """True if segment p->q passes through obstacle o."""
    for i in range(1, samples):
        t = i / samples
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if o.x < x < o.x + o.width and o.y < y < o.y + o.height:
            return True
    return False


def run_one(seed, mode, max_ticks=3000, predators=12):
    from src.core import SimulationCore
    from src.elements.agent import Agent
    from src.utils.DTOs import ActionRequest

    sim = SimulationCore(seed=seed, starting_agents=0, starting_predators=predators)
    env = sim.env
    rng = random.Random(seed * 7 + 1)
    interior = [o for o in env.obstacles if o.width < env.width and o.height < env.height]
    cands = []
    for o in interior:
        if mode.endswith("_big") and min(o.width, o.height) < 60:
            continue
        for (x, y) in perimeter_points(o):
            if _free(env, x, y) and all(_free(env, px, py) for (px, py) in perimeter_points(o)):
                cands.append((o, x, y))
    if not cands:
        return {"seed": seed, "mode": mode, "skipped": True}
    o, x, y = rng.choice(cands)
    agent = Agent(x=x, y=y, rng=env.rng, energy=500.0)
    agent.agent_id = env._next_agent_id
    env._next_agent_id += 1
    env.agents.append(agent)
    env._update_agent_grid()
    agent.max_age = 1e9
    agent.direction = math.atan2(y - (o.y + o.height / 2), x - (o.x + o.width / 2))
    env.agents_dict = {a.agent_id: a for a in env.agents}

    death_tick, energy_used, moved_ticks = None, 0.0, 0
    trace = []
    remembered = None  # (x, y, ttl) absolute, for 'sensed'
    state = sim.step([])
    for tick in range(1, max_ticks + 1):
        action = None
        threat = None
        if mode != "idle":
            if mode == "cheat":
                active = [(math.hypot(p.x - agent.x, p.y - agent.y), p) for p in env.predators if not p.resting]
                if active:
                    d, p = min(active, key=lambda t: t[0])
                    if d < 260:
                        threat = (p.x, p.y, d)
            else:
                obs = state["observations"][0]["observations"] if state["observations"] else []
                seen = [oo for oo in obs if oo["type"] == "Predator"]
                if seen:
                    s = min(seen, key=lambda oo: oo["distance"])
                    ang = agent.direction + s["angle"]
                    remembered = (agent.x + s["distance"] * math.cos(ang), agent.y + s["distance"] * math.sin(ang), 40)
                elif remembered is not None:
                    remembered = (remembered[0], remembered[1], remembered[2] - 1)
                    if remembered[2] <= 0:
                        remembered = None
                if remembered is not None:
                    threat = (remembered[0], remembered[1], math.hypot(remembered[0] - agent.x, remembered[1] - agent.y))
        if threat is not None:
            px, py, pd = threat
            best, best_score = None, -1e9
            for (qx, qy) in perimeter_points(o):
                dq = math.hypot(qx - px, qy - py)
                score = dq + (150.0 if occluded(o, (px, py), (qx, qy)) else 0.0) - 0.3 * math.hypot(qx - agent.x, qy - agent.y)
                if score > best_score:
                    best, best_score = (qx, qy), score
            tx, ty = best
            dist = math.hypot(tx - agent.x, ty - agent.y)
            if dist > 1.0:
                move = min(agent.sprint_speed if pd < 90 else agent.speed, dist)
                rel = (math.atan2(ty - agent.y, tx - agent.x) - agent.direction + math.pi) % (2 * math.pi) - math.pi
                action = ActionRequest(agent_id=agent.agent_id, move_distance=move, move_direction=rel,
                                       turn_angle=0.0, spawn_agent=False)
                moved_ticks += 1
        e0 = agent.energy
        active = [p for p in env.predators if not p.resting]
        if active:
            pn = min(active, key=lambda p: math.hypot(p.x - agent.x, p.y - agent.y))
            trace.append((tick, round(math.hypot(pn.x - agent.x, pn.y - agent.y)), occluded(o, (pn.x, pn.y), (agent.x, agent.y)),
                          threat is not None, action is not None, sum(1 for p in active if math.hypot(p.x - agent.x, p.y - agent.y) < 250)))
            trace = trace[-15:]
        state = sim.step([(agent.agent_id, action)] if action else [])
        energy_used += max(0.0, e0 - agent.energy - 0.1)
        if state["num_agents"] == 0:
            death_tick = tick
            break
    return {"seed": seed, "mode": mode, "skipped": False, "death_tick": death_tick,
            "energy_used": round(energy_used, 1), "moved_ticks": moved_ticks,
            "obstacle": (round(o.width), round(o.height)), "trace": trace if death_tick else []}


def _star(args):
    return run_one(*args)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", default="0-29")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--max-ticks", type=int, default=3000)
    p.add_argument("--predators", type=int, default=12)
    args = p.parse_args()
    seeds = parse_seeds(args.seeds)
    jobs = [(s, m, args.max_ticks, args.predators) for s in seeds for m in MODES]
    with Pool(args.workers) as pool:
        results = pool.map(_star, jobs)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "exp7_dance.json"), "w") as f:
        json.dump({"max_ticks": args.max_ticks, "predators": args.predators, "runs": results}, f)
    print(f"{'mode':8}{'n':>4}{'survived':>9}{'median_death_s':>15}{'mean_alive_s':>13}{'energy/100s':>12}{'moved%':>8}")
    for m in MODES:
        rs = [r for r in results if r["mode"] == m and not r["skipped"]]
        alive = [r["death_tick"] if r["death_tick"] else args.max_ticks for r in rs]
        deaths = [r["death_tick"] for r in rs if r["death_tick"]]
        e = sum(r["energy_used"] for r in rs) / max(1, sum(alive)) * 1000
        mv = 100 * sum(r["moved_ticks"] for r in rs) / max(1, sum(alive))
        print(f"{m:8}{len(rs):>4}{sum(1 for r in rs if not r['death_tick']):>9}"
              f"{(statistics.median(deaths) / 10 if deaths else float('nan')):>15.1f}"
              f"{statistics.fmean(alive) / 10:>13.1f}{e:>12.1f}{mv:>8.1f}")
