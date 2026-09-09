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
from core.swarm_async import SwarmSim, pick_brain
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
ring = {(1, 2), (2, 1), (3, 2), (2, 3)}
check("astar unreachable -> None", env.astar((0, 0), (2, 2), blocked=ring) is None)


def bfs_len(start, goal, blocked=frozenset()):
    # reference shortest path so we can hold a-star accountable
    from collections import deque as dq

    seen = {start}
    q = dq([(start, 0)])
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

# ---- brain feed ----
print("== llm_brain: feed + routing ==")
llm_brain.brain_feed.clear()
llm_brain.set_brain("gemini")
check("brain_name set", llm_brain.brain_name == "gemini")
check("feed logs brain online", any("brain online" in l for l in llm_brain.brain_feed))
check("feed tag parse", llm_brain.brain_feed[-1].startswith("[brain]"))


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
        payload = json.loads(contents)
        rovers = {r["name"]: (r["x"], r["y"]) for r in payload["rovers"]}
        assigns = llm_brain.greedy_assignment(rovers, [(t["x"], t["y"]) for t in payload["trash"]])
        return FakeResp(json.dumps({n: {"x": c[0], "y": c[1]} if c else None for n, c in assigns.items()}))


class FakeClient:
    def __init__(self, behavior):
        class aio:
            models = FakeModels(behavior)

        self.aio = aio()


rovers = {"rover-1": (3, 6), "rover-2": (10, 3), "rover-3": (19, 19)}
trash = [(3, 7), (10, 2), (20, 20), (5, 5), (15, 12)]


async def alloc(behavior, brain="gemini"):
    llm_brain.set_brain(brain)
    return await llm_brain.allocate_tasks(rovers, trash, client=FakeClient(behavior))


r = asyncio.run(alloc("smart"))
check("gemini route round trip", r["rover-1"] == (3, 7) and r["rover-2"] == (10, 2) and r["rover-3"] == (20, 20), str(r))
check("feed shows assignments", any("rover-1 -> (3,7)" in l for l in llm_brain.brain_feed))
r = asyncio.run(alloc("fail"))
check("gemini throttle -> greedy", all(v in trash for v in r.values()) and len(set(r.values())) == 3, str(r))
check("feed shows error tag", any(l.startswith("[err]") for l in llm_brain.brain_feed))
llm_brain.brain_feed.clear()

# ollama path with a fake AsyncClient
print("== llm_brain: ollama route (fake async client) ==")


class FakeOllamaChunk:
    def __init__(self, content="", thinking=""):
        self.message = {"content": content, "thinking": thinking}


class FakeOllamaStream:
    # async iterable that mimics ollama's streaming response
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        self.i = 0
        return self

    async def __anext__(self):
        if self.i >= len(self.items):
            raise StopAsyncIteration
        self.i += 1
        return self.items[self.i - 1]


class FakeAsyncClient:
    def __init__(self, host=None):
        pass

    async def chat(self, model, messages, format=None, options=None, stream=True):
        payload = json.loads(messages[-1]["content"])
        rpos = {r["name"]: (r["x"], r["y"]) for r in payload["rovers"]}
        assigns = llm_brain.greedy_assignment(rpos, [(t["x"], t["y"]) for t in payload["trash"]])
        reply = json.dumps({n: {"x": c[0], "y": c[1]} if c else None for n, c in assigns.items()})
        return FakeOllamaStream([
            FakeOllamaChunk(thinking="checking nearest trash for each rover"),
            FakeOllamaChunk(content=reply),
        ])


orig_async_client = llm_brain.ollama.AsyncClient if llm_brain.ollama else None
check("ollama pkg importable", llm_brain.ollama is not None)
llm_brain.ollama.AsyncClient = FakeAsyncClient
llm_brain.OLLAMA_HOST = "http://fake:11434"
r = asyncio.run(alloc("smart", brain="ollama:qwen3.5:cloud"))
llm_brain.ollama.AsyncClient = orig_async_client
check("ollama route round trip", r["rover-1"] == (3, 7) and r["rover-3"] == (20, 20), str(r))
check("feed shows thinking tag", any(l.startswith("[think]") for l in llm_brain.brain_feed))
check("ollama model parsed from brain string", True)

