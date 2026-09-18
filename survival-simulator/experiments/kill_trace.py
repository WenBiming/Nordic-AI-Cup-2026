"""Text trace of the last ticks before each predator kill.

    python -m experiments.kill_trace --policy policies.camper:CamperPolicy --seed 0 --kw hungry_energy=350 ...

For each eaten agent prints, tick by tick: policy branch, energy, biome, true distance to the nearest
predator (from the environment), distance of the nearest predator the agent actually observed (or '-'),
number of predators within 250, commanded move / turn.
"""
import argparse
import math
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from experiments.run import parse_kw  # noqa: E402
from policies import load_policy  # noqa: E402
from src.core import SimulationCore  # noqa: E402
from src.utils.DTOs import ActionRequest  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", required=True)
    p.add_argument("--kw", nargs="*")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ticks", type=int, default=25)
    p.add_argument("--max-kills", type=int, default=12)
    p.add_argument("--max-time", type=float, default=3000.0)
    p.add_argument("--starved", action="store_true", help="trace starvation deaths instead of kills")
    p.add_argument("--min-t", type=float, default=0.0, help="ignore deaths before this time")
    args = p.parse_args()

    policy = load_policy(args.policy, **parse_kw(args.kw))
    sim = SimulationCore(seed=args.seed)
    env = sim.env
    traces = defaultdict(lambda: deque(maxlen=args.ticks))
    kills = []
    orig_kill = env.kill_agent

    hist = defaultdict(lambda: defaultdict(int))

    def kill_agent(agent):
        want = (agent.energy <= 0) if args.starved else (agent.energy > 0)
        if want and env.time >= args.min_t:
            kills.append((env.time, agent.agent_id, agent.energy, agent.age, list(traces[agent.agent_id]), dict(hist[agent.agent_id])))
        orig_kill(agent)

    env.kill_agent = kill_agent

    state = sim.step([])
    tick = 0
    while True:
        step = {"game_status": "ok", "score": state["score"], "sim_time": state["sim_time"],
                "n_agents": state["num_agents"], "agent_status": [o for o in state["observations"] if o]}
        raw = policy.act(step)
        by_id = {a["agent_id"]: a for a in raw}
        for o in step["agent_status"]:
            ag = env.agents_dict.get(o["agent_id"])
            if ag is None:
                continue
            dists = [math.hypot(pr.x - ag.x, pr.y - ag.y) for pr in env.predators if not pr.resting]
            seen = [x["distance"] for x in o["observations"] if x["type"] == "Predator"]
            a = by_id[o["agent_id"]]
            m = policy.mem.get(o["agent_id"], {}) if hasattr(policy, "mem") else {}
            hist[o["agent_id"]][m.get("branch", "?")] += 1
            traces[o["agent_id"]].append(
                f"t={env.time:6.1f} {m.get('branch', '?'):10} e={o['energy']:6.1f} {o['biome'][:5]:5} "
                f"true_d={min(dists) if dists else -1:6.1f} seen_d={min(seen) if seen else -1:6.1f} "
                f"n250={sum(1 for d in dists if d < 250)} move={a['move_distance']:5.1f} "
                f"dir={a['move_direction']:5.2f} turn={a['turn_angle']:5.2f}")
        actions = [(a["agent_id"], ActionRequest(**a)) for a in raw]
        state = sim.step(actions)
        tick += 1
        if state["num_agents"] == 0 or env.time > args.max_time or len(kills) >= args.max_kills:
            break

    for t, aid, e, age, tr, h in kills[:args.max_kills]:
        tot = sum(h.values()) or 1
        print(f"\n=== {'starved' if args.starved else 'eaten'} at t={t:.1f} id={aid} energy={e:.0f} age={age:.0f}  life: " + ", ".join(f"{k} {100*v/tot:.0f}%" for k, v in sorted(h.items(), key=lambda kv: -kv[1])))
        print("\n".join(tr))
    print(f"\nrun ended t={env.time:.1f} agents={state['num_agents']} kills_recorded={len(kills)}")


if __name__ == "__main__":
    main()
