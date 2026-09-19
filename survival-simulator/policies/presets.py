"""Named policy configurations (see docs/journal.md for the experiment behind each one).

    from policies.presets import build_policy, PRESETS
    policy = build_policy(preset="14a")
    policy = build_policy(spec="policies.camper2:Camper2Policy", kwargs={"sprint_zone": 130})
"""
import json

from policies import load_policy

# name -> (policy spec, kwargs, note). Scores are 10-seed means on seeds 0-9.
PRESETS = {
    "dummy": ("policies.dummy:DummyPolicy", {}, "repository random walk, mean 28"),
    "v1_4c": ("policies.camper:CamperPolicy",
              {"hungry_energy": 350, "lookback": True, "crowd_max": 2, "scan_period": 5},
              "Exp 4c: v1 camper, mean 1060 / min 753"),
    "13a": ("policies.camper2:Camper2Policy",
            {"sprint_zone": 130, "aware": True, "select": True, "old_always": True},
            "Exp 13a: v2 + awareness + selection; 1111 (seeds 0-9), 1100 / min 739 (seeds 10-29) - default"),
    "13b": ("policies.camper2:Camper2Policy",
            {"sprint_zone": 130, "aware": True, "select": True, "old_always": True, "disperse_richest": True},
            "Exp 13b: 13a + richest leaves the camp, mean 1138 / min 773"),
    "14a": ("policies.camper2:Camper2Policy",
            {"sprint_zone": 130, "aware": True, "select": True, "old_always": True,
             "pop_schedule": [[0, 12], [600, 8]]},
            "Exp 14a: 13a + population 12 until t=600; 1202 on seeds 0-9 but 1004 / min 419 on seeds 10-29"),
}
DEFAULT_PRESET = "13a"


def parse_kwargs(items):
    """['k=v', ...] -> dict, values parsed as JSON when possible (true, 130, [[0,12]], "swamp")."""
    kwargs = {}
    for item in items or []:
        key, _, value = item.partition("=")
        if not _:
            raise ValueError(f"expected key=value, got {item!r}")
        try:
            kwargs[key] = json.loads(value)
        except json.JSONDecodeError:
            kwargs[key] = value
    return kwargs


def build_policy(preset=None, spec=None, kwargs=None):
    """Instantiate a policy from a preset name and/or an explicit spec; explicit kwargs override the preset's.

    Returns (policy, description) where description is a JSON-serialisable summary of what was built.
    """
    base_kwargs = {}
    if preset is not None:
        if preset not in PRESETS:
            raise KeyError(f"unknown preset {preset!r}; available: {', '.join(PRESETS)}")
        preset_spec, base_kwargs, _ = PRESETS[preset]
        spec = spec or preset_spec
    if spec is None:
        raise ValueError("need a preset or a policy spec")
    merged = {**base_kwargs, **(kwargs or {})}
    return load_policy(spec, **merged), {"preset": preset, "policy": spec, "kwargs": merged}
