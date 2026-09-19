# Experiment journal

Newest entries at the bottom. Raw results live in `experiments/results/<name>.json`; reproduce any row with
`python -m experiments.run --name <name> --policy <spec> --seeds 0-9 [--kw k=v ...]`.

## 2026-09-18 — setup and baseline

- Environment: Python 3.12 venv (`.venv`), deps from `requirements.txt`. Headless run and agent server verified.
- Read the whole simulator; digest in `00-mechanics.md`. Key facts: score ≈ survival seconds; agents live ~100–170 s
  (old-age drain) so reproduction is mandatory; walking costs 5× the living cost; fruit only near mature trees.
- Built `experiments/harness.py` (parallel seeds, death-cause instrumentation, timeline sampling) and the
  `policies/` package shared with `agent_server.py`.

### Exp 0 — environment dynamics (no agents, seeds 0–4, `--starting-agents 0 --no-stop`)

Mean over 5 seeds (`python -m experiments.analyze exp0_env_dynamics`):

| t (s) | predators | active | trees | mature trees | uneaten fruit |
|---|---|---|---|---|---|
| 300 | 2.6 | 2.6 | 59.8 | 39.0 | 167.6 |
| 600 | 5.6 | 4.4 | 41.8 | 30.4 | 106.0 |
| 900 | 9.0 | 7.2 | 30.6 | 20.6 | 84.8 |
| 1200 | 12.6 | 10.4 | 19.2 | 12.6 | 55.6 |
| 1500 | 16.2 | 13.4 | 14.8 | 9.8 | 38.6 |
| 1800 | 18.8 | 16.4 | 10.0 | 7.0 | 28.8 |
| 2100 | 21.6 | 17.6 | 8.6 | 5.4 | 23.0 |
| 2400 | 24.2 | 20.2 | 5.0 | 2.6 | 13.4 |
| 2700 | 26.8 | 21.2 | 3.0 | 1.2 | 12.4 |
| 3000 | 29.4 | 25.0 | 3.2 | 2.2 | 5.8 |

Both back-of-envelope predictions in `00-mechanics.md` hold (predators ≈ 0.01·t, trees ≈ 120·√decay).
Consequences for strategy:

- **Early game (t < 900) is abundant**: >100 fruits lying around, few predators. This is the time to grow the
  population and bank energy, not to be careful.
- **Late game (t > 2000) is a desert**: ~2–5 mature trees for a 1600×1200 map, ~0.2–0.5 fruit/s total, and
  20+ active predators. A species that only camps its current tree will lose it (trees live ~50–100 s) and then
  has to *find* one of the 2–3 remaining trees with a 200-unit vision range. Late-game tree finding / tree memory
  is likely the decisive capability. Fruit does not accumulate late (5.8 uneaten at t=3000 even with no eaters).
- No agent can bridge the gap by idling: old-age drain kills every agent at ~max_age+40 s, so reproduction must
  continue through t = 3000. The minimal late-game economy is ~1.3 energy/s per lineage (25 net per spawn +
  living), i.e. one ripe fruit per ~45 s.

### Exp 1 — baseline (`policies.dummy:DummyPolicy`, seeds 0–9)

| metric | value |
|---|---|
| score mean / median / min / max | 28.0 / 28.7 / 14.5 / 43.6 |
| survival median | 28.6 s |
| deaths | 103 starved, 0 eaten |

The dummy spawns whenever it can (5 → 10 agents in the first ticks), random-walks and starves within a minute.
Predators never matter at that time scale.

### Exp 2 — camper v1 (`policies.camper:CamperPolicy`, defaults)

Smoke run (seed 0, capped at 600 s): survived to the cap, score 617, 634 fruits eaten, 47 children,
22 starved / 24 eaten. Policy cost 0.13 ms/tick.

Full run, seeds 0–9:

| metric | value |
|---|---|
| score mean / median / min / max | **832** / 871 / 412 / 1165 |
| survival median / min | 862 s / 412 s; **0 of 10 reach t = 3000** |
| deaths | 354 starved, 291 eaten (per run ≈ 35 + 29, from ≈ 60 births) |
| fruits eaten | 7035 (≈ 700 per run) |
| policy cost | 0.09 ms/tick |

30× the baseline, but every run goes extinct at t = 400–1150 — while the map still has 30–60 trees and
80–150 uneaten fruit, and only 4–11 predators. Timelines show the population pinned at the cap (8) with a
**total energy of only 1000–1500 (≈150 per agent, cap 500)**, then a decline of 1–2 agents per 10 s once
predators reach 4+.

Diagnosis:
1. *Hand-to-mouth economy.* The ripeness gate (`ripe_age = 18 s`) only fires for fruit tracked continuously;
   a moving or scanning agent loses tracks, so in practice agents eat only when `energy < hungry_energy (120)`.
   Agents at ~150 energy cannot afford one sprint escape (5.5/tick) and starve after a bad stretch. → Exp 3.
