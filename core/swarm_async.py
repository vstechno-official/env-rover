import asyncio
import sys
from pathlib import Path

# so `python core/swarm_async.py` works from the repo root without -m package weirdness
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import llm_brain
from simulation.grid_env import GridEnv, Rover

GRID_W, GRID_H = 24, 24
ROVER_NAMES = ("rover-1", "rover-2", "rover-3")
TOTAL_TRASH = 40
MAX_TICKS = 30
SENSOR_RADIUS = 6


async def run_rover(rover, env, ticks):
    # one loop per rover. gemini api is slow so we async this, all 3 rovers fire
    # their brain calls at the same time instead of queueing one after another
    for tick in range(1, ticks + 1):
        trash = env.nearby_trash(rover.pos, radius=SENSOR_RADIUS)
        move, reason = await llm_brain.ask_brain(rover.pos, trash)

        new_pos, moved = env.move(rover.pos, move)
        rover.pos = new_pos
        rover.moves += 1
        if not moved:
            rover.stalls += 1  # hit a wall. model needs to learn to look around
        if env.collect(rover.pos):
            rover.collected += 1

        print(f"[{rover.name}] tick {tick:02d} @ {rover.pos} -> {move} | {reason}")

        # no locks anywhere btw: event loop is single threaded and none of the
        # grid reads/writes above await mid-mutation, so the shared env cant get corrupted
    return rover


async def main():
    env = GridEnv(GRID_W, GRID_H)  # pass a seed for a repeatable world
    spawned = env.spawn_trash(TOTAL_TRASH)

    rovers = []
    for i, name in enumerate(ROVER_NAMES):
        # spread the spawns so they arent all dogpiling one corner on tick 1
        x = (i + 1) * (GRID_W // (len(ROVER_NAMES) + 1))
        y = (i + 1) * (GRID_H // (len(ROVER_NAMES) + 1))
        rovers.append(Rover(name=name, pos=(x, y)))

    if llm_brain.get_client() is None:
        print("no GOOGLE_API_KEY in .env, running offline mode (greedy fallback, no llm calls)")
    else:
        print(f"brain online: {llm_brain.DEFAULT_MODEL}")
    print(f"spawned {spawned} trash on a {GRID_W}x{GRID_H} grid, {len(rovers)} rovers dropping in\n")
    print(env.render(rovers) + "\n")

    # gather = all 3 rovers run concurrently, we just wait for everyone to finish
    done = await asyncio.gather(*(run_rover(r, env, MAX_TICKS) for r in rovers))

    print("\nfinal grid:")
    print(env.render(done))
    print(f"\nresults after {MAX_TICKS} ticks")
    for r in done:
        print(f"  {r.name}: {r.collected} trash scooped, {r.moves} moves, {r.stalls} stalls")
    print(f"  trash left on the grid: {env.trash_left}/{spawned}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # ctrl c mid sim, bail clean instead of dumping a traceback
        print("\nctrl-c, bailing out of the sim")