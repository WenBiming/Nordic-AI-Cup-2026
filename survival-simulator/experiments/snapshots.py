"""Render PNG snapshots of a game around agent deaths (or at fixed times) for visual inspection.

    python -m experiments.snapshots --policy policies.camper:CamperPolicy --seed 0 --kw hungry_energy=350 \
        --out /tmp/snaps --before 15 --max-deaths 12

Each death produces one frame `before` ticks earlier (agents still alive) and one at the death tick,
cropped to a window around the dying agent. Vision cones / hearing discs are drawn by the simulator.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from experiments.run import parse_kw  # noqa: E402
from policies import load_policy  # noqa: E402
from src.core import SimulationCore  # noqa: E402
from src.utils.DTOs import ActionRequest  # noqa: E402


def crop_save(env, surface, cx, cy, path, window=500):
    env.draw(surface)
    x0 = int(max(0, min(env.width - window, cx - window / 2)))
    y0 = int(max(0, min(env.height - window, cy - window / 2)))
    sub = surface.subsurface(pygame.Rect(x0, y0, window, window)).copy()
    pygame.draw.circle(sub, (255, 255, 0), (int(cx - x0), int(cy - y0)), 14, 2)  # mark the agent
    pygame.image.save(sub, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", required=True)
    p.add_argument("--kw", nargs="*")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True)
    p.add_argument("--before", type=int, default=15, help="ticks before death for the first frame")
    p.add_argument("--max-deaths", type=int, default=10)
    p.add_argument("--max-time", type=float, default=3000.0)
    p.add_argument("--skip-starved", action="store_true")
    p.add_argument("--at", type=float, nargs="*", default=[], help="also snapshot the whole map at these times")
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)

    pygame.init()
    policy = load_policy(args.policy, **parse_kw(args.kw))
    sim = SimulationCore(seed=args.seed)
    env = sim.env
    surface = pygame.Surface((env.width, env.height))

    history = []  # ring of (tick, {agent_id: (x, y, energy)}) for the "before" frames — we re-render by re-running
    deaths = []
    orig_kill = env.kill_agent

    def kill_agent(agent):
        cause = "starved" if agent.energy <= 0 else "eaten"
        deaths.append((tick, cause, agent.agent_id, agent.x, agent.y, agent.energy, agent.age))
        orig_kill(agent)

    env.kill_agent = kill_agent

    tick = 0
    state = sim.step([])
    pending = {}  # tick -> list of (agent_id, label)
    saved = 0
    at_times = sorted(args.at)
    while True:
        step = {"game_status": "ok", "score": state["score"], "sim_time": state["sim_time"],
                "n_agents": state["num_agents"], "agent_status": [o for o in state["observations"] if o]}
        actions = [(a["agent_id"], ActionRequest(**a)) for a in policy.act(step)]
        # frame before a death: we cannot look ahead, so keep a rolling snapshot of positions and
        # render "before" frames from the current state every `before` ticks for agents that die soon.
        pos = {a.agent_id: (a.x, a.y, a.energy) for a in env.agents}
        history.append((tick, pos))
        if len(history) > args.before + 1:
            history.pop(0)
        n_deaths_before = len(deaths)
        state = sim.step(actions)
        tick += 1
        for d in deaths[n_deaths_before:]:
            _, cause, aid, x, y, e, age = d
            if cause == "starved" and args.skip_starved:
                continue
            if saved >= args.max_deaths:
                continue
            saved += 1
            label = f"{saved:02d}_t{env.time:.0f}_{cause}_id{aid}_e{e:.0f}_age{age:.0f}"
            crop_save(env, surface, x, y, os.path.join(args.out, label + "_death.png"))
            print(label)
        if at_times and env.time >= at_times[0]:
            env.draw(surface)
            pygame.image.save(surface, os.path.join(args.out, f"map_t{at_times[0]:.0f}.png"))
            at_times.pop(0)
        if state["num_agents"] == 0 or env.time > args.max_time:
            break
    print(f"done: t={env.time:.1f} score={state['score']:.1f} deaths={len(deaths)}")


if __name__ == "__main__":
    main()