2. *Weak evasion.* Half of all deaths are predator kills. Once a charging predator is behind the agent it is
   invisible (cone π/3, hearing 50 < charge distance 90), and v1 then merely *walks* (10/tick) away from a
   15/tick charger. → v1.1: sprint while blind, then look back once and stand off.
3. Children spawn next to the parent and camp the same tree, so a predator finding the camp eats several.
   Not addressed yet.

### Exp 3 — economy ablations (seeds 0–9, v1 evasion)

| run | change vs v1 | score mean | median | min | full | starved | eaten | fruits |
|---|---|---|---|---|---|---|---|---|
| exp2 (v1) | – | 832 | 871 | 412 | 0/10 | 354 | 291 | 7035 |
| exp3a | `hungry_energy=350` | **1020** | 1010 | 656 | 0/10 | 532 | 350 | 13105 |
| exp3b | `ripe_age=0` (never wait) | 876 | 905 | 612 | 0/10 | 456 | 331 | 13921 |
| exp3c | 3a + `pop_cap=12` | 970 | 1037 | 394 | 0/10 | 813 | 472 | 15923 |

- Eating freely up to 350 doubles fruit intake and adds ~190 score. Waiting for ripeness *above* 350 is still
  worth something (3b eats slightly more fruit but scores 145 less — it eats 20-energy fruit that would have
  become 60).
- A larger population does not help on its own: more mouths at the same trees, more variance.

Death log of 3a (age at death × cause):

| cause | <30 | 30–60 | 60–90 | 90–120 | 120+ |
|---|---|---|---|---|---|
| eaten | **180** (88 energy) | 80 (130) | 56 (123) | 21 | 13 |
| starved | 65 | 59 | 86 | 112 | **210** |

- 60 % of old-age deaths (starved ≥ 90 s) are the unavoidable lifespan; that is the replacement rate the
  species must sustain (~1 birth per 12 s at pop 8).
- **Half of all predator kills are newborns** sitting next to the parent's camp; extinctions end with 3–4 kills
  within 10 s at one camp (seeds 0, 2). One tree (≈4–6 energy/s) feeds 2–3 agents, not 8: crowding causes both
  the hand-to-mouth energy and the correlated kills.

Decisions → v1.1: (a) `lookback`: sprint while the charger is behind, then turn once to look back and stand
off; (b) `crowd_max`: while camping with ≥ 2 siblings within 60, the youngest turns away from the crowd and
walks ~250 units to find its own tree.

### Exp 4 — v1.1 evasion + dispersal (seeds 0–9, all with `hungry_energy=350`)

| run | change vs 3a | mean | median | min | max | starved | eaten | fruits |
|---|---|---|---|---|---|---|---|---|
| exp3a | – | 1020 | 1010 | 656 | 1558 | 532 | 350 | 13105 |
| exp4a | `lookback` | 935 | 930 | 596 | 1255 | 473 | 364 | 12012 |
| exp4b | + `crowd_max=2` | 1034 | 945 | 611 | 1444 | 554 | 391 | 12799 |
| exp4c | + `scan_period=5` | 1060 | 1078 | 753 | 1503 | 643 | 307 | 13826 |
| exp4d | 4b + `pop_cap=12` | 971 | 896 | 702 | 1548 | 846 | 426 | 15421 |

Seed-to-seed spread is ~250, so the standard error of a 10-seed mean is ~80: none of these is a real
improvement, all still 0/10 full runs. Parameter tweaking is exhausted; I needed to see the failures.

**Diagnostics** (`experiments/kill_trace.py`, seed 0 with the 4c settings; energy accounting via
`policy.stats()`): income 69 k from fruit; spent 10 % living, 18 % spawning, 11 % walking to fruit,
**22 % predator response** (flee alone 20 % for 2.8 % of ticks), 6 % walking to trees, 2 % camping.
The economy is fine — predators are the problem. Tick-by-tick traces of the first 8 kills:

1. **Agents below 100 energy cannot sprint** (`energy < max_energy/5` caps movement to walk speed) —
   four of eight victims were at 32–94 energy, "sprinting" at 10 while a 15/tick charger closed in.
   Every newborn (75 energy) is in this state until it eats.
2. **No predator memory**: after a stand-off the predator left the cone; the agent switched to `explore`
   and walked *forward, straight into it*.
3. **Spawning under attack**: a camper at 402 energy spawned while an unseen predator was 39 away
   (scan every 5 ticks missed a 16-tick approach); parent and child died within a second.
4. A second predator arrived from behind during a stand-off; two victims fled into the river
   (movement ×0.3) or along an obstacle (collision handling slid them sideways).

→ v2 (`policies/camper2.py`): threat memory in the agent frame (sightings + sibling alarms, advanced by
own motion, assumed to keep approaching at 12/tick, 40-tick TTL); stand-off vs. remembered threats too;
escape direction chosen among 7 candidates around "away from all threats", rejecting ones blocked by a
visible edge within 45; no sprint request below the threshold; no spawning while any threat is remembered;
dispersal, sibling alarms and `scan_period=5` on by default.

