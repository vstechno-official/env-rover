import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import imageio

from core.swarm_async import SwarmSim
from simulation import visualizer

FRAMES = 100
OUT = Path(__file__).resolve().parent / "assets" / "demo.gif"


async def record(frames=FRAMES, out=OUT, seed=11, respawn=(20, 8)):
    # headless render, offline allocator, fixed seed = a gif anyone can reproduce
    visualizer.init(headless=True)
    sim = SwarmSim(live=False, seed=seed, respawn=respawn)
    surface = visualizer.build_surface(sim.env.width, sim.env.height)
    shots = []
    for i in range(frames):
        await sim.tick()
        visualizer.draw(sim, surface)
        shots.append(visualizer.snapshot(surface))
        if (i + 1) % 20 == 0:
            print(f"  captured {i + 1}/{frames} frames, trash left {sim.env.trash_left}")
    imageio.v3.imwrite(str(out), shots, duration=100, loop=0)
    print(f"gif saved: {out} ({out.stat().st_size / 1e6:.2f} mb)")
    print(f"rovers scooped {sum(r.collected for r in sim.rovers)} trash across {frames} ticks")
    return sim


def main():
    try:
        asyncio.run(record())
    except KeyboardInterrupt:
        print("\nctrl-c, bailing out of the gif run")


if __name__ == "__main__":
    main()