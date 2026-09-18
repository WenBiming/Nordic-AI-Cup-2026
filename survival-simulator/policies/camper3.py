"""v3 hivemind: camper2 + obstacle hiding ("the dance").

Motivation (docs/journal.md, Exp 6/7): predators find an agent in the open every ~10 s at mid-game
density; Predator.step is stateless, so an agent that keeps an obstacle between itself and a predator
is forgotten the moment line of sight breaks. Scripted dancers lived 3x longer than idle agents.

Additions over Camper2Policy:
  * edge memory: observed edge segments (full segments, local frame) are remembered, advanced by own
    motion, and grouped into axis-aligned rectangles ("obstacles"); boundary walls are ignored;
  * home obstacle: when a tree is found and an obstacle lies within camp_obstacle_dist of it, the agent
    camps at the obstacle perimeter point nearest the tree instead of at the tree; after
    require_obstacle_after seconds trees without a nearby obstacle are skipped;
  * threat response: with a home obstacle, move to the perimeter point that is occluded from the nearest
    threat and far from all threats (sprint while the threat is close); otherwise camper2's flee/stand-off;
  * scanning: campers rotate continuously with a period from rotate_schedule [(t, period), ...].
"""
import math

from policies.camper2 import BIOME_PENALTY, Camper2Policy, _closest_point_on_segment, _rotate, _wrap

PERIMETER_OFFSET = 8.0