v2 smoke (seed 0, 600 s): score 624, **14 eaten** (v1: 24), 996 fruits (v1: 634). Kill traces of v2:
two campers approached from behind and never seen (a cone-step scan every 5 ticks needs 30–47 ticks per
rotation; a charging predator crosses 250 units in 17); one stand-off that crept to the 90-unit charge
distance and a second predator arriving; one flight through swamp at half speed while the predator ran on
grass. → three more switches: `rotate_period` (campers rotate continuously, 2π per N ticks, 1 energy per
rotation), `sprint_zone` (in a stand-off sprint away while the threat is closer than this — a pivoting
predator closes at 10.6/tick, so sprinting while facing it gains 9.4/tick vs 5/tick once it charges), and
`avoid_camp_biomes` (never camp in swamp/river, where escape speed is ×0.5 / ×0.3).

### Exp 5 — v2 variants (seeds 0–9)

| run | config | mean | median | min | starved | eaten | spawned |
|---|---|---|---|---|---|---|---|
| exp4c (v1 best) | – | 1060 | 1078 | 753 | 643 | 307 | 900 |
| exp5a | v2 base | 941 | 800 | 654 | 565 | 220 | 735 |
| exp5b | + `rotate_period=15` | 844 | 813 | 509 | 580 | 185 | 715 |
| exp5c | + `sprint_zone=130` | 920 | 916 | 586 | 584 | **167** | 701 |
| exp5d | + `avoid_camp_biomes` | (pending) | | | | | |
| exp5e | all three | (pending) | | | | | |

Predator kills keep falling (307 → 220 → 185 → 167) and the score does not move. Timelines show the
real shape of extinction: populations sit at 8 agents / 1500–2800 energy and then go **8 → 3 → 0 within
50–100 s**. ~260 of the ~570 starvations per batch are agents younger than 90 s — not old age. The
threat logic works (fewer kills) but every encounter costs 20–60 energy (stand-off retreat or a sprint),
and blocks spawning while a threat is remembered.

Back-of-envelope harassment rate: an active predator walks 110 units/s with a ~250-wide detection swath,
i.e. it sweeps ~1.4 map-areas per 100 s; at t ≈ 800 there are ~6 active predators, so an agent in the open
is *found* roughly every 12 s. At 20–60 energy per encounter that is 2–5 energy/s per agent against a
fruit income of 2–4 energy/s. **Encounter management cannot pay for itself past t ≈ 700; encounters have
to be avoided.** Predator vision is blocked by obstacle edges and predators steer away from edges they
see, so the standing spot should matter a lot → Exp 6.

### Exp 6 — does the standing spot change the kill rate? (`experiments/hiding.py`)

One idle agent (500 energy, no ageing) per seed and spot type, predators spawned at t = 0, up to 300 s.
First pass (20 predators, 20 seeds) had a placement bug that skipped most spots near the right/bottom
walls; the surviving sample still ranked: open ≈ obstacle side (median death ~8 s) < wall (16 s) < nook
(47 s) < map corner (2 of 5 survived the full 300 s, mean alive 131 s). Rerun with the fix, 30 seeds,
12 predators (≈ the density at t = 1200):

| spot | n | survived 300 s | median death | mean alive |
|---|---|---|---|---|
| open | 30 | 0 | 9.4 s | 12.8 s |
| obstacle side | 30 | 4 | 15.7 s | 69.5 s |
| wall | 30 | 5 | 19.3 s | 89.3 s |
| nook (obstacle + wall) | 30 | 6 | 25.4 s | 96.9 s |
| map corner | 28 | 7 | 26.2 s | 99.4 s |

An idle agent in the open is found within 10 s, confirming the harassment estimate. Cover multiplies
lifetime 5–8× but a spotted agent is still eventually cornered (the predator pivots to 90 and charges).

Exp 5d/5e closed at 927 and 816: every v2 variant is in the 800–1000 band.

### Exp 7 — the obstacle dance (`experiments/dance.py`)

`Predator.step` is stateless: when line of sight breaks it forgets the agent, wanders, and edge
avoidance steers it away from the obstacle. Scripted agent at a random interior obstacle moves to the
perimeter point occluded from / farthest from the nearest predator. 30 seeds, 12 predators, 300 s:

| mode | survived | median death | mean alive | energy per 100 s |
|---|---|---|---|---|
| idle | 4/30 | 16.9 s | 69.5 s | 0 |
| cheat (knows all predator positions) | 9/30 | 180 s | 210 s | 143 |
| sensed (own observations + 40-tick memory) | 9/30 | 140 s | 195 s | 123 |
| sensed, obstacles ≥ 60 on the short side | 12/30 | 114 s | 199 s | 109 |

The dance triples lifetime and needs no information the agent does not have. Remaining deaths (traces):
predators arriving unseen from the side (the scripted agent never scans) and already inside the 60-unit
hearing disc, after which occlusion no longer matters and the 15/tick predator wins the circling contest;
two "sleeping predator woke up next to the agent" cases.

