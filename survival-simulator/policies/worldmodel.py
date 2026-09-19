"""Hivemind world model: dead-reckoned poses of all agents in shared frames.

The simulator gives no absolute positions, but the hivemind knows every action it commanded, the
biome movement penalty at each agent, and it sees agents' relative distance / angle / facing when
they are near each other. That is enough for:
  * a pose (x, y, heading) per agent, advanced each tick by its own commanded motion;
  * exact initialisation of a child from its parent's observation of it (children appear within
    30 units of the parent, inside hearing range, so the parent always sees them);
  * merging of founder frames the first time two agents of different frames see each other;
  * drift correction whenever two agents of the same frame see each other.
Positions drift with collisions (the simulator slides blocked moves sideways), so treat them as
approximate (tens of units after minutes), fine for spacing and navigation decisions.

Conventions: heading in world radians; an observation of B by A at (d, ang, rel_dir) means
B = A.pos + d * (cos(A.h + ang), sin(A.h + ang)) and B.h = A.h + ang + pi - rel_dir.
"""
import math


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class WorldModel:
    def __init__(self, biome_penalty, correction=0.5):
        self.biome_penalty = biome_penalty
        self.correction = correction      # fraction of a sighting disagreement applied to each pose
        self.poses = {}                   # id -> [x, y, heading, frame]
        self.next_frame = 0
        self.pending_spawns = []          # ids of agents flagged to spawn last tick, in status order
        self.last_actions = {}            # id -> (move, mdir, turn, penalty)
        self.frames_merged = 0
        self.tick = 0

    # ------------------------------------------------------------------ per tick
    def reset(self):
        self.__init__(self.biome_penalty, self.correction)

    def begin_tick(self, statuses):
        """Advance poses by last tick's motion, register new agents, then fuse sightings."""
        self.tick += 1
        by_id = {s["agent_id"]: s for s in statuses}
        # 1. dead reckoning
        for aid, (move, mdir, turn, pen) in self.last_actions.items():
            p = self.poses.get(aid)
            if p is None:
                continue
            d = move * pen
            p[0] += d * math.cos(p[2] + mdir)
            p[1] += d * math.sin(p[2] + mdir)
            p[2] = _wrap(p[2] + turn)
        # 2. drop the dead
        for aid in [a for a in self.poses if a not in by_id]:
            del self.poses[aid]
        # 3. new agents: children of last tick's spawners (ids are assigned in spawn order), else founders
        new_ids = sorted(a for a in by_id if a not in self.poses)
        parents = [p for p in self.pending_spawns if p in by_id]
        for i, aid in enumerate(new_ids):
            parent = parents[i] if i < len(parents) else None
            placed = False
            if parent is not None:
                obs = next((o for o in by_id[parent]["observations"] if o["type"] == "Agent" and o.get("id") == aid), None)
                pp = self.poses.get(parent)
                if obs is not None and pp is not None:
                    x, y, h = self._project(pp, obs)
                    self.poses[aid] = [x, y, h, pp[3]]
                    placed = True
                elif pp is not None:  # parent did not see it: place at the parent, heading unknown
                    self.poses[aid] = [pp[0], pp[1], pp[2], pp[3]]
                    placed = True
            if not placed:
                self.poses[aid] = [0.0, 0.0, 0.0, self.next_frame]
                self.next_frame += 1
        self.pending_spawns = []
        # 4. sightings: merge frames, correct drift
        for s in statuses:
            pa = self.poses.get(s["agent_id"])
            if pa is None:
                continue
            for o in s["observations"]:
                if o["type"] != "Agent" or o.get("id") not in self.poses:
                    continue
                pb = self.poses[o["id"]]
                x, y, h = self._project(pa, o)
                if pb[3] != pa[3]:
                    self._merge_frame(pb[3], pa[3], pb, (x, y, h))
                else:
                    c = self.correction
                    # split the disagreement: move B toward the sighting, A the other way
                    pb[0] += c * (x - pb[0]) * 0.5
                    pb[1] += c * (y - pb[1]) * 0.5
                    pb[2] = _wrap(pb[2] + c * _wrap(h - pb[2]) * 0.5)
                    pa[0] -= c * (x - pb[0]) * 0.5
                    pa[1] -= c * (y - pb[1]) * 0.5

    def end_tick(self, actions, statuses):
        """Remember what was commanded so next tick can dead-reckon; note who spawned."""
        pen = {s["agent_id"]: self.biome_penalty.get(s["biome"], 1.0) for s in statuses}
        self.last_actions = {a["agent_id"]: (a["move_distance"], a["move_direction"], a["turn_angle"], pen.get(a["agent_id"], 1.0))
                             for a in actions}
        self.pending_spawns = [a["agent_id"] for a in actions if a["spawn_agent"]]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _project(pa, obs):
        ang = pa[2] + obs["angle"]
        x = pa[0] + obs["distance"] * math.cos(ang)
        y = pa[1] + obs["distance"] * math.sin(ang)
        h = _wrap(ang + math.pi - obs.get("rel_dir", 0.0))
        return x, y, h

    def _merge_frame(self, src, dst, pb, target):
        """Re-express every pose of frame `src` in frame `dst`, given that pose `pb` should equal `target`."""
        dh = _wrap(target[2] - pb[2])
        c, s = math.cos(dh), math.sin(dh)
        ox, oy = pb[0], pb[1]
        for p in self.poses.values():
            if p[3] != src:
                continue
            rx, ry = p[0] - ox, p[1] - oy
            p[0] = target[0] + rx * c - ry * s
            p[1] = target[1] + rx * s + ry * c
            p[2] = _wrap(p[2] + dh)
            p[3] = dst
        self.frames_merged += 1

    # ------------------------------------------------------------------ queries
    def pose(self, aid):
        return self.poses.get(aid)

    def to_local(self, aid, x, y):
        """World point -> (distance, relative angle) in agent aid's frame; None if unknown."""
        p = self.poses.get(aid)
        if p is None:
            return None
        dx, dy = x - p[0], y - p[1]
        return math.hypot(dx, dy), _wrap(math.atan2(dy, dx) - p[2])

    def to_world(self, aid, dist, ang):
        p = self.poses.get(aid)
        if p is None:
            return None
        a = p[2] + ang
        return p[0] + dist * math.cos(a), p[1] + dist * math.sin(a)

    def same_frame(self, a, b):
        pa, pb = self.poses.get(a), self.poses.get(b)
        return pa is not None and pb is not None and pa[3] == pb[3]
