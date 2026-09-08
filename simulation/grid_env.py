from dataclasses import dataclass

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


@dataclass
class Rover:
    # dumb container on purpose. the smart stuff lives in core/
    name: str
    pos: tuple
    collected: int = 0
    stalls: int = 0
    moves: int = 0


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
        # one vectorized hypot instead of a python loop over every trash item. numpy carries
        if self.trash.size == 0:
            return []
        dists = np.hypot(self.trash[:, 0] - pos[0], self.trash[:, 1] - pos[1])
        close = dists <= radius
        if not close.any():
            return []
        coords = self.trash[close]
        picked = dists[close]
        # nearest first, capped, so the llm prompt stays small and actually useful
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
            return pos, False  # model said some nonsense, rover just idles this tick
        dx, dy = MOVES[direction]
        nxt = (pos[0] + dx, pos[1] + dy)
        if self.in_bounds(nxt):
            return nxt, True
        return pos, False  # bumped the wall, stay put

    def render(self, rovers=()) -> str:
        # ascii dump for the terminal. proper viz comes later, this one is free
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