→ v3 (`policies/camper3.py`): edge memory → obstacle rectangles; camp on the obstacle side nearest the
tree (after t = 600 skip trees with no obstacle within 80); dance on threat when an obstacle is within 40,
else camper2's flee/stand-off with `sprint_zone=130`; continuous rotation scan with a time schedule
(none before 400 s, 2π/20 ticks until 1000 s, 2π/12 after); swamp/river camping avoided.

Obstacle reconstruction verified against ground truth (centre error ≤ 0.8 units, exact sizes with two
sides seen). Policy cost 2.4–6 ms/tick (edge grouping per agent per tick) — still within the 20 ms budget.

### Exp 8 — v3 in full games (seeds 0–9)

| run | config | mean | median | min | starved | eaten | fruits |
|---|---|---|---|---|---|---|---|
| exp5c (v2 + sprint zone) | – | 920 | 916 | 586 | 584 | 167 | 11744 |
| exp8a | v3 base | **718** | 645 | 294 | 439 | 291 | 10579 |
| exp8b | `require_obstacle_after=0` | (pending) | | | | | |
| exp8c | rotate always, period 15 | (pending) | | | | | |

Negative result. Kill traces of v3 (seed 0): campers charged from 250 away and only noticed at 38 (the
5-tick step scan before the rotation schedule starts); three kills in the swamp (biome avoidance did not
cover obstacle camps — fixed as opt-in `avoid_biome_obstacle_camps`); newborns; and six kills at one camp in
60 s — a predator that has eaten stays active nearby. Camping up to 80 units from the tree also puts most
fruit outside the 50-unit hearing disc (fewer fruits eaten), and a dance started inside ~60 units costs sprint
energy without saving the agent. Added as opt-in: `evacuate_ticks` (siblings that saw a just-eaten agent walk
away from the kill site) and `spawn_needs_fruit` (spawn only with fruit within hearing range; the parent yields
it for 30 ticks). Hiding is not the step change; parked.

### Pivot — directed evolution by spawn selection

Everything so far treats traits as fixed. Children mutate every trait by ×U(0.5, 1.5) with p = 0.1 each,
the hivemind observes every agent's traits, and it decides who spawns. Walk speed > 15 outpaces a sprinting
predator at 0.8 energy/tick; hearing ≥ 90 detects every predator before its charge distance; vision 400
outranges the predator's 250; max_energy up to 1000. With ~700 births per game there are many tickets.

Implemented in `Camper2Policy` (opt-in `select=True`): fitness = 2·speed/10 + hearing/50 + 0.5·vision/200 +
0.4·cone/(π/3) + 0.4·max_energy/500 + 0.5·sprint/20; the fittest living agent may spawn above
`elite_spawn_energy` (200), below-median agents only above `weak_spawn_energy` (400), spawns are granted
fittest-first when the cap binds; `pop_schedule` sets a time-dependent cap (fruit is abundant before t ≈ 600).
Harness timeline now records mean/max speed, hearing, vision. Smoke (seed 0, 900 s, cap 12→8): mean speed
10 → 11.6, best 13.6, vision 200 → 261, hearing 50 → 61 — selection works but slowly; the fast lineage died
in a camp crash at t ≈ 900.

Exp 8b (`require_obstacle_after=0`, always camp on an obstacle side when one is within 80 of the tree):
923 — back to the v2 level, so the obstacle camps themselves are not harmful; the extra kills in 8a came
from the mid-game switch. Exp 8c (rotate always) is still worse (752). v3 stays parked.

### Exp 9 — selection (seeds 0–9, camper2 + `sprint_zone=130`)

| run | config | mean | median | min | starved | eaten | spawned |
|---|---|---|---|---|---|---|---|
| exp5c (control) | – | 920 | 916 | 586 | 584 | 167 | 701 |
| exp9b | `select=true` | **752** | 743 | 385 | 495 | **136** | 581 |

Selection *works* — mean trait timeline of survivors: t = 300 speed 10.7 / hearing 54 / vision 209;
t = 600 11.6 / 61 / 229; t = 900 **16.9 / 86 / 319**; t = 1100 18.5 / 100 / 342 — and predation drops
to the lowest seen, yet the score falls: the spawn thresholds cut births (581 vs 701) and the survivors
**starve**. Starvation traces (seed 1, `--starved`):

- some agents spend 29–33 % of their life in stand-off: every predator passing within 200 triggers
  "face it and walk away" (0.5/tick, plus the walk back to the tree), whether or not it is pursuing;
- a newborn (age 14) died with `eat 0 %`: disperse → to_tree → stand-off → starved. The crowd rule sends the
  youngest away from the only fruit it knows;
- the rest are old-age deaths at 100–150 s. The replacement pipeline, not predation, fails at t ≈ 600–900.

→ camper2 opt-ins: `standoff_trend` (walk away only if the seen threat is closing or unseen; otherwise
stand and watch), `newborn_energy` (agents below it are never dispersed), `spawn_needs_fruit` + yield
(spawn only with fruit in hearing range; the parent leaves it for the child for 30 ticks), `old_always`
(old agents dump energy into a child regardless of fitness when the population is below cap).

