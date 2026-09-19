"""v2 hivemind: tree camper with threat memory.

Differences from v1 (policies/camper.py), each motivated by kill traces (docs/journal.md, Exp 4):
  * threat memory: every predator sighting (own or shared by a sibling) is kept in the agent's
    local frame, advanced by the agent's own motion and assumed to keep approaching, so a
    predator that leaves the cone is still walked away from and faced;
  * the escape direction is chosen among candidates around "away from all threats", rejecting
    ones that run into a visible edge;
  * stand-off (face it, walk away) is used whenever the nearest threat is beyond charge_dist,
    sprinting only while it is closer; agents below the sprint threshold (energy < max/5) never
    request a sprint;
  * no spawning while any threat is remembered;
  * crowd dispersal and sibling alarms on by default.
Frame convention: x forward, y left, angle = atan2(y, x).
"""
import math

BIOME_PENALTY = {"forest": 1.0, "grassland": 1.0, "swamp": 0.5, "desert": 0.8, "river": 0.3}


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _closest_point_on_segment(p, q):
    (x1, y1), (x2, y2) = p, q
    dx, dy = x2 - x1, y2 - y1
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / den))
    return x1 + t * dx, y1 + t * dy


def _rotate(x, y, a):
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


class Camper2Policy:
    def __init__(self, charge_dist=95.0, camp_dist=15.0, scan_period=5, ripe_age=18.0,
                 hungry_energy=350.0, spawn_energy=300.0, pop_cap=8, old_age=70.0,
                 old_spawn_energy=110.0, edge_margin=35.0, target_ttl=40,
                 crowd_max=2, crowd_dist=60.0, disperse_ticks=25,
                 share_alarm=True, alarm_dist=220.0,
                 threat_ttl=40, threat_approach=12.0, threat_merge=60.0, edge_clear=45.0,
                 standoff_speed=1.0, rotate_period=0, sprint_zone=0.0, avoid_camp_biomes=(),
                 select=False, pop_schedule=None, elite_spawn_energy=200.0, weak_spawn_energy=400.0,
                 standoff_trend=False, newborn_energy=0.0, spawn_needs_fruit=False, yield_ticks=30,
                 old_always=False, aware=False, pred_cone=1.0472, pred_vision=250.0, pred_hearing=60.0,
                 watch_ttl=15, disperse_richest=False, camp_timeout=0, fitness_weights=None,
                 watch_scan=False, escape_minmax=False, escape_hysteresis=0.0, spawn_cooldown=0,
                 tree_memory=False, tree_mem_ttl=900, tree_max_age=800, edge_memory=0, old_no_eat_age=0.0,
                 inherit=False, tree_choice="nearest", tree_fruit_radius=70.0, tree_switch_margin=0):
        self.tree_switch_margin = tree_switch_margin  # with tree_choice fruit: switch only for >= this many more fruits
        # tree_choice "fruit": target the visible tree with the most tracked fruit around it (minus a
        # distance term) instead of the nearest one; unattended trees accumulate 5-10 ripe fruits
        self.tree_choice = tree_choice
        self.tree_fruit_radius = tree_fruit_radius
        # inherit: a newborn receives its parent's memory (tree, fruit, threats) transformed into its own frame
        self.inherit = inherit
        self.last_spawners = []
        # old_no_eat_age > 0: agents older than this leave fruit to the young (their drain is 0.01*age per tick)
        self.old_no_eat_age = old_no_eat_age
        # edge_memory > 0: remember visible edges for this many ticks (advanced by own motion) so that
        # a retreat away from a predator does not back into an obstacle the agent no longer sees
        self.edge_memory = edge_memory
        self.watch_scan = watch_scan            # keep the camp scan going while watching a harmless predator
        self.escape_minmax = escape_minmax      # escape direction maximises the min distance from all threats
        self.escape_hysteresis = escape_hysteresis  # keep last escape direction if the new one is within this angle
        self.spawn_cooldown = spawn_cooldown    # ticks between two spawns of the same agent
        # tree_memory: remember every tree seen (dead-reckoned in the agent frame); when the current tree
        # is lost, walk to the nearest remembered one instead of exploring blind
        self.tree_memory = tree_memory
        self.tree_mem_ttl = tree_mem_ttl
        self.tree_max_age = tree_max_age
        # trait weights for spawn selection; defaults favour walking speed, then hearing
        self.fitness_weights = dict(speed=2.0, hearing=1.0, vision=0.5, cone=0.4, max_energy=0.4, sprint=0.5)
        if fitness_weights:
            self.fitness_weights.update(fitness_weights)
        self.camp_timeout = camp_timeout        # >0: leave a camp after this many ticks without any fruit seen
        self.camp_biome = {}                    # diagnostics: camping ticks per biome
        self.disperse_richest = disperse_richest  # the crowd member with most energy leaves, not the youngest
        self.energies = {}
        # aware: use the predator's relative looking direction to tell whether it can see us;
        # predators that cannot are only watched (no walking away)
        self.aware = aware
        self.pred_cone = pred_cone
        self.pred_vision = pred_vision
        self.pred_hearing = pred_hearing
        self.watch_ttl = watch_ttl              # memory of a predator that did not see us
        self.standoff_trend = standoff_trend    # stand-off walks only if the seen threat is closing
        self.newborn_energy = newborn_energy    # agents below this energy are never sent to disperse
        self.spawn_needs_fruit = spawn_needs_fruit  # spawn only with a tracked fruit within hearing range
        self.yield_ticks = yield_ticks          # parent ignores fruit this long after spawning
        self.old_always = old_always            # old agents spawn whatever their fitness when below cap
        # select: fitness-based spawn selection (who reproduces is the hivemind's choice, and traits mutate)
        self.select = select
        self.pop_schedule = sorted(pop_schedule) if pop_schedule else None  # [(sim_time, pop_cap), ...]
        self.elite_spawn_energy = elite_spawn_energy  # fittest living agent may spawn above this energy
        self.weak_spawn_energy = weak_spawn_energy    # below-median agents only above this energy
        self.rotate_period = rotate_period      # >0: camping agents rotate 2*pi per this many ticks
        self.sprint_zone = sprint_zone          # stand-off: sprint away while the threat is closer than this
        self.avoid_camp_biomes = set(avoid_camp_biomes)  # do not camp trees standing in these biomes
        self.charge_dist = charge_dist
        self.camp_dist = camp_dist
        self.scan_period = scan_period
        self.ripe_age = ripe_age
        self.hungry_energy = hungry_energy
        self.spawn_energy = spawn_energy
        self.pop_cap = pop_cap
        self.old_age = old_age
        self.old_spawn_energy = old_spawn_energy
        self.edge_margin = edge_margin
        self.target_ttl = target_ttl
        self.crowd_max = crowd_max
        self.crowd_dist = crowd_dist
        self.disperse_ticks = disperse_ticks
        self.share_alarm = share_alarm
        self.alarm_dist = alarm_dist
        self.threat_ttl = threat_ttl          # ticks a remembered predator is kept after last sighting
        self.threat_approach = threat_approach  # assumed closing speed of an unseen predator (units/tick)
        self.threat_merge = threat_merge
        self.edge_clear = edge_clear
        self.standoff_speed = standoff_speed
        self.mem = {}
        self.tick = 0
        self.last_time = -1.0
        self.branch_ticks = {}
        self.branch_energy = {}

    # ------------------------------------------------------------------ bookkeeping
    def _reset(self):
        self.mem = {}
        self.tick = 0

    def _get_mem(self, agent_id):
        m = self.mem.get(agent_id)
        if m is None:
            m = {"tree": None, "tree_age": 0, "threats": [], "disperse": 0, "fruits": [],
                 "last_action": None, "penalty": 1.0, "scan": 0, "branch": "?", "yield": 0,
                 "closing": False, "last_fruit": 0, "trees": [], "esc": None, "last_spawn": -10**9,
                 "edges": []}
            self.mem[agent_id] = m
        return m

    @staticmethod
    def _advance(points, action, penalty):
        """Move local-frame points by the inverse of our own motion (move, then turn)."""
        if action is None or not points:
            return points
        move, mdir, turn = action
        mx, my = move * penalty * math.cos(mdir), move * penalty * math.sin(mdir)
        out = []
        for (x, y, *rest) in points:
            rx, ry = _rotate(x - mx, y - my, -turn)
            out.append((rx, ry, *rest))
        return out

    def _account(self, branch, move, turn, speed):
        cost = min(move, speed) * 0.05 + max(0.0, move - speed) * 0.5 + min(math.pi, abs(turn)) / (2 * math.pi)
        self.branch_ticks[branch] = self.branch_ticks.get(branch, 0) + 1
        self.branch_energy[branch] = self.branch_energy.get(branch, 0.0) + cost

    def stats(self):
        return {"branch_ticks": dict(self.branch_ticks),
                "branch_energy": {k: round(v, 1) for k, v in self.branch_energy.items()},
                "camp_biome": dict(self.camp_biome)}

    # ------------------------------------------------------------------ main
    def act(self, step):
        sim_time = step.get("sim_time", 0.0)
        if sim_time < self.last_time:
            self._reset()
        self.last_time = sim_time
        self.tick += 1
        statuses = step["agent_status"]
        alive = {a["agent_id"] for a in statuses}
        for dead in [k for k in self.mem if k not in alive]:
            del self.mem[dead]

        if self.share_alarm:
            self._share_alarms(statuses)
        self.energies = {a["agent_id"]: a["energy"] for a in statuses}
        if self.inherit:
            self._inherit_memory(statuses)

        pop_cap = self.pop_cap
        if self.pop_schedule:
            for t, cap in self.pop_schedule:
                if sim_time >= t:
                    pop_cap = cap
        spawns_left = max(0, pop_cap - len(statuses))
        fitness = {a["agent_id"]: self.fitness(a) for a in statuses} if self.select else None
        if fitness:
            ranked = sorted(fitness.values())
            median = ranked[len(ranked) // 2]
            best = ranked[-1]
        decided = []
        for obs in statuses:
            (move, mdir, turn), wants_spawn = self._decide(obs)
            if fitness and wants_spawn is not None:
                f, e = fitness[obs["agent_id"]], obs["energy"]
                threat_free = not self.mem[obs["agent_id"]]["threats"]
                old_dump = self.old_always and obs["age"] > self.old_age and e > self.old_spawn_energy
                if f >= best - 1e-9:
                    wants_spawn = threat_free and (e > self.elite_spawn_energy or old_dump)
                elif f < median:
                    wants_spawn = threat_free and (e > self.weak_spawn_energy or old_dump)
            decided.append((obs, (move, mdir, turn), wants_spawn))
        # fittest candidates spawn first when the cap binds
        order = sorted(range(len(decided)), key=lambda i: -(fitness[decided[i][0]["agent_id"]] if fitness else 0))
        spawn_flags = [False] * len(decided)
        for i in order:
            if decided[i][2] and spawns_left > 0:
                spawn_flags[i] = True
                spawns_left -= 1
        actions = []
        for i, (obs, (move, mdir, turn), _) in enumerate(decided):
            actions.append({"agent_id": obs["agent_id"], "move_distance": move,
                            "move_direction": mdir, "turn_angle": turn, "spawn_agent": spawn_flags[i]})
            if spawn_flags[i]:
                self.mem[obs["agent_id"]]["yield"] = self.yield_ticks
                self.mem[obs["agent_id"]]["last_spawn"] = self.tick
        self.last_spawners = [obs["agent_id"] for i, (obs, _, _) in enumerate(decided) if spawn_flags[i]]
        return actions

    def fitness(self, a):
        """Trait score: walking speed dominates (a walker faster than 15 outpaces a sprinting predator),
        then hearing (predators charge from 90), vision range/cone, energy capacity, sprint."""
        w = self.fitness_weights
        return (w["speed"] * a["speed"] / 10 + w["hearing"] * a["hearing_radius"] / 50
                + w["vision"] * a["vision_range"] / 200 + w["cone"] * a["vision_angle"] / 1.0472
                + w["max_energy"] * a["max_energy"] / 500 + w["sprint"] * a["sprint_speed"] / 20)

    def _inherit_memory(self, statuses):
        """New agents get the memory of the parent that sees them, expressed in their own frame."""
        by_id = {s["agent_id"]: s for s in statuses}
        new_ids = [a for a in by_id if a not in self.mem]
        if not new_ids:
            return
        for parent in self.last_spawners:
            ps = by_id.get(parent)
            pm = self.mem.get(parent)
            if ps is None or pm is None:
                continue
            for o in ps["observations"]:
                if o["type"] != "Agent" or o.get("id") not in new_ids:
                    continue
                child = self._get_mem(o["id"])
                bx, by = o["distance"] * math.cos(o["angle"]), o["distance"] * math.sin(o["angle"])
                rot = -(math.pi - o["rel_dir"] + o["angle"])
                def tf(pt):
                    x, y = _rotate(pt[0] - bx, pt[1] - by, rot)
                    return (x, y, *pt[2:])
                if pm["tree"] is not None:
                    child["tree"], child["tree_age"] = tf(pm["tree"])[:2], 0
                child["fruits"] = [tf(f) for f in pm["fruits"]]
                child["threats"] = [tf(t) for t in pm["threats"]]
                if self.tree_memory:
                    child["trees"] = [tf(t) for t in pm["trees"]]
                new_ids.remove(o["id"])

    def _share_alarms(self, statuses):
        """Report each predator sighting to every sibling the observer can see, in that sibling's frame.
        With B seen at (d, theta) and rel_dir = B's bearing of A: B.dir - A.dir = pi - rel_dir + theta."""
        by_id = {s["agent_id"]: s for s in statuses}
        alarms = {}
        for a in statuses:
            preds = [o for o in a["observations"] if o["type"] == "Predator" and not o.get("virtual")]
            if not preds:
                continue
            for s in a["observations"]:
                if s["type"] != "Agent" or s["id"] not in by_id:
                    continue
                bx, by = s["distance"] * math.cos(s["angle"]), s["distance"] * math.sin(s["angle"])
                rot = -(math.pi - s["rel_dir"] + s["angle"])
                for p in preds:
                    px, py = p["distance"] * math.cos(p["angle"]) - bx, p["distance"] * math.sin(p["angle"]) - by
                    qx, qy = _rotate(px, py, rot)
                    d = math.hypot(qx, qy)
                    if d <= self.alarm_dist:
                        alarms.setdefault(s["id"], []).append((d, math.atan2(qy, qx)))
        for target, seen in alarms.items():
            obs_list = by_id[target]["observations"]
            for d, ang in seen:
                obs_list.append({"type": "Predator", "distance": d, "angle": ang, "rel_dir": 0.0, "virtual": True})

    # ------------------------------------------------------------------ per agent
    def _decide(self, obs):
        m = self._get_mem(obs["agent_id"])
        energy, speed, sprint = obs["energy"], obs["speed"], obs["sprint_speed"]
        hearing, cone, max_energy = obs["hearing_radius"], obs["vision_angle"], obs["max_energy"]
        penalty = BIOME_PENALTY.get(obs["biome"], 1.0)

        # ---- advance memory by last tick's own motion
        if m["tree"] is not None:
            m["tree"] = self._advance([m["tree"]], m["last_action"], m["penalty"])[0]
            m["tree_age"] += 1
            if m["tree_age"] > self.target_ttl:
                m["tree"] = None
        m["fruits"] = self._advance(m["fruits"], m["last_action"], m["penalty"])
        m["threats"] = self._advance(m["threats"], m["last_action"], m["penalty"])
        if self.tree_memory:
            m["trees"] = self._advance(m["trees"], m["last_action"], m["penalty"])
        if m["esc"] is not None and m["last_action"] is not None:
            m["esc"] = _wrap(m["esc"] - m["last_action"][2])

        preds, fruits, trees, edges, siblings = [], [], [], [], []
        for o in obs["observations"]:
            t = o["type"]
            if t == "Predator":
                preds.append(o)
            elif t == "Fruit":
                fruits.append(o)
            elif t == "Tree":
                trees.append(o)
            elif t == "Edge":
                edges.append(o["coords"])
            elif t == "Agent":
                siblings.append(o)
        if self.edge_memory:
            edges = self._remember_edges(m, edges)

        # ---- threat memory: unseen threats keep approaching, sightings replace nearby entries
        threats = []
        for (x, y, ttl, *rest) in m["threats"]:
            d0 = rest[0] if rest else math.hypot(x, y)
            sees = rest[1] if len(rest) > 1 else True
            d = math.hypot(x, y)
            if d > 5.0 and sees:  # only a predator that saw us is assumed to keep approaching
                f = max(0.0, d - self.threat_approach) / d
                x, y = x * f, y * f
            if ttl > 1:
                threats.append([x, y, ttl - 1, d0, sees])
        closing = False
        for p in preds:
            px, py = p["distance"] * math.cos(p["angle"]), p["distance"] * math.sin(p["angle"])
            if not self.aware:
                sees = True
            elif p.get("virtual"):
                sees = p["distance"] < 100.0
            else:
                sees = p["distance"] <= self.pred_hearing or \
                    (p["distance"] <= self.pred_vision and abs(p["rel_dir"]) <= self.pred_cone / 2)
            ttl = self.threat_ttl if sees else self.watch_ttl
            merged = False
            for th in threats:
                if math.hypot(th[0] - px, th[1] - py) < self.threat_merge:
                    # th holds last tick's position already advanced by our motion and by the assumed
                    # approach; compare against the raw remembered distance instead
                    if math.hypot(px, py) < th[3] - 2.0:
                        closing = True
                    th[0], th[1], th[2], th[3], th[4] = px, py, ttl, math.hypot(px, py), sees
                    merged = True
                    break
            if not merged:
                threats.append([px, py, ttl, math.hypot(px, py), sees])
                closing = True  # new sighting: be careful
        m["closing"] = closing or not preds  # unseen (remembered only) threats count as closing
        m["threats"] = [tuple(t) for t in threats]

        # ---- fruit tracking (first-seen tick for ripeness)
        new_fruits = []
        for f in fruits:
            fx, fy = f["distance"] * math.cos(f["angle"]), f["distance"] * math.sin(f["angle"])
            best, best_d = None, 6.0
            for (x, y, seen) in m["fruits"]:
                d = math.hypot(x - fx, y - fy)
                if d < best_d:
                    best, best_d = seen, d
            new_fruits.append((fx, fy, self.tick if best is None else best))
        m["fruits"] = new_fruits
        if new_fruits:
            m["last_fruit"] = self.tick

        if self.tree_memory:
            self._update_tree_memory(m, trees, hearing)
        if trees:
            if self.tree_choice == "fruit" and len(trees) > 1:
                def tree_score(o):
                    tx, ty = o["distance"] * math.cos(o["angle"]), o["distance"] * math.sin(o["angle"])
                    n = sum(1 for (fx, fy, _) in m["fruits"] if math.hypot(fx - tx, fy - ty) < self.tree_fruit_radius)
                    return n - o["distance"] / 150.0
                tr = max(trees, key=tree_score)
                if self.tree_switch_margin and m["tree"] is not None:
                    # stick with the current target unless the best visible tree is clearly richer
                    cur = min(trees, key=lambda o: math.hypot(o["distance"] * math.cos(o["angle"]) - m["tree"][0],
                                                          o["distance"] * math.sin(o["angle"]) - m["tree"][1]))
                    if math.hypot(cur["distance"] * math.cos(cur["angle"]) - m["tree"][0],
                                  cur["distance"] * math.sin(cur["angle"]) - m["tree"][1]) < 30 and \
                       tree_score(tr) - tree_score(cur) < self.tree_switch_margin:
                        tr = cur
            else:
                tr = min(trees, key=lambda o: o["distance"])
            m["tree"] = (tr["distance"] * math.cos(tr["angle"]), tr["distance"] * math.sin(tr["angle"]))
            m["tree_age"] = 0
        elif self.tree_memory and m["tree"] is None and m["disperse"] == 0 and m["trees"]:
            tx, ty, *_ = min(m["trees"], key=lambda t: math.hypot(t[0], t[1]))
            m["tree"], m["tree_age"] = (tx, ty), -int(math.hypot(tx, ty) / 8)

        move, mdir, turn = 0.0, 0.0, 0.0
        old = obs["age"] > self.old_age
        wants_spawn = not threats and ((energy > self.spawn_energy) or (old and energy > self.old_spawn_energy))
        if wants_spawn and self.spawn_cooldown and self.tick - m["last_spawn"] < self.spawn_cooldown:
            wants_spawn = False
        if wants_spawn and self.spawn_needs_fruit:
            wants_spawn = any(math.hypot(f[0], f[1]) < hearing for f in m["fruits"])
        if m["yield"] > 0:
            m["yield"] -= 1

        active = [t for t in threats if t[4]] if self.aware else threats
        if threats and not active:
            # watched: a predator nearby that cannot see us. Keep it inside our cone cheaply.
            nearest = min(threats, key=lambda t: math.hypot(t[0], t[1]))
            nang = math.atan2(nearest[1], nearest[0])
            if self.watch_scan:
                turn = self._scan(m, cone)
            elif abs(nang) > cone / 2 - 0.15 and math.hypot(nearest[0], nearest[1]) < 150:
                turn = nang
            m["branch"] = "watch"
        elif threats:
            threats = active
            nearest = min(threats, key=lambda t: math.hypot(t[0], t[1]))
            nd, nang = math.hypot(nearest[0], nearest[1]), math.atan2(nearest[1], nearest[0])
            ax = ay = 0.0
            for (x, y, *_) in threats:
                d = max(1.0, math.hypot(x, y))
                ax -= x / d / d
                ay -= y / d / d
            away = math.atan2(ay, ax)
            if self.escape_minmax:
                away = self._minmax_direction(threats, away, speed)
            if self.escape_hysteresis and m["esc"] is not None and abs(_wrap(away - m["esc"])) < self.escape_hysteresis:
                away = m["esc"]
            mdir = self._clear_direction(away, edges)
            m["esc"] = mdir
            if nd < self.charge_dist:
                can_sprint = energy >= max_energy / 5
                move = sprint if can_sprint else speed
                m["branch"] = "flee"
            else:
                move = speed * self.standoff_speed
                if nd < self.sprint_zone and energy >= max_energy / 5:
                    move = sprint
                if self.standoff_trend and not m["closing"] and nd >= self.sprint_zone:
                    move = 0.0  # passing by: watch it, do not run
                if abs(nang) > 0.05:
                    turn = nang
                m["branch"] = "standoff"
        else:
            m["esc"] = None
            too_old = self.old_no_eat_age and obs["age"] > self.old_no_eat_age and energy >= self.old_spawn_energy
            target_fruit = None if (m["yield"] > 0 or too_old) else self._pick_fruit(m["fruits"], energy, max_energy)
            camping = m["tree"] is not None and math.hypot(*m["tree"]) <= self.camp_dist
            if camping and obs["biome"] in self.avoid_camp_biomes:
                m["tree"] = None  # bad ground for escaping; keep exploring
                camping = False
            if camping and m["disperse"] == 0 and self.crowd_max > 0 and energy >= self.newborn_energy:
                crowd = [s for s in siblings if s["distance"] < self.crowd_dist]
                leaver = False
                if len(crowd) >= self.crowd_max:
                    if self.disperse_richest:
                        top = max(self.energies.get(s["id"], 0.0) for s in crowd)
                        ties = [s["id"] for s in crowd if abs(self.energies.get(s["id"], 0.0) - top) < 1e-9]
                        leaver = energy > top or (abs(energy - top) < 1e-9 and obs["agent_id"] > max(ties))
                    else:
                        leaver = obs["agent_id"] > max(s["id"] for s in crowd)
                if leaver:
                    m["disperse"] = self.disperse_ticks
                    cx = sum(math.cos(s["angle"]) for s in crowd)
                    cy = sum(math.sin(s["angle"]) for s in crowd)
                    m["tree"] = None
                    turn = _wrap(math.atan2(-cy, -cx))
            if m["disperse"] > 0 and turn == 0.0:
                m["disperse"] -= 1
                move = speed
                turn = self._steer_off_edges(edges)
                if target_fruit is not None and math.hypot(target_fruit[0], target_fruit[1]) < hearing:
                    d = math.hypot(target_fruit[0], target_fruit[1])
                    move, mdir = min(speed, d / penalty), math.atan2(target_fruit[1], target_fruit[0])
                m["branch"] = "disperse"
            elif m["disperse"] > 0:
                m["branch"] = "disperse"
            elif target_fruit is not None:
                fx, fy = target_fruit[0], target_fruit[1]
                d, ang = math.hypot(fx, fy), math.atan2(fy, fx)
                move, mdir = min(speed, d / penalty), ang
                if d > hearing and abs(ang) > cone / 3:
                    turn = ang
                m["branch"] = "eat"
            elif m["tree"] is not None and not camping:
                tx, ty = m["tree"]
                d, ang = math.hypot(tx, ty), math.atan2(ty, tx)
                move, mdir = min(speed, d / penalty), ang
                if abs(ang) > cone / 3:
                    turn = ang
                m["branch"] = "to_tree"
            elif camping:
                turn = 2 * math.pi / self.rotate_period if self.rotate_period else self._scan(m, cone)
                m["branch"] = "camp"
                self.camp_biome[obs["biome"]] = self.camp_biome.get(obs["biome"], 0) + 1
                if self.camp_timeout and self.tick - m["last_fruit"] > self.camp_timeout:
                    # barren camp (young, dying or desert tree): move on
                    m["tree"], m["disperse"], m["last_fruit"] = None, self.disperse_ticks, self.tick
            else:
                move = speed
                turn = self._steer_off_edges(edges) or self._scan(m, cone)
                m["branch"] = "explore"

        m["last_action"] = (move, mdir, turn)
        m["penalty"] = penalty
        self._account(m["branch"], move, turn, speed)
        return (move, mdir, turn), wants_spawn

    # ------------------------------------------------------------------ helpers
    def _clear_direction(self, away, edges):
        """Pick the candidate direction closest to `away` whose path is not blocked by a visible edge."""
        if not edges:
            return away
        pts = [_closest_point_on_segment(p, q) for p, q in edges]
        best, best_score = away, -9.0
        for k in (0, 1, -1, 2, -2, 3, -3):
            cand = _wrap(away + k * math.pi / 6)
            blocked = 0.0
            cx, cy = math.cos(cand), math.sin(cand)
            for (x, y) in pts:
                d = math.hypot(x, y)
                if d < self.edge_clear and (x * cx + y * cy) / max(d, 1e-6) > 0.5:
                    blocked = 1.0
                    break
            score = math.cos(cand - away) - 2.0 * blocked
            if score > best_score:
                best, best_score = cand, score
        return best

    def _remember_edges(self, m, seen):
        """Merge currently visible edges into a short memory of edge segments in the local frame."""
        act, pen = m["last_action"], m["penalty"]
        mem = []
        if act is not None:
            move, mdir, turn = act
            mx, my = move * pen * math.cos(mdir), move * pen * math.sin(mdir)
            for (p, q, ttl) in m["edges"]:
                if ttl <= 1:
                    continue
                a = _rotate(p[0] - mx, p[1] - my, -turn)
                b = _rotate(q[0] - mx, q[1] - my, -turn)
                mem.append((a, b, ttl - 1))
        for (p, q) in seen:
            for i, (a, b, _) in enumerate(mem):
                if (math.hypot(a[0] - p[0], a[1] - p[1]) < 8 and math.hypot(b[0] - q[0], b[1] - q[1]) < 8) or \
                   (math.hypot(a[0] - q[0], a[1] - q[1]) < 8 and math.hypot(b[0] - p[0], b[1] - p[1]) < 8):
                    mem[i] = (tuple(p), tuple(q), self.edge_memory)
                    break
            else:
                mem.append((tuple(p), tuple(q), self.edge_memory))
        m["edges"] = mem[-40:]
        return [(a, b) for (a, b, _) in mem]

    @staticmethod
    def _minmax_direction(threats, away, speed, horizon=4.0):
        """Among 16 directions pick the one maximising the minimum distance to any threat after moving
        `horizon` ticks at walking speed (threats assumed to close head-on); ties favour `away`."""
        best, best_score = away, -1e9
        step = speed * horizon
        for k in range(16):
            cand = _wrap(away + k * math.pi / 8)
            cx, cy = step * math.cos(cand), step * math.sin(cand)
            worst = min(math.hypot(x - cx, y - cy) for (x, y, *_) in threats)
            score = worst - 0.02 * step * abs(_wrap(cand - away))
            if score > best_score:
                best, best_score = cand, score
        return best

    def _update_tree_memory(self, m, trees, hearing):
        seen = [(o["distance"] * math.cos(o["angle"]), o["distance"] * math.sin(o["angle"])) for o in trees]
        mem = []
        for (x, y, seen_tick, first_tick) in m["trees"]:
            if math.hypot(x, y) < hearing - 5 and not any(math.hypot(x - sx, y - sy) < 30 for sx, sy in seen):
                continue  # inside hearing range yet unseen: the tree is gone
            if self.tick - seen_tick > self.tree_mem_ttl or self.tick - first_tick > self.tree_max_age:
                continue
            mem.append([x, y, seen_tick, first_tick])
        for sx, sy in seen:
            for t in mem:
                if math.hypot(t[0] - sx, t[1] - sy) < 30:
                    t[0], t[1], t[2] = sx, sy, self.tick
                    break
            else:
                mem.append([sx, sy, self.tick, self.tick])
        m["trees"] = [tuple(t) for t in mem[-30:]]

    def _pick_fruit(self, fruits, energy, max_energy):
        if not fruits or energy > max_energy - 25:
            return None
        hungry = energy < self.hungry_energy
        ripe = [f for f in fruits if hungry or (self.tick - f[2]) * 0.1 >= self.ripe_age]
        if not ripe:
            return None
        return min(ripe, key=lambda f: math.hypot(f[0], f[1]))

    def _scan(self, m, cone):
        m["scan"] += 1
        if self.scan_period and m["scan"] % self.scan_period == 0:
            return cone
        return 0.0

    def _steer_off_edges(self, edges):
        best = None
        for p, q in edges:
            cx, cy = _closest_point_on_segment(p, q)
            d = math.hypot(cx, cy)
            if d < self.edge_margin and cx > -5 and (best is None or d < best[0]):
                best = (d, cx, cy)
        if best is None:
            return 0.0
        return -math.pi / 2 if best[2] >= 0 else math.pi / 2