class Camper3Policy(Camper2Policy):
    def __init__(self, camp_obstacle_dist=80.0, require_obstacle_after=600.0, edge_ttl=150,
                 max_edge_len=200.0, hide_min_dist=70.0, dance_sprint_dist=110.0,
                 rotate_schedule=((0, 0), (400, 20), (1000, 12)), sprint_zone=130.0,
                 avoid_camp_biomes=("swamp", "river"), avoid_biome_obstacle_camps=False,
                 evacuate_ticks=0, evacuate_dist=120.0, spawn_needs_fruit=False, yield_ticks=30, **kw):
        super().__init__(sprint_zone=sprint_zone, avoid_camp_biomes=avoid_camp_biomes, **kw)
        self.avoid_biome_obstacle_camps = avoid_biome_obstacle_camps  # apply avoid_camp_biomes to obstacle camps too
        self.evacuate_ticks = evacuate_ticks    # >0: siblings that saw a just-eaten agent walk away from it this long
        self.evacuate_dist = evacuate_dist
        self.spawn_needs_fruit = spawn_needs_fruit  # spawn only with a tracked fruit within hearing range
        self.yield_ticks = yield_ticks          # parent ignores fruit this long after spawning
        self.last_energy = {}
        self.last_seen_sib = {}                 # observer id -> {sibling id: (x, y, tick)} local frame
        self.camp_obstacle_dist = camp_obstacle_dist
        self.require_obstacle_after = require_obstacle_after
        self.edge_ttl = edge_ttl
        self.max_edge_len = max_edge_len
        self.hide_min_dist = hide_min_dist      # prefer hiding points at least this far from the threat (hearing 60)
        self.dance_sprint_dist = dance_sprint_dist
        self.rotate_schedule = sorted(rotate_schedule)

    def _get_mem(self, agent_id):
        m = self.mem.get(agent_id)
        created = m is None
        m = super()._get_mem(agent_id)
        if created:
            m["edges"] = []      # (x1, y1, x2, y2, ttl)
            m["home"] = None     # rectangle (cx, cy, ux, uy, hw, hh) in local frame: centre, unit axis, half sizes
            m["camp_pt"] = None  # (x, y) local
            m["yield"] = 0
        return m

    def act(self, step):
        statuses = step["agent_status"]
        alive = {a["agent_id"] for a in statuses}
        if self.evacuate_ticks and step.get("sim_time", 0.0) >= self.last_time:
            eaten = [i for i, e in self.last_energy.items() if i not in alive and e > 3.0]
            for victim in eaten:
                for obs in statuses:
                    seen = self.last_seen_sib.get(obs["agent_id"], {}).get(victim)
                    if seen is None or self.tick - seen[2] > 20 or math.hypot(seen[0], seen[1]) > self.evacuate_dist:
                        continue
                    m = self._get_mem(obs["agent_id"])
                    vx, vy = self._advance([(seen[0], seen[1])], m["last_action"], m["penalty"])[0]
                    # treat the kill site as a threat: the dance / flee logic walks away from it
                    m["threats"].append((vx, vy, self.evacuate_ticks))
        actions = super().act(step)
        self.last_energy = {a["agent_id"]: a["energy"] for a in statuses}
        self.last_seen_sib = {k: v for k, v in self.last_seen_sib.items() if k in alive}
        for obs in statuses:
            d = self.last_seen_sib.setdefault(obs["agent_id"], {})
            for o in obs["observations"]:
                if o["type"] == "Agent":
                    d[o["id"]] = (o["distance"] * math.cos(o["angle"]), o["distance"] * math.sin(o["angle"]), self.tick)
        for a in actions:
            if a["spawn_agent"]:
                self._get_mem(a["agent_id"])["yield"] = self.yield_ticks
        return actions

    # ------------------------------------------------------------------ obstacle model
    @staticmethod
    def _advance_edges(edges, action, penalty):
        if action is None or not edges:
            return edges
        move, mdir, turn = action
        mx, my = move * penalty * math.cos(mdir), move * penalty * math.sin(mdir)
        out = []
        for (x1, y1, x2, y2, ttl) in edges:
            a = _rotate(x1 - mx, y1 - my, -turn)
            b = _rotate(x2 - mx, y2 - my, -turn)
            out.append((a[0], a[1], b[0], b[1], ttl))
        return out

    def _update_edges(self, m, seen_edges):
        edges = [(x1, y1, x2, y2, ttl - 1) for (x1, y1, x2, y2, ttl) in m["edges"] if ttl > 1]
        for (p, q) in seen_edges:
            (x1, y1), (x2, y2) = p, q
            if math.hypot(x2 - x1, y2 - y1) > self.max_edge_len:
                continue  # boundary wall
            replaced = False
            for i, e in enumerate(edges):
                if (math.hypot(e[0] - x1, e[1] - y1) < 8 and math.hypot(e[2] - x2, e[3] - y2) < 8) or \
                   (math.hypot(e[0] - x2, e[1] - y2) < 8 and math.hypot(e[2] - x1, e[3] - y1) < 8):
                    edges[i] = (x1, y1, x2, y2, self.edge_ttl)
                    replaced = True
                    break
            if not replaced:
                edges.append((x1, y1, x2, y2, self.edge_ttl))
        m["edges"] = edges[-40:]

    @staticmethod
    def _rect_from_group(group):
        """Axis-aligned (in world) rectangle from edges sharing corners. Returns (cx, cy, ux, uy, hw, hh)."""
        longest = max(group, key=lambda e: math.hypot(e[2] - e[0], e[3] - e[1]))
        L = math.hypot(longest[2] - longest[0], longest[3] - longest[1])
        ux, uy = (longest[2] - longest[0]) / L, (longest[3] - longest[1]) / L
        vx, vy = -uy, ux
        us, vs = [], []
        for (x1, y1, x2, y2, _) in group:
            for (x, y) in ((x1, y1), (x2, y2)):
                us.append(x * ux + y * uy)
                vs.append(x * vx + y * vy)
        umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
        if vmax - vmin < 5.0:  # only one side seen: assume a square extending away from the agent
            depth = max(30.0, min(100.0, L))
            v_edge = (vmin + vmax) / 2
            if v_edge > 0:   # edge is on the +v side of the agent -> obstacle extends further along +v
                vmin, vmax = v_edge, v_edge + depth
            else:
                vmin, vmax = v_edge - depth, v_edge
        cu, cv = (umin + umax) / 2, (vmin + vmax) / 2
        cx, cy = cu * ux + cv * vx, cu * uy + cv * vy
        return (cx, cy, ux, uy, (umax - umin) / 2, (vmax - vmin) / 2)

    def _obstacles(self, m):
        edges = m["edges"]
        groups = []
        used = [False] * len(edges)
        for i, e in enumerate(edges):
            if used[i]:
                continue
            group, stack = [], [i]
            used[i] = True
            while stack:
                j = stack.pop()
                group.append(edges[j])
                ej = edges[j]
                for k, ek in enumerate(edges):
                    if used[k]:
                        continue
                    if any(math.hypot(ej[a] - ek[b], ej[a + 1] - ek[b + 1]) < 8 for a in (0, 2) for b in (0, 2)):
                        used[k] = True
                        stack.append(k)
            groups.append(group)
        return [self._rect_from_group(g) for g in groups]

    @staticmethod
    def _rect_local(rect, x, y):
        cx, cy, ux, uy, hw, hh = rect
        dx, dy = x - cx, y - cy
        return dx * ux + dy * uy, -dx * uy + dy * ux  # (u, v) coordinates relative to the rectangle centre

    @classmethod
    def _rect_dist(cls, rect, x, y):
        u, v = cls._rect_local(rect, x, y)
        du, dv = max(0.0, abs(u) - rect[4]), max(0.0, abs(v) - rect[5])
        return math.hypot(du, dv)

    @classmethod
    def _perimeter(cls, rect):
        cx, cy, ux, uy, hw, hh = rect
        hw2, hh2 = hw + PERIMETER_OFFSET, hh + PERIMETER_OFFSET
        pts = []
        for (u, v) in ((0, -hh2), (0, hh2), (-hw2, 0), (hw2, 0), (-hw2, -hh2), (hw2, -hh2), (-hw2, hh2), (hw2, hh2)):
            pts.append((cx + u * ux - v * uy, cy + u * uy + v * ux))
        return pts

    @classmethod
    def _occluded(cls, rect, p, q, samples=10):
        for i in range(1, samples):
            t = i / samples
            x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            u, v = cls._rect_local(rect, x, y)
            if abs(u) < rect[4] and abs(v) < rect[5]:
                return True
        return False

    # ------------------------------------------------------------------ decision
    def _rotate_period(self):
        period = 0
        for t, p in self.rotate_schedule:
            if self.last_time >= t:
                period = p
        return period

    def _decide(self, obs):
        m = self._get_mem(obs["agent_id"])
        energy, speed, sprint = obs["energy"], obs["speed"], obs["sprint_speed"]
        hearing, cone, max_energy = obs["hearing_radius"], obs["vision_angle"], obs["max_energy"]
        penalty = BIOME_PENALTY.get(obs["biome"], 1.0)

        # ---- advance memory by last tick's own motion
        act, pen = m["last_action"], m["penalty"]
        if m["tree"] is not None:
            m["tree"] = self._advance([m["tree"]], act, pen)[0]
            m["tree_age"] += 1
            if m["tree_age"] > self.target_ttl:
                m["tree"] = None
        m["fruits"] = self._advance(m["fruits"], act, pen)
        m["threats"] = self._advance(m["threats"], act, pen)
        m["edges"] = self._advance_edges(m["edges"], act, pen)
        if m["camp_pt"] is not None:
            m["camp_pt"] = self._advance([m["camp_pt"]], act, pen)[0]

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
        self._update_edges(m, edges)
        rects = self._obstacles(m)

        # ---- threats
        threats = []
        for (x, y, ttl) in m["threats"]:
            d = math.hypot(x, y)
            if d > 5.0:
                f = max(0.0, d - self.threat_approach) / d
                x, y = x * f, y * f
            if ttl > 1:
                threats.append([x, y, ttl - 1])
        for p in preds:
            px, py = p["distance"] * math.cos(p["angle"]), p["distance"] * math.sin(p["angle"])
            for th in threats:
                if math.hypot(th[0] - px, th[1] - py) < self.threat_merge:
                    th[0], th[1], th[2] = px, py, self.threat_ttl
                    break
            else:
                threats.append([px, py, self.threat_ttl])
        m["threats"] = [tuple(t) for t in threats]

        # ---- fruit tracking
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

        # ---- tree / camp point selection
        if trees:
            tr = min(trees, key=lambda o: o["distance"])
            tx, ty = tr["distance"] * math.cos(tr["angle"]), tr["distance"] * math.sin(tr["angle"])
            near = [(self._rect_dist(r, tx, ty), r) for r in rects]
            near = [nr for nr in near if nr[0] <= self.camp_obstacle_dist]
            if near:
                _, r = min(near, key=lambda nr: nr[0])
                pts = self._perimeter(r)
                cp = min(pts, key=lambda p: math.hypot(p[0] - tx, p[1] - ty))
                m["tree"], m["tree_age"], m["camp_pt"] = (tx, ty), 0, cp
            elif self.last_time < self.require_obstacle_after or m["tree"] is None:
                m["tree"], m["tree_age"], m["camp_pt"] = (tx, ty), 0, None
        if m["tree"] is None:
            m["camp_pt"] = None
        home = None
        if rects:
            d, r = min(((self._rect_dist(r, 0.0, 0.0), r) for r in rects), key=lambda x: x[0])
            if d < 40.0:
                home = r

        move, mdir, turn = 0.0, 0.0, 0.0
        old = obs["age"] > self.old_age
        wants_spawn = not threats and ((energy > self.spawn_energy) or (old and energy > self.old_spawn_energy))
        if wants_spawn and self.spawn_needs_fruit:
            wants_spawn = any(math.hypot(f[0], f[1]) < hearing for f in m["fruits"])
        if m["yield"] > 0:
            m["yield"] -= 1
        target_pt = m["camp_pt"] if m["camp_pt"] is not None else m["tree"]

        if threats:
            nearest = min(threats, key=lambda t: math.hypot(t[0], t[1]))
            nd, nang = math.hypot(nearest[0], nearest[1]), math.atan2(nearest[1], nearest[0])
            if home is not None and nd > 20.0:
                # the dance: perimeter point occluded from the nearest threat and far from all threats
                best, best_score = None, -1e9
                for (qx, qy) in self._perimeter(home):
                    score = -0.3 * math.hypot(qx, qy)
                    for (x, y, *_) in threats:
                        dq = math.hypot(qx - x, qy - y)
                        score += min(dq, 150.0) + (150.0 if self._occluded(home, (x, y), (qx, qy)) else 0.0) \
                            - (100.0 if dq < self.hide_min_dist else 0.0)
                    if score > best_score:
                        best, best_score = (qx, qy), score
                d = math.hypot(*best)
                if d > 1.5:
                    fast = nd < self.dance_sprint_dist and energy >= max_energy / 5
                    move, mdir = min(sprint if fast else speed, d / penalty), math.atan2(best[1], best[0])
                m["branch"] = "dance"
            else:
                ax = ay = 0.0
                for (x, y, *_) in threats:
                    d = max(1.0, math.hypot(x, y))
                    ax -= x / d / d
                    ay -= y / d / d
                mdir = self._clear_direction(math.atan2(ay, ax), edges)
                if nd < self.charge_dist:
                    move = sprint if energy >= max_energy / 5 else speed
                    m["branch"] = "flee"
                else:
                    move = speed
                    if nd < self.sprint_zone and energy >= max_energy / 5:
                        move = sprint
                    if abs(nang) > 0.05:
                        turn = nang
                    m["branch"] = "standoff"
        else:
            target_fruit = None if m["yield"] > 0 else self._pick_fruit(m["fruits"], energy, max_energy)
            at_home = target_pt is not None and math.hypot(*target_pt) <= self.camp_dist
            if at_home and obs["biome"] in self.avoid_camp_biomes and (m["camp_pt"] is None or self.avoid_biome_obstacle_camps):
                m["tree"], target_pt, at_home = None, None, False
            if at_home and m["disperse"] == 0 and self.crowd_max > 0:
                crowd = [s for s in siblings if s["distance"] < self.crowd_dist]
                if len(crowd) >= self.crowd_max and obs["agent_id"] > max(s["id"] for s in crowd):
                    m["disperse"] = self.disperse_ticks
                    cx = sum(math.cos(s["angle"]) for s in crowd)
                    cy = sum(math.sin(s["angle"]) for s in crowd)
                    m["tree"], m["camp_pt"] = None, None
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
            elif target_pt is not None and not at_home:
                d, ang = math.hypot(*target_pt), math.atan2(target_pt[1], target_pt[0])
                move, mdir = min(speed, d / penalty), ang
                if abs(ang) > cone / 3:
                    turn = ang
                m["branch"] = "to_tree"
            elif at_home:
                period = self._rotate_period()
                turn = 2 * math.pi / period if period else self._scan(m, cone)
                m["branch"] = "camp"
            else:
                move = speed
                turn = self._steer_off_edges(edges) or self._scan(m, cone)
                m["branch"] = "explore"

        m["last_action"] = (move, mdir, turn)
        m["penalty"] = penalty
        self._account(m["branch"], move, turn, speed)
        return (move, mdir, turn), wants_spawn
