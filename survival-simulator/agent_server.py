"""Agent endpoint. Pick the policy on the command line:

    python agent_server.py                              # default preset (see policies/presets.py)
    python agent_server.py --preset 13a
    python agent_server.py --preset 14a --kw pop_cap=10 # preset with overrides
    python agent_server.py --policy policies.camper2:Camper2Policy --kw sprint_zone=130 aware=true
    python agent_server.py --list                       # show presets

GET / reports which policy is loaded.
"""
import argparse

from fastapi import FastAPI, Body

from policies.presets import DEFAULT_PRESET, PRESETS, build_policy, parse_kwargs
from src.utils.DTOs import StepResponse

HOST = "0.0.0.0"
PORT = 9052

app = FastAPI(title="Survival Simulator Agent Endpoint")

# One hivemind per server process; it resets its memory when sim_time goes backwards
# (a new game), so it survives the evaluation's three consecutive runs.
policy, policy_info = build_policy(preset=DEFAULT_PRESET)


def configure(preset=None, spec=None, kwargs=None):
    """Replace the served policy (used by the CLI; importable for tests)."""
    global policy, policy_info
    policy, policy_info = build_policy(preset=preset, spec=spec, kwargs=kwargs)
    return policy_info


# The simulator sends capitalised observation types; the platform's verify sample sends lowercase ones.
_TYPES = {"fruit": "Fruit", "agent": "Agent", "predator": "Predator", "tree": "Tree", "edge": "Edge"}


@app.post("/predict")
@app.post("/")  # the platform's verify call posts to the base URL as given
def predict(step: StepResponse = Body(...)):
    """
    Receives the current simulation state and returns actions for all agents.
    """
    data = step.model_dump()
    for agent in data["agent_status"]:
        for obs in agent["observations"]:
            t = obs.get("type")
            if isinstance(t, str):
                obs["type"] = _TYPES.get(t.lower(), t)
    actions = policy.act(data)

    # Must return {"actions": [...]} format
    return {"actions": actions}


@app.get("/")
def index():
    return {"message": "Agent endpoint running!", **policy_info}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", choices=sorted(PRESETS), help=f"named configuration (default: {DEFAULT_PRESET})")
    p.add_argument("--policy", help="policy spec module.path:ClassName (overrides the preset's class)")
    p.add_argument("--kw", nargs="*", metavar="KEY=JSON", help="policy kwargs, override the preset's")
    p.add_argument("--list", action="store_true", help="list presets and exit")
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    return p.parse_args()


if __name__ == "__main__":
    import uvicorn

    args = parse_args()
    if args.list:
        for name, (spec, kwargs, note) in PRESETS.items():
            print(f"{name:8} {note}\n         {spec} {kwargs}")
        raise SystemExit(0)
    preset = args.preset or (None if args.policy else DEFAULT_PRESET)
    info = configure(preset=preset, spec=args.policy, kwargs=parse_kwargs(args.kw))
    print(f"serving {info}")
    uvicorn.run(app, host=args.host, port=args.port)
