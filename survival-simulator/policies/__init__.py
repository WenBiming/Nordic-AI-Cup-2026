"""Hivemind policies. Each policy is a class with ``act(step: dict) -> list[dict]``.

``step`` has the shape of ``StepResponse`` (game_status, score, sim_time, n_agents,
agent_status) and the returned list holds one ``ActionRequest``-shaped dict per agent.
The same object is used by ``agent_server.py`` and ``experiments/harness.py``.
"""
import importlib


def load_policy(spec: str, **kwargs):
    """Instantiate ``"module.path:ClassName"`` with keyword arguments."""
    module_name, class_name = spec.split(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(**kwargs)
