import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import llm_brain
from simulation.grid_env import DIR_NAMES, GridEnv, Rover

GRID_W, GRID_H = 24, 24
ROVER_NAMES = ("rover-1", "rover-2", "rover-3")
TOTAL_TRASH = 40
MAX_TICKS = 80


class SwarmSim:
    # the whole swarm in one object so the cli, the visualizer and the gif
    # generator all run the exact same sim
    def __init__(self, width=GRID_W, height=GRID_H, trash=TOTAL_TRASH, live=False, seed=None, respawn=None):
        self.env = GridEnv(width, height, seed=seed)
        self.spawned = self.env.spawn_trash(trash)
        self.respawn = respawn  # (every_n_ticks, count) so demo runs never go boring
        self.live = live  # live=True pings gemini for allocations, else greedy all day
        self.tick_count = 0
        self.rovers = []
        for i, name in enumerate(ROVER_NAMES):
            # spread the spawns so they arent all dogpiling one corner on tick 1
            x = (i + 1) * (width // (len(ROVER_NAMES) + 1))
            y = (i + 1) * (height // (len(ROVER_NAMES) + 1))
            self.rovers.append(Rover(name=name, pos=(x, y)))

    def _trash_set(self):
        return {(int(t[0]), int(t[1])) for t in self.env.trash}

    def _target_valid(self, rover):
        # another rover can scoop my trash by walking over it, so targets die mid-drive
        return rover.target is not None and rover.target in self._trash_set()

    async def _allocate(self):
        # one gemini call hands out one target to every rover that needs one
        needing = {r.name: r.pos for r in self.rovers if not self._target_valid(r)}
        if not needing:
            return
        claimed = {r.target for r in self.rovers if self._target_valid(r)}
        free_trash = [t for t in self._trash_set() if t not in claimed]
        if self.live:
            assignments = await llm_brain.allocate_tasks(needing, free_trash)
        else:
            # a-star handles the actual driving so we dont burn gemini tokens
            assignments = llm_brain.greedy_assignment(needing, free_trash)
        for rover in self.rovers:
            if rover.name in assignments:
                self._assign(rover, assignments[rover.name])

    def _assign(self, rover, target):
        # a-star handles the actual driving so we dont burn gemini tokens
        rover.target = target
        rover.path = []
        if target is not None:
            full = self.env.astar(rover.pos, target)
            rover.path = list(full[1:]) if full else []

    async def tick(self):
        # one heartbeat: top up targets, drive every rover one step, scoop
        self.tick_count += 1
        if self.respawn and self.tick_count % self.respawn[0] == 0:
            # the world keeps getting dirty so the demo loop never dies
            self.spawned += self.env.spawn_trash(self.respawn[1])
        await self._allocate()
        for rover in self.rovers:
            if not self._target_valid(rover):
                rover.target = None
                rover.path = []
            if rover.path:
                nxt = rover.path.pop(0)
                delta = (int(nxt[0]) - rover.pos[0], int(nxt[1]) - rover.pos[1])
                if delta in DIR_NAMES:
                    rover.pos, moved = self.env.move(rover.pos, DIR_NAMES[delta])
                    rover.moves += 1 if moved else 0
                else:
                    rover.stalls += 1  # stale path entry, shouldnt happen, just skip it
            rover.trail.append(rover.pos)
            if len(rover.trail) > 14:
                rover.trail.pop(0)
            if self.env.collect(rover.pos):
                rover.collected += 1
                for other in self.rovers:
                    if other.target == rover.pos:
                        # my trash got scooped from under me, need a new job
                        other.target = None
                        other.path = []

    async def run(self, ticks, on_frame=None, stop_when_clean=True):
        for _ in range(ticks):
            await self.tick()
            if on_frame is not None:
                on_frame(self)
            if stop_when_clean and self.env.trash_left == 0:
                break


async def main():
    live = llm_brain.get_client() is not None
    if live:
        print(f"brain online: {llm_brain.DEFAULT_MODEL} allocates, a-star drives")
    else:
        print("no GOOGLE_API_KEY in .env, running offline mode (greedy allocator, zero llm calls)")
    sim = SwarmSim(live=live, seed=7)
    print(f"spawned {sim.spawned} trash on a {sim.env.width}x{sim.env.height} grid, {len(sim.rovers)} rovers dropping in\n")
    print(sim.env.render(sim.rovers) + "\n")

    def line(s):
        parts = []
        for r in s.rovers:
            bits = f"{r.name} @{r.pos}"
            if r.target:
                bits += f" -> {r.target}"
            parts.append(bits)
        print(f"[tick {s.tick_count:02d}] " + " | ".join(parts) + f" | trash left {s.env.trash_left}")

    await sim.run(MAX_TICKS, on_frame=line)
    print("\nfinal grid:")
    print(sim.env.render(sim.rovers))
    print(f"\nresults after {sim.tick_count} ticks")
    for r in sim.rovers:
        print(f"  {r.name}: {r.collected} trash scooped, {r.moves} moves")
    print(f"  trash left on the grid: {sim.env.trash_left}/{sim.spawned}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # ctrl c mid sim, bail clean instead of dumping a traceback
        print("\nctrl-c, bailing out of the sim")