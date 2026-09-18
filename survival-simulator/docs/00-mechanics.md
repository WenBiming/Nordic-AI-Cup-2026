# Simulator mechanics (digest of `src/`)

All numbers are from the code, not the README. Time step `dt = 0.1 s`; 1 unit = 1 pixel on a 1600×1200 map. Game ends at 3000 s (30 000 ticks) or when no agent is alive.

## Scoring (`environment.py:non_agent_step`)

| Event | Score change |
|---|---|
| Every tick, regardless of population | `+dt` (= +0.1) → **max 3000 from survival** |
| Agent eats a fruit | `+fruit.energy / 1000` (fruit energy 20–60 → +0.02…+0.06) |
| Predator touches an agent | `−agent.energy / 100` (an agent at 500 energy → −5) |

Consequence: the score is ~99 % survival time. Fruit is worth almost nothing directly; it matters only as the energy source. Predator kills hurt in proportion to the victim's energy, so fat agents should not get eaten; empty agents dying is free.

## Agent energy (`environment.py`)

Defaults: `speed 10`, `sprint_speed 20`, `max_energy 500`, `hearing 50`, `vision 200`, `cone π/3`. Starting agents have 150 energy; children spawn with **75**.

| Cost | Per tick | Per second |
|---|---|---|
| Living (all biomes have `energy_drain_rate = 1.0`) | 0.1 | 1 |
| Walking distance `d ≤ speed` | `0.05 d` (full walk 10 → 0.5) | 5 at full walk |
| Sprinting `speed < d ≤ sprint` | `0.05·speed + 0.5·(d − speed)` (d=20 → 5.5) | 55 |
| Turn by θ | `min(π,|θ|)/2π` (π/3 → 0.167, max 0.5) | – |
| Spawn child | 100 (requires `energy > 100`) | – |
| Old age: once `age > max_age` (`max_age` ~ U(60,120), hidden) | `0.01·age` **per tick** (age 100 → 1.0/tick = 10/s) | 10+ |

Sprinting is blocked (capped to walk speed) when `energy < max_energy/5`. Movement distance is multiplied by the biome `move_penalty` (swamp 0.5, desert 0.8, river 0.3, forest/grassland 1.0) but the energy cost is charged on the requested distance. River flow is defined but never applied.

Old-age drain makes every agent's practical lifespan ≈ `max_age + 30…50 s` (100–170 s). **Reproduction is mandatory** — roughly 20–30 generations per game. A spawn nets −25 energy species-wide (100 paid, 75 delivered) and a fresh `max_age`.

Fruit is eaten on touch (`distance < agent.size(5) + fruit.radius`), energy capped at `max_energy`.

Spawned child appears 10–30 units from the parent; each of 6 traits mutates with p = 0.1 by ×U(0.5, 1.5), capped (speed 20, sprint 40, max_energy 1000, hearing 100, vision 400, cone π/2). No lower caps.

## Fruit and trees

- Fruit: spawns with 20 energy, +2/s until 60 (age 20), rots away at age 100. Spawns 10–60 units from a tree (`tree.radius`…`3·radius`, radius grows to 20).
- Tree spawns fruit only when `age ≥ 20`, with chance `dt · fruit_spawn_rate` per tick (forest/grassland 0.1/s, swamp 0.08/s, desert 0.05/s, river 0). Trees die once `age > 50 + 50·√U` checked every tick → effectively soon after 50–70 s. A tree yields only ~3–6 fruit in its life.
- Tree spawn chance per tick `= 100/max(1, n_trees/2) · dt · 0.5^(t/300)`, then filtered by biome `tree_spawn_rate` (forest 1, swamp 0.9, grass 0.5, desert 0.1). Halving every 300 s ⇒ tree count collapses late game (rough equilibrium `n ≈ 120·√decay`: ~60 at t=600, ~15 at 1800, ~4 at 3000). Verify in Exp 0.
- 32 free fruits + ~50–65 trees at start.

## Predators (`predator.py`)

- Spawn chance per tick `= dt · t · 1e-4 / max(1, n_pred)`, never despawn. Rough expectation `n ≈ 0.01·t` → ~30 predators by t = 3000. Verify in Exp 0.
- `speed 11`, `sprint 15`, `size 10`, `max_energy 200`, hearing 60, vision 250, cone π/3. Spawn resting with 0 energy; rest until energy > 100 (+30/s ⇒ 3.3 s), then active until energy ≤ 0. No passive drain: walking costs 0.55/tick (~18 s of wandering per 100 energy), sprinting 2.55/tick (~4 s). Eating an agent adds the agent's energy (cap 200).
- Behaviour when it perceives an agent (nearest one):
  - if agent is looking away (`|rel_dir| > π/2`) **or** distance < 90: charge at `min(15, distance)` with a turn toward the agent (max 0.3 rad/tick).
  - else (agent facing it, distance ≥ 90): pivot sideways at sprint speed (`angle ± π/4`), closing ~10.6 units/tick, trying to get behind.
- Otherwise: avoid visible edges, else wander (`turn U(−0.1, 0.1)`, move 11).
- Predators see agents through the same `observe()` — hearing 60 disc + π/3 cone up to 250, blocked by obstacles.

Implications: an agent that keeps facing a predator ≥ 90 away forces it to sprint (2.55/tick) until it collapses; walking away meanwhile (10/tick vs. its 10.6 closing) is nearly break-even and once its energy < 40 it is capped to 11 and falls behind. A charging predator (15/tick) can only be outrun by sprinting (20/tick, 5.5 energy/tick) — expensive, so avoid getting within 90 or approached from behind.

## Observations

Relative only (distance, angle in agent frame; edges as local coordinates). Everything within `hearing_radius` is sensed in all directions; beyond that only inside the vision cone and not blocked by obstacles. Agent → agent observations include `id`. No absolute position is given; dead reckoning from commanded moves is possible but drifts (biome penalty is known from `biome`, collisions are not).

## Server constraints

- 10 s timeout per request, **600 s accumulated wait per run** → budget ≈ 20 ms per tick including HTTP. Keep the policy well under 5 ms/tick.
- Evaluation = 3 consecutive games on preset seeds, averaged; the server must survive all three. Agent ids restart at 0 each game, so hivemind memory must reset when `sim_time` goes backwards.