Note on determinism: the 5c configuration reproduced exactly across processes, but the 13a configuration
gave 316.19 and 312.39 at t = 300 in two consecutive runs of the same process. The simulator iterates
Python *sets* of objects (`local_fruits`, `local_predators`, …), so observation and eating order depend on
memory addresses; any tie (two predators within merge range, two equidistant fruits) can branch a run.
Single-seed comparisons are therefore approximate; 10-seed means are the unit of evidence, and the
evaluation server (Linux) will not reproduce local runs anyway.

### Exp 10 — isolating the v2.1 options (seeds 0–9, camper2 + `sprint_zone=130`)

| run | option | mean | median | min | starved | eaten | spawned | fruits |
|---|---|---|---|---|---|---|---|---|
| exp5c (control) | – | 920 | 916 | 586 | 584 | 167 | 701 | 11744 |
| exp10a | `standoff_trend` | **972** | 873 | 712 | 595 | 193 | 738 | 11739 |
| exp10b | `newborn_energy=150` | 813 | 817 | 636 | 505 | 169 | 624 | 10443 |
| exp10c | `spawn_needs_fruit` | 836 | 827 | 462 | 474 | 181 | 605 | 11138 |
| exp10d | `select` + `old_always` | (rerunning) | | | | | | |
| exp9c/9d/9e | pop 16→10→8 (±select) | 823 / 856 / 871 | | | ~1000 | 190–330 | 1140–1340 | ~16000 |

Only the stand-off trend helps (+50, noise-level). Keeping newborns at the camp (10b) or gating spawns on
fruit at hand (10c) both *reduce* births and score. The front-loaded population (9c–e) doubles births and
fruit intake and still dies at the same time — more bodies at the same camps.

### Exp 11 — predator awareness (seeds 0–9)

The predator observation carries `rel_dir` = our bearing from the *predator's* facing, and its sensing is
a π/3 cone to 250 plus a 60 disc, so for every predator we see we know whether it can see us. `aware=true`:
threats that cannot see us are only *watched* (kept inside our cone, no walking away, 15-tick memory);
sighting/alarm entries that see us keep the full response. Smoke (seed 0, 900 s): 12–16 % of agent-ticks
became near-free "watch" ticks that used to be stand-off walking; score 834–870 vs 770 for v2 base on this
seed, but more kills (38–41 vs 17–26). Also added `disperse_richest` (the crowd member with the most
energy leaves the camp instead of the youngest; the hivemind knows all energies).

| run | config | mean | median | min | max | starved | eaten | spawned | fruits |
|---|---|---|---|---|---|---|---|---|---|
| exp5c (control) | v2 + sprint zone | 920 | 916 | 586 | 1600 | 584 | 167 | 701 | 11744 |
| exp11a | + `aware` | **1043** | 1018 | 545 | 1517 | 548 | 373 | 871 | 13061 |
| exp10d | + `select` + `old_always` | **1038** | 982 | **769** | 1580 | 717 | 168 | 835 | 12783 |
| exp11b | + `aware` + `standoff_trend` | 981 | 943 | 669 | 1590 | 523 | 342 | 815 | 12760 |
| exp12a | v1-4c + `aware` | 992 | 1023 | 526 | 1352 | 530 | 406 | 886 | 13303 |
| **exp13a** | + `aware` + `select` + `old_always` | **1111** | 1021 | **867** | 1575 | 624 | 236 | 810 | 14023 |

Awareness buys +120 through the economy (more births, more fruit) at the price of more kills; selection
with old agents always dumping energy into children buys the same +120 with the fewest kills and the best
worst case. Combined (13a) they stack: new best on mean and on the worst seed. The stand-off trend adds
nothing on top of awareness; awareness does not help v1 (v1 has no threat memory to make cheaper).
Server now serves 13a.

Where the budget goes after awareness (11a vs 5c): stand-off 29 % → 23 % of movement energy, "watch"
≈ 0, but flee 16 % → 22 % — threat response is still ~45 % of movement energy; the gain is time: 10 % of
agent-ticks moved from walking away to watching/eating, hence more births.

Autopsy of 11a: per-agent death rate 0.5 → 1.3 → 1.8 → 2.2 → 2.4 per 100 s across 300-s windows
(natural old-age rate ≈ 0.8). Every run still ends as a camp-level crash: 8 agents with 1400–1900 energy
→ 2–4 agents with ~200 within 30–40 s. Groups hover at ~175 energy per agent even while eating everything
they see, so they have no reserve when predators arrive. `camp_timeout` (leave a tree that produced no fruit
for 30 s) tried on seed 0: 942 vs 1022 without — parked.

Lifespans in 13a (860 deaths): mean age at death 87.5 s; 35 % die before 60 s. Starved 624 (56 % at
age ≥ 90 = old age; 153 before 60 = young starvation); eaten 236, **74 % of them below 100 energy (could
not sprint)**, 61 % younger than 60 s. Births ≈ deaths ≈ 30 per 300 s at 8 agents: a birth every 10 s,
10 energy/s of pure turnover; the species keeps no reserve.

