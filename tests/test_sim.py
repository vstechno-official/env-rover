import asyncio
import contextlib
import io
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from core import llm_brain
from core.swarm_async import SwarmSim
from simulation import grid_env as ge
from simulation import visualizer

FAILS = []
TMP = Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "envrover-tests"


def check(label, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {label}{(' | ' + extra) if extra and not cond else ''}")
    if not cond:
        FAILS.append(label)


# ---- manhattan + a-star ----
print("== grid_env: manhattan + a-star ==")
check("manhattan basic", ge.manhattan((0, 0), (3, 4)) == 7)
check("manhattan symmetric", ge.manhattan((10, 10), (4, 2)) == ge.manhattan((4, 2), (10, 10)))

env = ge.GridEnv(24, 24, seed=42)
env.spawn_trash(40)
p = env.astar((0, 0), (3, 4))
check("astar start->goal nodes", p[0] == (0, 0) and p[-1] == (3, 4))
check("astar optimal = manhattan steps", len(p) == ge.manhattan((0, 0), (3, 4)) + 1)
check("astar start==goal", env.astar((5, 5), (5, 5)) == [(5, 5)])
check("astar every step is 1 tile", all(ge.manhattan(p[i], p[i + 1]) == 1 for i in range(len(p) - 1)))
check("astar stays in bounds", all(env.in_bounds(t) for t in p))
check("astar out of bounds -> None", env.astar((0, 0), (99, 99)) is None)

blocked = {(1, 0)}
p2 = env.astar((0, 0), (2, 0), blocked=blocked)
check("astar detours around blocked", p2 is not None and not any(t in blocked for t in p2))
check("detour length sane", len(p2) == 5, f"got {len(p2)}")

ring = {(1, 2), (2, 1), (3, 2), (2, 3)}
check("astar unreachable -> None", env.astar((0, 0), (2, 2), blocked=ring) is None)
check("astar goal blocked -> None", env.astar((0, 0), (1, 2), blocked={(1, 2)}) is None)


def bfs_len(start, goal, blocked=frozenset()):
    # reference shortest path so we can hold a-star accountable
    seen = {start}
    q = deque([(start, 0)])
    while q:
        cur, d = q.popleft()
        if cur == goal:
            return d
        for dx, dy in ge.MOVES.values():
            nxt = (cur[0] + dx, cur[1] + dy)
            if env.in_bounds(nxt) and nxt not in seen and nxt not in blocked:
                seen.add(nxt)
                q.append((nxt, d + 1))
    return None


rng = np.random.default_rng(3)
agree = True
for _ in range(30):
    a = tuple(int(v) for v in rng.integers(0, 24, 2))
    b = tuple(int(v) for v in rng.integers(0, 24, 2))
    blk = {(int(x), int(y)) for x, y in rng.integers(0, 24, (12, 2))}
    blk.discard(a)
    blk.discard(b)
    star = env.astar(a, b, blocked=blk)
    ref = bfs_len(a, b, blocked=blk)
    if ref is None:
        agree &= star is None
    else:
        agree &= star is not None and len(star) - 1 == ref
check("astar optimal vs bfs (30 random cases)", agree)

# rover dataclass fields
r = ge.Rover(name="t", pos=(1, 1))
r.target = (2, 2)
r.path = [(1, 2), (2, 2)]
r.trail.append((1, 1))
check("rover carries target/path/trail", r.target == (2, 2) and len(r.path) == 2 and r.trail == [(1, 1)])

# ---- allocator ----
print("== llm_brain: gemini task allocator ==")
trash = [(3, 7), (10, 2), (20, 20)]
g = llm_brain.greedy_assignment({"rover-1": (3, 6), "rover-2": (10, 3), "rover-3": (19, 19)}, trash)
check("greedy picks nearest", g["rover-1"] == (3, 7) and g["rover-2"] == (10, 2) and g["rover-3"] == (20, 20))
check("greedy no dupes", len(set(g.values())) == 3)
g2 = llm_brain.greedy_assignment({"rover-1": (0, 0), "rover-2": (0, 0)}, trash)
check("greedy breaks ties without dupes", g2["rover-1"] != g2["rover-2"])
g3 = llm_brain.greedy_assignment({"rover-1": (0, 0)}, [])
check("greedy no trash -> None", g3["rover-1"] is None)
check("extract dict form", llm_brain._extract_coord({"x": 3, "y": 7}) == (3, 7))
check("extract list form", llm_brain._extract_coord([3, 7]) == (3, 7))
check("extract junk -> None", llm_brain._extract_coord("up") is None)


class FakeResp:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0

    async def generate_content(self, model, contents, config=None):
        self.calls += 1
        if self.behavior == "fail":
            raise RuntimeError("simulated 429")
        if self.behavior == "garbage":
            return FakeResp("rover one should take the trash near the corner")
        if self.behavior == "hallucinate":
            return FakeResp(json.dumps({"rover-1": {"x": 50, "y": 50}, "rover-2": {"x": 3, "y": 7}}))
        if self.behavior == "dupe":
            return FakeResp(json.dumps({"rover-1": {"x": 3, "y": 7}, "rover-2": {"x": 3, "y": 7}}))
        if self.behavior == "fenced":
            return FakeResp('```json\n{"rover-1": {"x": 3, "y": 7}, "rover-2": {"x": 10, "y": 2}}\n```')
        payload = json.loads(contents)
        rovers = {r["name"]: (r["x"], r["y"]) for r in payload["rovers"]}
        assigns = llm_brain.greedy_assignment(rovers, [(t["x"], t["y"]) for t in payload["trash"]])
        return FakeResp(json.dumps({n: {"x": c[0], "y": c[1]} if c else None for n, c in assigns.items()}))


class FakeClient:
    def __init__(self, behavior):
        class aio:
            models = FakeModels(behavior)

        self.aio = aio()


async def alloc(behavior, rovers, trash):
    return await llm_brain.allocate_tasks(rovers, trash, client=FakeClient(behavior))


rovers = {"rover-1": (3, 6), "rover-2": (10, 3)}
r = asyncio.run(alloc("smart", rovers, trash))
check("gemini async round trip", r == {"rover-1": (3, 7), "rover-2": (10, 2)}, str(r))
r = asyncio.run(alloc("fenced", rovers, trash))
check("markdown fences tolerated", r["rover-1"] == (3, 7) and r["rover-2"] == (10, 2))
r = asyncio.run(alloc("fail", rovers, trash))
check("api throttle -> greedy fallback", r["rover-1"] in trash and r["rover-2"] in trash and r["rover-1"] != r["rover-2"])
r = asyncio.run(alloc("garbage", rovers, trash))
check("garbage reply -> greedy fallback", r["rover-1"] in trash and r["rover-2"] in trash)
r = asyncio.run(alloc("hallucinate", rovers, trash))
check("hallucinated coords rejected", r["rover-1"] in trash and r["rover-2"] in trash and r["rover-1"] != r["rover-2"], str(r))
r = asyncio.run(alloc("dupe", rovers, trash))
check("dupe assignment patched", r["rover-1"] != r["rover-2"] and r["rover-1"] in trash and r["rover-2"] in trash)
r = asyncio.run(llm_brain.allocate_tasks(rovers, []))
check("no trash left -> None targets", r == {"rover-1": None, "rover-2": None})
llm_brain._client = None
saved = os.environ.pop("GOOGLE_API_KEY", None)
try:
    r = asyncio.run(llm_brain.allocate_tasks(rovers, trash))
finally:
    llm_brain._client = None
    if saved is not None:
        os.environ["GOOGLE_API_KEY"] = saved
check("offline -> greedy", r["rover-1"] in trash and r["rover-2"] in trash)

# ---- swarm engine ----
print("== SwarmSim: allocator + a-star driving ==")


async def run_sim(ticks, seed=7, respawn=None, live=False):
    sim = SwarmSim(live=live, seed=seed, respawn=respawn)
    await sim.run(ticks)
    return sim


sim = asyncio.run(run_sim(200))
check("swarm cleans the whole grid", sim.env.trash_left == 0, f"left {sim.env.trash_left} after {sim.tick_count} ticks")
check("cleaned before tick cap", sim.tick_count <= 200)
check("all rovers in bounds", all(sim.env.in_bounds(r.pos) for r in sim.rovers))
check("scoops add up", sum(r.collected for r in sim.rovers) == sim.spawned)
print(f"  [info] full clean took {sim.tick_count} ticks, {[(r.name, r.collected) for r in sim.rovers]}")

sim2 = asyncio.run(run_sim(100, seed=11, respawn=(20, 8)))
check("respawn keeps the world dirty", sim2.env.trash_left > 0)
check("respawn inflates spawned count", sim2.spawned > 40)
check("100 ticks stay in bounds", all(sim2.env.in_bounds(r.pos) for r in sim2.rovers))

sim3 = SwarmSim(seed=3)
for _ in range(10):
    asyncio.run(sim3.tick())
paths_held = [r.path for r in sim3.rovers]
check("rovers actually hold a-star paths", any(paths_held) or all(r.target is None for r in sim3.rovers))
check("trail capped at 14", all(len(r.trail) <= 14 for r in sim3.rovers))

sim4 = SwarmSim(seed=5)
asyncio.run(sim4.tick())
check("tick increments", sim4.tick_count == 1)
before = {r.name: r.target for r in sim4.rovers}
asyncio.run(sim4.tick())
after = {r.name: r.target for r in sim4.rovers}
check("targets persist while valid", any(before[n] == after[n] and after[n] is not None for n in before))

# ---- visualizer (headless) ----
print("== visualizer (headless) ==")
visualizer.init(headless=True)
sim5 = SwarmSim(seed=9)
frame = visualizer.render_frame(sim5)
exp_h = visualizer.HUD_H + 24 * visualizer.TILE + visualizer.PAD + visualizer.FOOTER_H
exp_w = 2 * visualizer.PAD + 24 * visualizer.TILE
check("frame pixel size", frame.shape == (exp_h, exp_w, 3), str(frame.shape))
check("frame not blank", int(frame.std()) > 5)

simA = SwarmSim(seed=21)
simB = SwarmSim(seed=21)
fa, fb = None, None
for _ in range(5):
    asyncio.run(simA.tick())
    asyncio.run(simB.tick())
fa = visualizer.render_frame(simA)
fb = visualizer.render_frame(simB)
check("render is deterministic", np.array_equal(fa, fb))

shots = []
simV = SwarmSim(seed=11, respawn=(20, 8))
surface = visualizer.build_surface(simV.env.width, simV.env.height)
for _ in range(20):
    asyncio.run(simV.tick())
    visualizer.draw(simV, surface)
    shots.append(visualizer.snapshot(surface))
check("20 headless frames rendered", len(shots) == 20 and all(s.shape == (exp_h, exp_w, 3) for s in shots))

# ---- gif pipeline (tiny run, real codec) ----
print("== gif pipeline ==")
TMP.mkdir(exist_ok=True)
gif_path = TMP / "test_demo.gif"
import generate_gif


async def record_small():
    return await generate_gif.record(frames=12, out=gif_path, seed=9)


asyncio.run(record_small())
check("gif file written", gif_path.exists() and gif_path.stat().st_size > 1000)
import imageio.v3 as iio

gif_frames = iio.imread(str(gif_path))
check("gif readable, 12 frames", gif_frames.shape[0] == 12, str(gif_frames.shape))
gif_path.unlink()

print(f"\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)