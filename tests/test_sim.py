import asyncio
import contextlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import llm_brain
from core.swarm_async import main as swarm_main
from simulation.grid_env import GridEnv, Rover

FAILS = []


def check(label, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {label}{(' | ' + extra) if extra and not cond else ''}")
    if not cond:
        FAILS.append(label)


# ---- grid env ----
print("== grid_env ==")
env = GridEnv(24, 24, seed=42)
spawned = env.spawn_trash(40)
check("spawned exactly 40", spawned == 40, f"got {spawned}")
check("trash_left matches", env.trash_left == 40)
check("no dupes in trash", len({tuple(c) for c in env.trash}) == env.trash_left)
env.spawn_trash(700)
check("overflow guard caps spawn", env.trash_left <= 24 * 24, f"got {env.trash_left}")

env2 = GridEnv(24, 24, seed=7)
env2.spawn_trash(40)
nb = env2.nearby_trash((12, 12), radius=6, limit=8)
check("nearby sorted nearest-first", all(nb[i][2] <= nb[i + 1][2] for i in range(len(nb) - 1)))
check("nearby capped at limit", len(nb) <= 8)
check("nearby radius respected", all(d <= 6 for _, _, d in nb))
check("empty-sensor corner", env2.nearby_trash((0, 0), radius=0) == [])

pos, ok = env2.move((5, 5), "RIGHT")
check("move RIGHT works", pos == (6, 5) and ok)
pos, ok = env2.move((0, 3), "LEFT")
check("wall blocks at x=0", pos == (0, 3) and not ok)
pos, ok = env2.move((0, 0), "UP")
check("wall blocks at y=0", pos == (0, 0) and not ok)
pos, ok = env2.move((23, 23), "DOWN")
check("wall blocks at max", pos == (23, 23) and not ok)
pos, ok = env2.move((3, 3), "JUMP")
check("garbage dir = stay put", pos == (3, 3) and not ok)

t = env2.nearby_trash((12, 12), radius=6)
tx, ty = t[0][0], t[0][1]
check("collect only on tile", env2.collect((tx + 1 if tx + 1 < 24 else tx - 1, ty)) is False)
check("collect on tile works", env2.collect((tx, ty)) is True)
check("collect decrements", env2.trash_left == 39)

r = Rover(name="t", pos=(0, 0))
art = env2.render([r])
check("render is height lines", len(art.splitlines()) == 24)
check("render line width ok", all(len(l) == 24 for l in art.splitlines()))
check("render shows rover digit", art.splitlines()[0][0] == "1")


# ---- llm brain parser ----
print("== llm_brain ==")
check("clean json", llm_brain._parse_move('{"move": "up", "reason": "trash north"}') == ("UP", "trash north"))
check("fenced json", llm_brain._parse_move('```json\n{"move": "LEFT", "reason": "x"}\n```')[0] == "LEFT")
check("junk text", llm_brain._parse_move("the rover should go up")[0] is None)
check("illegal move", llm_brain._parse_move('{"move": "TELEPORT"}')[0] is None)
check("json list not dict", llm_brain._parse_move("[1,2,3]")[0] is None)
check("json string not dict", llm_brain._parse_move('"go up"')[0] is None)
check("empty reply", llm_brain._parse_move("")[0] is None)
check("reason truncates", len(llm_brain._parse_move('{"move": "UP", "reason": "' + "x" * 200 + '"')[1]) <= 80)
check("greedy homes on trash", llm_brain._greedy_move((5, 5), [(8, 5, 3.0)]) in ("RIGHT",))
check("greedy vertical", llm_brain._greedy_move((5, 5), [(5, 9, 4.0)]) == "DOWN")
check("greedy wanders solo", llm_brain._greedy_move((5, 5), []) in llm_brain.VALID_MOVES)
check("missing reason ok", llm_brain._parse_move('{"move": "RIGHT"}') == ("RIGHT", ""))


# ---- fake gemini clients (shape matches client.aio.models.generate_content) ----
print("== swarm async (fake gemini) ==")


class FakeResp:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, behavior, latency=0.0):
        self.behavior = behavior
        self.latency = latency
        self.calls = 0

    async def generate_content(self, model, contents, config=None):
        self.calls += 1
        if self.latency:
            await asyncio.sleep(self.latency)
        if self.behavior == "fail":
            raise RuntimeError("simulated 429")
        if self.behavior == "nonsense":
            return FakeResp("i think the rover should fly")
        if self.behavior == "smart":
            payload = json.loads(contents)
            trash = [(t["x"], t["y"], t["dist"]) for t in payload["trash_nearby"]]
            move = llm_brain._greedy_move((payload["rover"]["x"], payload["rover"]["y"]), trash)
            return FakeResp(json.dumps({"move": move, "reason": "smart fake brain"}))
        return FakeResp('{"move": "RIGHT", "reason": "fake brain says so"}')