### Exp 12–16 — stacking on 13a (seeds 0–9; base = `sprint_zone=130 aware select old_always`)

| run | change | mean | median | min | max | starved | eaten | spawned | fruits |
|---|---|---|---|---|---|---|---|---|---|
| exp13a | base | 1111 | 1021 | 867 | 1575 | 624 | 236 | 810 | 14023 |
| exp12b | (v1-4c + aware + alarms) | 1017 | 1078 | 567 | 1327 | 603 | 335 | 888 | 13971 |
| exp13b | + `disperse_richest` | **1138** | 1110 | 773 | 1659 | 634 | 272 | 856 | 14651 |
| exp14a | + pop 12 until t=600, then 8 | **1202** | 1173 | 638 | 1747 | 993 | 308 | 1251 | 17983 |
| exp16a | + `spawn_needs_fruit` | 1031 | 1059 | 589 | 1572 | 571 | 223 | 744 | 12974 |
| exp15a | + `spawn_energy=400` | 1136 | 1087 | 777 | 1603 | 662 | 259 | 871 | 14159 |
| exp15b | + `pop_cap=6` | 947 | 946 | 526 | 1510 | 386 | 170 | 506 | 10335 |
| exp16b | + fitness weights hearing 1.5 / max_energy 0 / sprint 0.3 | 1010 | 986 | 356 | 1568 | 566 | 209 | 725 | 12941 |
| exp14b | + `hungry_energy=250` | 1092 | 1045 | 740 | 1947 | 608 | 213 | 771 | 12340 |
| exp14c/d, 15c, 17a/b/c | elite 150 / camp timeout / pop 6+400 / 14a+richest schedules | stopped before finishing (2026-09-19) | | | | | | | |

Noise calibration: exp10d was accidentally run twice with identical settings and gave 10-seed means of
1038 and 959. Differences below ~100 between configurations are not evidence.

"Fewer, richer" (pop 6) is clearly worse: bodies matter more than reserves. Dropping `max_energy` from the
fitness function hurts, so capacity is worth selecting for despite the higher sprint gate.

Serving: `policies/presets.py` names the configurations worth serving; `agent_server.py --preset NAME`
(or `--policy spec --kw k=v`) selects one, `GET /` reports it. See `docs/02-serving.md`.

With awareness and selection keeping the economy alive, a front-loaded population now pays (+90) — more
bodies early when fruit is abundant and more mutation tickets — at the cost of a worse floor. Richest-leaves
adds a little. Spawn-only-with-fruit is out for good. → Exp 17 stacks 14a + richest with three schedules.

## 2026-09-19 — platform validation runs (preset 14a, server on Azure Sweden Central)

| attempt | score | errors | what happened |
|---|---|---|---|
| 01:08 UTC | 1024.7 | "accumulated wait time for agent exceeded 600 seconds" | species alive at t ≈ 1025 when the platform stopped the game |
| 01:46 UTC | 720.4 | none | extinction at t ≈ 720 (inside the local 14a range, min 638) |