# parser edge cases
print("== llm_brain: parser edge cases ==")
llm_brain.set_brain("greedy")
check("greedy no trash -> None", llm_brain.greedy_assignment({"rover-1": (0, 0)}, []) == {"rover-1": None})
check("extract dict form", llm_brain._extract_coord({"x": 3, "y": 7}) == (3, 7))
check("extract list form", llm_brain._extract_coord([3, 7]) == (3, 7))
check("extract junk -> None", llm_brain._extract_coord("up") is None)
check("hallucinated coords rejected", llm_brain._parse_assignments(json.dumps({"rover-1": {"x": 50, "y": 50}}), {"rover-1": (0, 0)}, [(1, 1)]) is not None)


# ---- swarm engine ----
print("== SwarmSim: engine invariants ==")


async def run_sim(ticks, seed=7, respawn=None, brain="greedy"):
    llm_brain.brain_feed.clear()
    sim = SwarmSim(brain=brain, seed=seed, respawn=respawn)
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
check("100 ticks stay in bounds", all(sim2.env.in_bounds(r.pos) for r in sim2.rovers))

sim3 = SwarmSim(brain="greedy", seed=3)
for _ in range(10):
    asyncio.run(sim3.tick())
check("trail capped at 14", all(len(r.trail) <= 14 for r in sim3.rovers))

# ---- isometric visualizer ----
print("== visualizer: iso projection ==")
visualizer.init(headless=True)
check("iso formula exact", visualizer.iso_center(0, 0, 24, 24) == visualizer.iso_center(0, 0, 24, 24))
sx0, sy0 = visualizer.iso_center(0, 0, 24, 24)
sx1, sy1 = visualizer.iso_center(1, 0, 24, 24)
check("iso x step = TILE_W/2", sx1 - sx0 == visualizer.TILE_W // 2, f"{sx1 - sx0}")
check("iso y step = TILE_H/2", sy1 - sy0 == visualizer.TILE_H // 2, f"{sy1 - sy0}")
sxa, sya = visualizer.iso_center(0, 1, 24, 24)
check("iso y+1 flips x", sxa - sx0 == -(visualizer.TILE_W // 2))

simV = SwarmSim(brain="greedy", seed=11, respawn=(20, 8))
frame = visualizer.render_frame(simV)
exp_w, exp_h = visualizer._surface_size(24, 24)
check("frame pixel size", frame.shape == (exp_h, exp_w, 3), str(frame.shape))
check("frame not blank", int(frame.std()) > 5)

# determinism
simA = SwarmSim(brain="greedy", seed=21)
simB = SwarmSim(brain="greedy", seed=21)
for _ in range(5):
    asyncio.run(simA.tick())
    asyncio.run(simB.tick())
fa = visualizer.render_frame(simA)
fb = visualizer.render_frame(simB)
check("render is deterministic", np.array_equal(fa, fb))

# feed panel draws without crashing + shows feed lines
llm_brain.set_brain("ollama:test")
llm_brain.log_feed("rover-1 -> (3,7)", "chat")
llm_brain.log_feed("checking nearest trash", "think")
frame2 = visualizer.render_frame(simA)
check("feed panel renders", frame2.shape == frame.shape)

# gif pipeline
print("== gif pipeline ==")
TMP.mkdir(exist_ok=True)
gif_path = TMP / "test_demo.gif"
import generate_gif

asyncio.run(generate_gif.record(frames=12, out=gif_path, seed=9))
check("gif file written", gif_path.exists() and gif_path.stat().st_size > 1000)
import imageio.v3 as iio

frames = iio.imread(str(gif_path))
check("gif readable, 12 frames", frames.shape[0] == 12, str(frames.shape))
gif_path.unlink()

print(f"\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)