class FakeAio:
    def __init__(self, behavior, latency=0.0):
        self.models = FakeModels(behavior, latency)


class FakeClient:
    def __init__(self, behavior="ok", latency=0.0):
        self.aio = FakeAio(behavior, latency)


async def scenario_concurrent():
    ok = llm_brain.ask_brain((2, 2), [(9, 2, 7.0)], client=FakeClient("ok"))
    bad = llm_brain.ask_brain((1, 1), [], client=FakeClient("fail"))
    return await asyncio.gather(ok, bad)


r1, r2 = asyncio.run(scenario_concurrent())
check("valid move returned", r1[0] == "RIGHT", str(r1))
check("api error falls back greedy", r2[0] in llm_brain.VALID_MOVES and "error" in r2[1], str(r2))
check("no real client touched", llm_brain._client is None)


async def scenario_nonsense():
    return await llm_brain.ask_brain((3, 3), [(6, 3, 3.0)], client=FakeClient("nonsense"))


r4 = asyncio.run(scenario_nonsense())
check("nonsense reply falls back", r4[0] in llm_brain.VALID_MOVES and "greedy" in r4[1].lower(), str(r4))


async def scenario_offline():
    llm_brain._client = None
    saved = os.environ.pop("GOOGLE_API_KEY", None)
    try:
        return await llm_brain.ask_brain((2, 2), [(10, 2, 8.0)])
    finally:
        llm_brain._client = None
        if saved is not None:
            os.environ["GOOGLE_API_KEY"] = saved


r5 = asyncio.run(scenario_offline())
check("offline mode greedy", r5[0] in llm_brain.VALID_MOVES and "offline" in r5[1].lower(), str(r5))

# ---- full sim runs, zero network (get_client patched) ----
print("== full swarm sim, online path (fake gemini, 30ms latency) ==")
orig_get_client = llm_brain.get_client
smart = FakeClient("smart", latency=0.03)
llm_brain.get_client = lambda: smart
buf = io.StringIO()
t0 = time.time()
with contextlib.redirect_stdout(buf):
    asyncio.run(swarm_main())
dt = time.time() - t0
llm_brain.get_client = orig_get_client
out = buf.getvalue()
check("90 brain calls made (3 rovers x 30 ticks)", smart.aio.models.calls == 90, f"got {smart.aio.models.calls}")
collected = sum(int(m) for m in re.findall(r"(\d+) trash scooped", out))
check("rovers actually collected trash", collected > 0, f"got {collected}")
check("ticks overlapped (async, not sequential)", dt < 2.0, f"took {dt:.2f}s")
print(f"  [info] smart-fake sim: {collected} trash collected in {dt:.2f}s")

print("== full swarm sim, offline path ==")
llm_brain.get_client = lambda: None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    asyncio.run(swarm_main())
llm_brain.get_client = orig_get_client
out = buf.getvalue()
check("offline banner shown", "offline mode" in out)
check("offline sim completed", "trash left on the grid" in out)

print(f"\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)