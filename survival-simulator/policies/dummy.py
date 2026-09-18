"""Baseline: the repository's random-walk dummy policy, wrapped in the policy interface."""
import random

from src.utils.controllers.dummy_agent_policy import action_decision


class DummyPolicy:
    def __init__(self, seed: int = 1):
        self.rng = random.Random(seed)

    def act(self, step: dict) -> list:
        return [action_decision(agent, self.rng).dict() for agent in step["agent_status"]]


class IdlePolicy:
    """Stands still and never spawns. Used to measure the environment on its own."""

    def act(self, step: dict) -> list:
        return [
            {"agent_id": a["agent_id"], "move_distance": 0.0, "move_direction": 0.0,
             "turn_angle": 0.0, "spawn_agent": False}
            for a in step["agent_status"]
        ]
