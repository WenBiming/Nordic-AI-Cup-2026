"""Headless experiment harness.

Runs a policy on one or many seeds, instruments the environment for death causes and
fruit consumption, samples a timeline, and writes JSON results.
"""
import json
import os
import statistics
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

RESULTS_DIR = os.path.join(ROOT, "experiments", "results")


def _instrument(env, stats):
    orig_kill = env.kill_agent

    def kill_agent(agent):
        cause = "starved" if agent.energy <= 0 else "eaten"
        stats[cause] += 1
        if cause == "eaten":
            stats["eaten_energy"] += float(agent.energy)
        stats["deaths"].append([round(env.time, 1), cause, round(float(agent.energy), 1), round(agent.age, 1)])
        orig_kill(agent)

    env.kill_agent = kill_agent

    orig_remove_fruit = env.remove_fruit

    def remove_fruit(fruit):
        if fruit.age <= 100:  # rot removes at age > 100; anything else is a bite
            stats["fruits_eaten"] += 1
            stats["fruit_energy"] += float(fruit.energy)
        orig_remove_fruit(fruit)

    env.remove_fruit = remove_fruit

    orig_spawn = env.spawn_agent

    def spawn_agent(*args, **kwargs):
        if kwargs.get("parent") is not None:
            stats["spawned"] += 1
            stats["births"].append(round(env.time, 1))
        return orig_spawn(*args, **kwargs)

    env.spawn_agent = spawn_agent


def _sample(env, state):
    agents = env.agents
    return {
        "t": round(env.time, 1),
        "score": round(state["score"], 3),
        "agents": len(agents),
        "energy": round(sum(a.energy for a in agents), 1),
        "mean_age": round(statistics.fmean(a.age for a in agents), 1) if agents else 0.0,
        "predators": len(env.predators),
        "predators_active": sum(1 for p in env.predators if not p.resting),
        "trees": len(env.trees),
        "mature_trees": sum(1 for t in env.trees if t.age >= 20),
        "fruits": len(env.fruits),
        "speed": round(statistics.fmean(a.speed for a in agents), 2) if agents else 0.0,
        "sprint": round(statistics.fmean(a.sprint_speed for a in agents), 2) if agents else 0.0,
        "hearing": round(statistics.fmean(a.hearing_radius for a in agents), 1) if agents else 0.0,
        "vision": round(statistics.fmean(a.vision_radius for a in agents), 1) if agents else 0.0,
        "max_speed": round(max((a.speed for a in agents), default=0.0), 2),
    }


def run_game(policy_spec, policy_kwargs, seed, max_time=3000.0, sample_every=100,
             starting_agents=5, stop_on_extinct=True):
    """Run one game. Returns a result dict (JSON-serialisable)."""
    from src.core import SimulationCore
    from src.utils.DTOs import ActionRequest
    from policies import load_policy

    policy = load_policy(policy_spec, **policy_kwargs)
    sim = SimulationCore(seed=seed, starting_agents=starting_agents)
    env = sim.env
    stats = {"starved": 0, "eaten": 0, "eaten_energy": 0.0,
             "fruits_eaten": 0, "fruit_energy": 0.0, "spawned": 0, "deaths": [], "births": []}
    _instrument(env, stats)

    wall_start = time.perf_counter()
    policy_time = 0.0
    timeline = []
    peak_agents = starting_agents
    tick = 0
    state = sim.step([])
    while True:
        step = {
            "game_status": "ok",
            "score": state["score"],
            "sim_time": state["sim_time"],
            "n_agents": state["num_agents"],
            "agent_status": [o for o in state["observations"] if o is not None],
        }
        t0 = time.perf_counter()
        raw_actions = policy.act(step)
        policy_time += time.perf_counter() - t0
        actions = []
        for a in raw_actions:
            if not isinstance(a, ActionRequest):
                a = ActionRequest(**a)
            actions.append((a.agent_id, a))
        state = sim.step(actions)
        tick += 1
        peak_agents = max(peak_agents, state["num_agents"])
        if tick % sample_every == 0:
            timeline.append(_sample(env, state))
        if (stop_on_extinct and state["num_agents"] == 0) or env.time > max_time:
            break

    return {
        "seed": seed,
        "policy": policy_spec,
        "policy_kwargs": policy_kwargs,
        "score": state["score"],
        "survival_time": round(env.time, 1),
        "ticks": tick,
        "extinct": state["num_agents"] == 0,
        "peak_agents": peak_agents,
        "final_agents": state["num_agents"],
        "final_predators": len(env.predators),
        "stats": stats,
        "policy_stats": policy.stats() if hasattr(policy, "stats") else None,
        "policy_ms_per_tick": round(1000 * policy_time / max(1, tick), 3),
        "wall_s": round(time.perf_counter() - wall_start, 1),
        "timeline": timeline,
    }


def _run_game_star(args):
    return run_game(*args)


def run_batch(name, policy_spec, seeds, policy_kwargs=None, workers=None, **game_kwargs):
    """Run many seeds in parallel and write ``experiments/results/<name>.json``."""
    policy_kwargs = policy_kwargs or {}
    jobs = [(policy_spec, policy_kwargs, s) for s in seeds]
    t0 = time.perf_counter()
    if workers == 1:
        results = [run_game(*j, **game_kwargs) for j in jobs]
    else:
        with Pool(workers) as pool:
            results = pool.starmap(_run_with_kwargs, [(j, game_kwargs) for j in jobs])
    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = {"name": name, "policy": policy_spec, "policy_kwargs": policy_kwargs,
           "game_kwargs": game_kwargs, "wall_s": round(time.perf_counter() - t0, 1),
           "summary": summarize(results), "runs": results}
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def _run_with_kwargs(job, game_kwargs):
    return run_game(*job, **game_kwargs)


def summarize(results):
    scores = [r["score"] for r in results]
    surv = [r["survival_time"] for r in results]
    return {
        "n": len(results),
        "score_mean": round(statistics.fmean(scores), 2),
        "score_median": round(statistics.median(scores), 2),
        "score_min": round(min(scores), 2),
        "score_max": round(max(scores), 2),
        "survival_median": round(statistics.median(surv), 1),
        "survival_min": round(min(surv), 1),
        "full_runs": sum(1 for r in results if not r["extinct"]),
        "starved": sum(r["stats"]["starved"] for r in results),
        "eaten": sum(r["stats"]["eaten"] for r in results),
        "fruits_eaten": sum(r["stats"]["fruits_eaten"] for r in results),
        "spawned": sum(r["stats"]["spawned"] for r in results),
        "policy_ms_per_tick": round(statistics.fmean(r["policy_ms_per_tick"] for r in results), 3),
    }


def format_table(out):
    lines = [f"{'seed':>10} {'score':>9} {'surv':>7} {'peak':>5} {'starv':>5} {'eaten':>5} "
             f"{'fruit':>6} {'spawn':>5} {'pred':>4} {'ms/tick':>7}"]
    for r in out["runs"]:
        s = r["stats"]
        lines.append(f"{r['seed']:>10} {r['score']:>9.2f} {r['survival_time']:>7.1f} {r['peak_agents']:>5} "
                     f"{s['starved']:>5} {s['eaten']:>5} {s['fruits_eaten']:>6} {s['spawned']:>5} "
                     f"{r['final_predators']:>4} {r['policy_ms_per_tick']:>7.2f}")
    lines.append(json.dumps(out["summary"]))
    return "\n".join(lines)
