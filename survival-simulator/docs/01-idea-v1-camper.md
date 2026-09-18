# Idea v1 — "Tree camper" hivemind

Date: 2026-09-18. Status: proposed → executing.

## Reasoning (from `00-mechanics.md`)

1. Score ≈ survival time. Everything else is noise until the species reliably reaches t = 3000.
2. Agents cannot idle through the game (1 energy/s, 500 cap) and cannot live past ~150 s (old-age drain). So the species needs a **steady energy income** and a **steady stream of children**.
3. Walking is 5× the living cost. Wandering to find fruit is the wrong economy. Fruit only appears next to mature trees, at ~0.1 fruit/s ≈ 4 energy/s per tree vs. 1 energy/s to live. **Sitting at a tree and picking fruit as it spawns is net positive; wandering is net negative.**
4. Predators detect at 250 in a cone / 60 around; agents see only 200 / 50. But a predator only charges when the agent looks away or is within 90. Facing it and backing off drains its energy at 2.55/tick.
5. Late game (t > 1500) has few trees and many predators. Population should be moderate: enough redundancy to survive unlucky kills, not so many that fruit runs out.

## Policy sketch (per tick, per agent; hivemind keeps memory keyed by agent id)

Priority order:

1. **Threat response** — if a predator is observed:
   - distance < `charge_dist` (90) → *flee*: move directly away at sprint speed (as long as energy allows), no turn.
   - else → *stand-off*: turn to face the predator (turn = its angle), walk away at full walk speed.
2. **Eat** — if a fruit is observed: move toward the nearest fruit, distance `min(speed, d)`; turn toward it only if outside the hearing radius (keep it in the cone).
3. **Camp** — if a tree is observed within `camp_radius` (≈ 35, inside hearing range so all fruit around it is sensed): stand still, and every `scan_period` ticks turn by the cone angle to look around (cheap: ~1 energy per full rotation).
   - if a tree is observed farther away: walk toward the nearest tree.
4. **Explore** — nothing useful seen: walk forward at `explore_speed` with a slow scanning turn; if energy is below `explore_min_energy`, stay still and only scan (cheaper to wait than to search).
5. **Reproduce** — independent flag: spawn when `energy > spawn_energy` (e.g. 300) and population < `pop_cap`, or when `age > old_age` (≈ 70) and `energy > 100` (dump energy into a child before the old-age drain eats it).

Memory: last-seen tree bearing (to keep walking toward a tree that left the cone), tick counter for scanning, per-agent "fleeing" timer so a predator that dropped out of sight is still run from for a few ticks.

## Experiments

- **Exp 0 – environment dynamics.** No agents. Record trees, fruits, predators (active/resting) every 10 s over 3000 s for 5 seeds. Purpose: confirm the tree-collapse and predator-growth predictions; they decide how aggressive reproduction and how much late-game hiding are needed.
- **Exp 1 – baseline.** Dummy policy, 10 seeds. Metrics: survival time, score, deaths by starvation vs predator.
- **Exp 2 – v1 camper.** Same 10 seeds. Success criterion: median survival ≥ 1500 s (baseline ≈ 20 s). Log death causes and population timeline to see what kills the species first.
- **Exp 3 – ablations** on whatever kills us in Exp 2 (pop_cap, spawn_energy, stand-off vs flee thresholds).

Harness: `experiments/harness.py` — headless, seeds in parallel, instruments `kill_agent` (energy ≤ 0 ⇒ starvation, else predator) and `remove_fruit` (age ≤ 100 ⇒ eaten), samples a timeline every 100 ticks, writes JSON to `experiments/results/`. The policy class is shared with `agent_server.py`, so what is tested is what is served.
