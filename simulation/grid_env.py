import heapq
from dataclasses import dataclass, field

import numpy as np

# grid vocab. 0 = empty, 1 = trash. thats all the world state we need rn
EMPTY = 0
TRASH = 1

# (dx, dy) per move. y grows downward like every screen coord system ever made
MOVES = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

# flipped so the driving code can turn a step delta back into a move name
DIR_NAMES = {delta: name for name, delta in MOVES.items()}


def manhattan(a, b) -> int:
    # the a-star heuristic AND the real walk cost on a 4-dir grid
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class Rover:
    # dumb container on purpose. the smart stuff lives in core/
    name: str
    pos: tuple
    collected: int = 0
    stalls: int = 0
    moves: int = 0
    target: tuple | None = None  # the trash the allocator told this rover to go get
    path: list = field(default_factory=list)  # remaining a-star steps to that target
    trail: list = field(default_factory=list)  # last few tiles, purely for the visualizer glow


class GridEnv:
    def __init__(self, width: int = 24, height: int = 24, seed: int | None = None):
        self.width = width
        self.height = height
        # trash lives in an (N, 2) coord array. radius queries on this are way
        # faster than scanning a full 2d map every tick. render builds the grid on demand
        self.trash = np.empty((0, 2), dtype=np.int16)
        self.rng = np.random.default_rng(seed)

    def spawn_trash(self, count: int) -> int:
        # brute forcing the grid bounds rn, if we land on an occupied tile we just reroll.
        # taken set covers old trash AND tiles picked earlier in this same call
        taken = {tuple(c) for c in self.trash}
        fresh = []
        guard = 0
        while len(fresh) < count and guard < count * 50:
            x = int(self.rng.integers(0, self.width))
            y = int(self.rng.integers(0, self.height))
            if (x, y) not in taken:
                fresh.append((x, y))
                taken.add((x, y))
            guard += 1
        # guard cap stops an infinite loop when the grid is basically full lol
        if fresh:
            self.trash = np.vstack([self.trash, np.array(fresh, dtype=np.int16)])
        return len(fresh)

    def nearby_trash(self, pos, radius: int = 6, limit: int = 8) -> list:
        # kept for sensor-style queries. the allocator sees the whole board now
        if self.trash.size == 0:
            return []
        dists = np.hypot(self.trash[:, 0] - pos[0], self.trash[:, 1] - pos[1])
        close = dists <= radius
        if not close.any():
            return []
        coords = self.trash[close]
        picked = dists[close]
        # nearest first, capped, so prompts and logs stay small
        order = np.argsort(picked)[:limit]
        return [(int(coords[i][0]), int(coords[i][1]), round(float(picked[i]), 2)) for i in order]

    def collect(self, pos) -> bool:
        # called right after a move. standing on trash = scoop it
        if self.trash.size == 0:
            return False
        hit = (self.trash[:, 0] == pos[0]) & (self.trash[:, 1] == pos[1])
        if not hit.any():
            return False
        self.trash = self.trash[~hit]
        return True

    def in_bounds(self, pos) -> bool:
        return 0 <= pos[0] < self.width and 0 <= pos[1] < self.height

    def move(self, pos, direction: str):
        # walls win. never letting a rover clip out and corrupt the sim state
        if direction not in MOVES:
            return pos, False  # nonsense direction, rover just idles this tick
        dx, dy = MOVES[direction]
        nxt = (pos[0] + dx, pos[1] + dy)
        if self.in_bounds(nxt):
            return nxt, True
        return pos, False  # bumped the wall, stay put

    def astar(self, start, goal, blocked=frozenset()):
        # real a-star: heapq open set, manhattan heuristic, 4 directions.
        # trash tiles are walkable, only the walls (or the blocked set) stop you
        if not self.in_bounds(start) or not self.in_bounds(goal):
            return None
        if start in blocked or goal in blocked:
            return None
        g_score = {start: 0}
        came_from = {}
        open_heap = [(manhattan(start, goal), 0, start)]
        while open_heap:
            _, g, cur = heapq.heappop(open_heap)
            if cur == goal:
                # walk the chain backwards to rebuild the full path
                path = [cur]
                while cur in came_from:
                    cur = came_from[cur]
                    path.append(cur)
                return path[::-1]
            if g > g_score.get(cur, float("inf")):
                continue  # stale heap entry, we already found a cheaper way here
            for dx, dy in MOVES.values():
                nxt = (cur[0] + dx, cur[1] + dy)
                if not self.in_bounds(nxt) or nxt in blocked:
                    continue
                ng = g + 1
                if ng < g_score.get(nxt, float("inf")):
                    g_score[nxt] = ng
                    came_from[nxt] = cur
                    heapq.heappush(open_heap, (ng + manhattan(nxt, goal), ng, nxt))
        return None  # unreachable, only happens when the goal is fully walled off

    def render(self, rovers=()) -> str:
        # ascii dump for the terminal. the pygame view handles the pretty stuff
        canvas = [["." for _ in range(self.width)] for _ in range(self.height)]
        for x, y in self.trash:
            canvas[int(y)][int(x)] = "#"
        for i, r in enumerate(rovers):
            x, y = r.pos
            canvas[int(y)][int(x)] = str(i + 1)
        return "\n".join("".join(row) for row in canvas)

    @property
    def trash_left(self) -> int:
        return int(self.trash.shape[0])