Server-side timing during the second run (nginx `$request_time`, 1500 requests): p50 3 ms, p99 5 ms.
Platform-side rate: 14.9 requests/s ⇒ **67 ms per tick**, i.e. ~60 ms of network per request. The platform
host is Hetzner Helsinki (46.62.240.126); TCP connect from the Azure VM is a stable 50 ms, from a Stockholm
laptop 12 ms. Budget for a full game is 20 ms/tick, so any run that survives past t ≈ 1000 is cut off from
this VM — exactly the runs that score. Conclusion: the endpoint must run near Helsinki (Hetzner hel1 is the
platform's own datacenter). `deploy/install.sh` installs the service on a fresh Ubuntu host in one command.

## 2026-09-19 — autonomous development session

Rule from here on: decisions on ≥ 20 seeds, and new seeds (10–29) so that seeds 0–9 do not get overfitted.

### Exp 18 — baselines on seeds 10–29

| run | config | mean | median | min | max |
|---|---|---|---|---|---|
| exp18a | 13a | **1100** | 1149 | 739 | 1375 |
| exp18b | 14a (pop 12 until 600) | 1004 | 1033 | 419 | 1467 |
| exp18c | 14a + richest | (pending) | | | |

14a's 1202 on seeds 0–9 was seed luck: over all 30 seeds 13a ≈ 1104 with a much better floor. 13a is the
base again and the served default.

Late-game kill traces of 14a (seed 12): three siblings born within seconds of each other, all in the swamp,
eaten in the same second while "sprinting" at an effective 9/tick; an agent in `watch` staring at one harmless
predator while another approached unseen from behind, then zigzagging between the two (the away-vector flips
each tick). → options: `watch_scan` (keep scanning while watching), `escape_minmax` + `escape_hysteresis`
(direction maximising the minimum distance to all threats, sticky), `spawn_cooldown` (ticks between two spawns
of one parent), `tree_memory` (walk to the nearest remembered tree when the current one is lost), and the
existing `avoid_camp_biomes`. Exp 19 tests each on 13a, seeds 10–29.

### World model (infrastructure, `policies/worldmodel.py`)

Dead-reckoned pose per agent in shared frames: children initialised from the parent's observation of them,
founder frames merged on first mutual sighting (5 → 1 frame by t ≈ 160 on seed 3), drift split between the
two agents of every sighting. Accuracy test against true positions: pairwise distance error < 2 units until
t ≈ 200, then median 50 and outliers of 500+. Cause (per-tick vector error by branch): the simulator keeps
the commanded distance on collision and only rotates the direction, and **28–34 % of stand-off/flee ticks
are collisions** — agents retreat backwards, facing the predator, into obstacles they never saw. Camp/eat/
to_tree are exact. A 60-tick edge memory (`edge_memory`) does not reduce this (the obstacles were never in
view). Left as infrastructure; not used by any policy yet.

### Exp 19 — single options on 13a (seeds 10–29)

| run | option | mean | median | min | max | starved | eaten | spawned |
|---|---|---|---|---|---|---|---|---|
| exp18a | 13a | **1100** | 1149 | 739 | 1375 | 1268 | 553 | 1721 |
| exp18c | 14a + richest | 1065 | 1018 | 742 | 1576 | 1688 | 686 | 2274 |
| exp19a | `avoid_camp_biomes` swamp/river | 931 | 977 | 577 | 1164 | 1232 | 426 | 1558 |
| exp19b | `watch_scan` | 964 | 964 | 420 | 1429 | 1110 | 543 | 1553 |
| exp19c | `escape_minmax` + hysteresis 0.8 | 1048 | 1008 | 692 | 1456 | 1212 | 589 | 1701 |
| exp19d | `spawn_cooldown=100` | 1035 | 1036 | 536 | 1425 | 1232 | 495 | 1627 |
| exp19e | `tree_memory` | 926 | 950 | 287 | 1219 | 1049 | 443 | 1392 |
| exp19f | 13b (`disperse_richest`) | 910 | 941 | 413 | 1507 | 1020 | 434 | 1354 |

Six of six below the baseline (SE ≈ 55): 13a is a local optimum for single switches. Swamp trees are
worth keeping despite the escape penalty; staring at a harmless predator beats scanning; walking to
remembered trees loses (trees die within its memory horizon and dead reckoning drifts in stand-offs);
13b's earlier 1138 was seed noise.

Life composition on 13a (seeds 11, 13): young starvers (15 % of deaths) live **26 s, eat 1 fruit**, spend
42 % of their ticks in explore/disperse/to_tree — they never learn where the food is. Eaten agents live
46 s (9 fruits); old-age deaths 122 s (23 fruits). About half of all births never become productive.
→ `inherit`: the parent sees its newborn (distance, angle, facing), so the hivemind transforms the parent's
tree, fruit and threat memory into the child's frame at birth (transform verified exact). Exp 22a.

### Exp 20–22 — spacing, inheritance (seeds 10–29, base 13a = 1100 / min 739)

| run | option | mean | median | min | max | starved | eaten | spawned |
|---|---|---|---|---|---|---|---|---|
| **exp20a** | `crowd_max=1` (≤ 2 agents per camp) | **1138** | 1119 | **856** | 1472 | 1449 | 509 | 1858 |
| exp20b | `crowd_dist=100` | 943 | 872 | 498 | 1504 | 1096 | 492 | 1488 |
| exp20c | `disperse_ticks=50` | (pending) | | | | | | |
| exp22a | `inherit` (newborn gets parent's memory) | 1083 | 1084 | 593 | 1564 | 1272 | 574 | 1746 |

Fewer agents per camp is the first change with a better mean and a much better floor; a wider trigger radius
is harmful (too much wandering). Inheriting the parent's map does not rescue the young — their starvation is
about barren camps rather than ignorance. Exp 23 re-tests `crowd_max=1` against 13a on seeds 30–49.

### Exp 21 and noise calibration (seeds 10–29)

| run | option | mean | median | min | max | spawned |
|---|---|---|---|---|---|---|
| exp18a / exp18a2 | 13a, two independent draws | 1100 / **1098** | 1149 / 1154 | 739 / 739 | 1375 / 1325 | 1721 / 1752 |
| exp20c | `disperse_ticks=50` | 1095 | 1066 | 835 | 1377 | 1813 |
| exp21a | `old_no_eat_age=105` | 1017 | 1047 | 655 | 1398 | 1650 |
| exp21b | fitness ≈ speed only | 1077 | 1074 | 801 | 1554 | 1757 |
| exp21c | `elite_spawn_energy=150` | (pending) | | | | |

Two independent 20-seed draws of 13a differ by 2 points (per-seed results mostly repeat; only a few seeds
branch), so 20-seed means are reliable to ~±20 and `crowd_max=1` (+38, floor +117) is probably real.
Old agents must keep eating — they are the elite spawners (births 1650 vs 1721 when they stop).

### Exp 23 — paired confirmation on seeds 30–49, and what the noise really is

| run | config | mean | median | min | max |
|---|---|---|---|---|---|
| exp23b | 13a | 1067 | 1081 | 623 | 1721 |
| exp23a | 13a + `crowd_max=1` | 1048 | 1021 | 662 | 1529 |
| exp21c | 13a + `elite_spawn_energy=150` (seeds 10–29) | 977 | 964 | 538 | 1421 |

Per-seed paired difference (crowd1 − 13a): mean −19, 10 wins of 20, SD 260. The +38 of Exp 20a was noise.
Calibration: re-running one configuration reproduces its per-seed scores almost exactly (the simulator is
nearly deterministic per seed), but the *difference between two configurations* has a per-seed SD of ~260,
so a 20-seed comparison resolves only effects of ~±120 and a +50 change would need ~100 seeds. Every
single-switch or single-knob change tried in Exp 19–23 is inside that band or clearly negative.

State of the policy after this session: **13a** (`Camper2Policy(sprint_zone=130, aware=True, select=True,
old_always=True)`), ≈ 1100 on seeds 10–29, 1067 on 30–49, 1111 on 0–9. Random search over the numeric
knobs (`experiments/search.py`, `search_s1`) is running; results in `experiments/results/search_s1.csv`.

Why the ceiling is ~1100–1300: at t ≈ 1000–1300 (10–13 predators) the per-agent death rate is ~2 per
100 s against an old-age floor of ~0.8; replacing that needs ~18 energy/s in births at 8 agents while the
4–8 trees a group occupies yield 16–32 energy/s before living (8/s) and movement (~15/s). The economy
cannot fund the death rate. Getting past it needs either far fewer predator-induced deaths (hiding, tested
negative as implemented) or coordinated use of the whole map's trees (world model, built but unused).

### The resource left on the table (seed 31, 13a, instrumented)

Crowding is not the crash mechanism: largest cluster ≈ 2.3 agents, median nearest-sibling distance
140–190 units, correlation of clustering with survival 0.0 (Exp 23b). The population declines *gradually*
from t ≈ 600 (7.2 → 6.3 → 5.6 → 4.6 → 3.0 agents per 200-s window): births < deaths.

Where the food is: **only 5–13 % of the fruit on the map is within 100 units of any agent**; 70–100
fruits (3–4 k energy) stand uneaten at unattended trees and rot after 100 s (≈ 0.8 fruit/s lost, against
1.24 fruit/s eaten — the species captures ~60 % of the map's production). 76 % of camping ticks (97 % after
t = 600) have no fruit within 60 units: a camper lives off its own tree's 0.1 fruit/s while unattended mature
trees hold piles of 5–10 ripe fruits (200–400 energy) for whoever walks 300 units (15 energy).
→ `tree_choice="fruit"` (target the visible tree with the most fruit around it, re-target when a richer
one is in view) and `camp_timeout` (leave a camp that has shown no fruit for 40 s). Exp 24, seeds 10–29.

### Exp 24 and the treadmill (seeds 10–29)

| run | option | mean | median | min | fruits | energy/fruit | intake energy/s |
|---|---|---|---|---|---|---|---|
| exp18a | 13a | 1100 | 1149 | 739 | 27334 | 42.3 | 54.1 |
| exp24a | `tree_choice=fruit` | 988 | 889 | 683 | 26574 | 42.2 | 58.6 |
| exp24b | `camp_timeout=400` | 1076 | 1103 | 690 | 27772 | 42.5 | 56.6 |
| exp24c / 24d | both / fruit choice with switch margin 2 | (pending) | | | | | |
| exp3b (old) | never wait for ripeness | 876 | | | | 40.2 | 65.4 |

Higher intake does not buy survival (24a +8 % energy/s, −110 score; 3b +20 %, −220). Death and birth
rates per 100 s are the same in every configuration: births 8.0–8.3, deaths 8.5–8.8, of which
eaten < 40 s ≈ 1.2–1.5, starved < 40 s ≈ 1.2–1.6, starved ≥ 90 s ≈ 3.2 (old age). `inherit` did not
change young starvation (1.32 vs 1.29). The population cap makes this a treadmill: each death frees a
slot, a 75-energy child fills it, one child in three dies within 40 s at a cost of 100 energy, and the
species' fate is decided by whether a bad stretch (several kills in one window) empties the slots faster
than 300-energy parents can refill them. Single-switch changes redistribute the same turnover.

Directions that could break the treadmill (not done in this session):
1. **Global coordination** with the world model (`policies/worldmodel.py`): send dispersers to the
   regions of dead lineages / unattended fruit-rich trees instead of 250 units in a random direction;
   keep ≥ 4 independent camps alive so one bad window cannot take the species.
2. **Nomadic harvesting** of the 40 % of production that rots: agents that leave a camp only when a
   richer visible tree exists (24d tests a switch margin) or move in a planned circuit between remembered
   trees (needs the world model to avoid dead-reckoning drift).
3. **Decoys**: predators chase the nearest agent; an old (post-max_age) agent stepping toward a predator
   that threatens a young one buys the young agent's life for an energy the old one was about to lose.
