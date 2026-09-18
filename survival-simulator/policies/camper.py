"""v1 hivemind: tree camper with predator stand-off.

Per agent, each tick, first matching rule wins for movement:
  1. predator seen close   -> flee (sprint straight away)
  2. predator seen far     -> stand-off (face it, walk away)
  3. ripe/needed fruit     -> walk to it
  4. tree within camp_dist -> stand still, scan slowly
  5. tree seen / remembered-> walk to it
  6. nothing               -> explore (walk forward, steer off edges, scan)
Spawning is decided independently from energy, age and population.

All geometry is in the agent's local frame: x forward, y left (angle = atan2(y, x)),
matching the simulator's observation convention. Memory per agent is advanced by the
agent's own commanded motion so remembered targets stay roughly valid while unseen.
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


class CamperPolicy:
    def __init__(self, charge_dist=95.0, flee_ticks=15, camp_dist=15.0, scan_period=10,
                 ripe_age=18.0, hungry_energy=120.0, spawn_energy=300.0, pop_cap=8,
                 old_age=70.0, old_spawn_energy=110.0, edge_margin=35.0, target_ttl=40,
                 flee_speed_factor=1.0, lookback=False, crowd_max=0, crowd_dist=60.0,
                 disperse_ticks=25, share_alarm=False, alarm_dist=220.0):
        self.lookback = lookback
        # share_alarm: a predator seen by one agent is reported to every sibling it can see,
        # converted into that sibling's frame (siblings' relative facing is observed)
        self.share_alarm = share_alarm
        self.alarm_dist = alarm_dist
        # crowd_max > 0: when camping with >= crowd_max siblings within crowd_dist, the youngest
        # (highest id) walks away for disperse_ticks to find its own tree
        self.crowd_max = crowd_max
        self.crowd_dist = crowd_dist
        self.disperse_ticks = disperse_ticks
        self.charge_dist = charge_dist
        self.flee_ticks = flee_ticks
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
        self.flee_speed_factor = flee_speed_factor
        self.mem = {}
        self.tick = 0
        self.last_time = -1.0
        self.branch_ticks = {}   # diagnostics: ticks spent per decision branch
        self.branch_energy = {}  # and commanded move+turn energy per branch

    # ------------------------------------------------------------------ memory
    def _reset(self):
        self.mem = {}
        self.tick = 0

    def _get_mem(self, agent_id):
        m = self.mem.get(agent_id)
        if m is None:
            m = {"tree": None, "tree_age": 0, "flee": 0, "flee_dir": 0.0, "disperse": 0,
                 "fruits": [], "last_action": None, "penalty": 1.0, "scan": 0}
            self.mem[agent_id] = m
        return m

    @staticmethod
    def _advance(points, action, penalty):
        """Move local-frame points by the inverse of our own motion (move then turn)."""
        if action is None or not points:
            return points
        move, mdir, turn = action
        mx, my = move * penalty * math.cos(mdir), move * penalty * math.sin(mdir)
        c, s = math.cos(-turn), math.sin(-turn)
        out = []
        for (x, y, *rest) in points:
            x, y = x - mx, y - my
            out.append((x * c - y * s, x * s + y * c, *rest))
        return out

    # ------------------------------------------------------------------ main
    def act(self, step):
        sim_time = step.get("sim_time", 0.0)
        if sim_time < self.last_time:
            self._reset()
        self.last_time = sim_time
        self.tick += 1
        n_agents = len(step["agent_status"])
        alive = {a["agent_id"] for a in step["agent_status"]}
        for dead in [k for k in self.mem if k not in alive]:
            del self.mem[dead]

        if self.share_alarm:
            self._share_alarms(step["agent_status"])

        actions = []
        spawns_left = max(0, self.pop_cap - n_agents)
        for obs in step["agent_status"]:
            action, wants_spawn = self._decide(obs)
            spawn = False
            if wants_spawn and spawns_left > 0:
                spawn = True
                spawns_left -= 1
            actions.append({"agent_id": obs["agent_id"], "move_distance": action[0],
                            "move_direction": action[1], "turn_angle": action[2],
                            "spawn_agent": spawn})
        return actions

    def _share_alarms(self, statuses):
        """Inject virtual predator observations into siblings' observation lists.

        Observer A sees sibling B at (d, theta) with B's relative bearing of A (rel_dir).
        B.direction - A.direction = pi - rel_dir + theta, so a point in A's frame maps into
        B's frame by translating by -B and rotating by -(pi - rel_dir + theta).
        """
        by_id = {s["agent_id"]: s for s in statuses}
        alarms = {}  # target id -> list of (distance, angle)
        for a in statuses:
            preds = [o for o in a["observations"] if o["type"] == "Predator"]
            if not preds:
                continue
            for s in a["observations"]:
                if s["type"] != "Agent" or s["id"] not in by_id:
                    continue
                bx, by = s["distance"] * math.cos(s["angle"]), s["distance"] * math.sin(s["angle"])
                rot = -(math.pi - s["rel_dir"] + s["angle"])
                c, sn = math.cos(rot), math.sin(rot)
                for p in preds:
                    px, py = p["distance"] * math.cos(p["angle"]) - bx, p["distance"] * math.sin(p["angle"]) - by
                    qx, qy = px * c - py * sn, px * sn + py * c
                    d = math.hypot(qx, qy)
                    if d <= self.alarm_dist:
                        alarms.setdefault(s["id"], []).append((d, math.atan2(qy, qx)))
        for target, seen in alarms.items():
            obs_list = by_id[target]["observations"]
            if any(o["type"] == "Predator" for o in obs_list):
                continue  # it has its own, better information
            d, ang = min(seen)
            obs_list.append({"type": "Predator", "distance": d, "angle": ang, "rel_dir": 0.0, "virtual": True})

    def _decide(self, obs):
        m = self._get_mem(obs["agent_id"])
        energy, speed, sprint = obs["energy"], obs["speed"], obs["sprint_speed"]
        hearing, cone = obs["hearing_radius"], obs["vision_angle"]
        penalty = BIOME_PENALTY.get(obs["biome"], 1.0)

        # advance memory by last tick's motion
        if m["tree"] is not None:
            m["tree"] = self._advance([m["tree"]], m["last_action"], m["penalty"])[0]
            m["tree_age"] += 1
            if m["tree_age"] > self.target_ttl:
                m["tree"] = None
        m["fruits"] = self._advance(m["fruits"], m["last_action"], m["penalty"])

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

        # fruit tracking: match observed fruit to remembered ones (first-seen tick)
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

        if trees:
            tr = min(trees, key=lambda o: o["distance"])
            m["tree"] = (tr["distance"] * math.cos(tr["angle"]), tr["distance"] * math.sin(tr["angle"]))
            m["tree_age"] = 0

        move, mdir, turn = 0.0, 0.0, 0.0
        old = obs["age"] > self.old_age
        wants_spawn = (energy > self.spawn_energy) or (old and energy > self.old_spawn_energy)

        if preds:
            p = min(preds, key=lambda o: o["distance"])
            if p["distance"] < self.charge_dist:
                m["flee"], m["flee_dir"] = self.flee_ticks, _wrap(p["angle"] + math.pi)
                move, mdir = sprint * self.flee_speed_factor, m["flee_dir"]
                m["branch"] = "flee"
            else:
                # move is applied before the turn, so both are relative to the current facing
                m["flee"] = 0
                move, mdir, turn = speed, _wrap(p["angle"] + math.pi), p["angle"]
                m["branch"] = "standoff"
        elif m["flee"] > 0:
            # predator out of sight (behind us): keep sprinting, then look back once so a
            # predator that is still chasing is seen at >= charge_dist and handled by stand-off
            m["flee"] -= 1
            m["branch"] = "flee_blind"
            if self.lookback:
                move, mdir = sprint * self.flee_speed_factor, m["flee_dir"]
                if m["flee"] == 0:
                    turn = math.pi
            else:  # v1 behaviour
                move, mdir = speed, m["flee_dir"]
        else:
            target_fruit = self._pick_fruit(m["fruits"], energy, obs["max_energy"])
            camping = m["tree"] is not None and math.hypot(*m["tree"]) <= self.camp_dist
            if camping and m["disperse"] == 0 and self.crowd_max > 0:
                crowd = [s for s in siblings if s["distance"] < self.crowd_dist]
                if len(crowd) >= self.crowd_max and obs["agent_id"] > max(s["id"] for s in crowd):
                    m["disperse"] = self.disperse_ticks
                    cx = sum(math.cos(s["angle"]) for s in crowd)
                    cy = sum(math.sin(s["angle"]) for s in crowd)
                    m["tree"] = None
                    turn = _wrap(math.atan2(-cy, -cx))  # face away from the crowd, then walk forward
            if m["disperse"] > 0 and turn == 0.0:
                m["disperse"] -= 1
                m["branch"] = "disperse"
                move = speed
                turn = self._steer_off_edges(edges, speed)
                if target_fruit is not None and math.hypot(target_fruit[0], target_fruit[1]) < hearing:
                    move, mdir = min(speed, math.hypot(target_fruit[0], target_fruit[1]) / penalty), \
                        math.atan2(target_fruit[1], target_fruit[0])
            elif m["disperse"] > 0:
                m["branch"] = "disperse"  # this tick only turns to the dispersal heading
            elif target_fruit is not None:
                fx, fy = target_fruit[0], target_fruit[1]
                d, ang = math.hypot(fx, fy), math.atan2(fy, fx)
                move, mdir = min(speed, d / penalty), ang
                m["branch"] = "eat"
                if d > hearing and abs(ang) > cone / 3:
                    turn = ang
            elif m["tree"] is not None and math.hypot(*m["tree"]) > self.camp_dist:
                tx, ty = m["tree"]
                d, ang = math.hypot(tx, ty), math.atan2(ty, tx)
                move, mdir = min(speed, d / penalty), ang
                m["branch"] = "to_tree"
                if abs(ang) > cone / 3:
                    turn = ang
            elif m["tree"] is not None:
                turn = self._scan(m, cone)
                m["branch"] = "camp"
            else:
                move = speed
                m["branch"] = "explore"
                turn = self._steer_off_edges(edges, speed) or self._scan(m, cone)
                if turn:
                    mdir = 0.0

        m["last_action"] = (move, mdir, turn)
        m["penalty"] = penalty
        m["flee_dir"] = _wrap(m["flee_dir"] - turn)
        self._account(m.get("branch", "?"), move, turn, speed)
        return (move, mdir, turn), wants_spawn

    def _account(self, branch, move, turn, speed):
        cost = min(move, speed) * 0.05 + max(0.0, move - speed) * 0.5 + min(math.pi, abs(turn)) / (2 * math.pi)
        self.branch_ticks[branch] = self.branch_ticks.get(branch, 0) + 1
        self.branch_energy[branch] = self.branch_energy.get(branch, 0.0) + cost

    def stats(self):
        return {"branch_ticks": dict(self.branch_ticks),
                "branch_energy": {k: round(v, 1) for k, v in self.branch_energy.items()}}

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

    def _steer_off_edges(self, edges, speed):
        """Turn away from the nearest edge point if it is close and ahead."""
        best = None
        for p, q in edges:
            cx, cy = _closest_point_on_segment(p, q)
            d = math.hypot(cx, cy)
            if d < self.edge_margin and cx > -5 and (best is None or d < best[0]):
                best = (d, cx, cy)
        if best is None:
            return 0.0
        _, cx, cy = best
        return -math.pi / 2 if cy >= 0 else math.pi / 2
