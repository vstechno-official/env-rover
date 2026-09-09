import json
import os
import subprocess
from collections import deque

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None  # sdk not installed = gemini path disabled, ollama + greedy still fine

try:
    import ollama
except ImportError:
    ollama = None  # no ollama pkg/instance = local path disabled, gemini + greedy still fine

# keys go in .env (see .env.example). never commit the real one lol
load_dotenv()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

SYSTEM_PROMPT = (
    "you are the task allocator for a swarm of trash-collecting rovers on a 2d grid. "
    "you get json with 'rovers' (name + position) and 'trash' (coordinates still on the grid). "
    "assign exactly one trash target to each rover. spread them out, never send two rovers "
    "after the same trash, prefer trash that is close to each rover. "
    'reply with json only, exactly like {"rover-1": {"x": 3, "y": 7}, "rover-2": {"x": 11, "y": 2}}. '
    "every x and y is an integer and must come from the trash list."
)

# global rolling feed of what the brain is saying/thinking. the visualizer just
# blits whatever lands here, so the whole app feels like its thinking out loud
brain_feed = deque(maxlen=60)
brain_name = "greedy"


def log_feed(text, tag="sys"):
    # one line in, one styled line out. tags get their own color in the hud
    line = f"[{tag}] {text}"
    brain_feed.append(line)
    return line


def set_brain(name):
    # whoever gets picked at startup, the hud shows it everywhere
    global brain_name
    brain_name = name
    log_feed(f"brain online: {name}", "brain")


# ---------------- gemini side ----------------

_client = None


def get_client():
    # lazy singleton, no point rebuilding the client on every single call
    global _client
    if _client is None:
        key = os.getenv("GOOGLE_API_KEY")
        if not key or genai is None:
            return None
        _client = genai.Client(api_key=key)
    return _client


# ---------------- ollama side ----------------

def list_ollama_models():
    # shells out to `ollama list` exactly like the user sees in their terminal
    try:
        proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    models = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


async def _ollama_chat(model, payload):
    # native async client, streams reasoning + answer tokens so the hud can show
    # the thinking process live instead of a frozen screen while ollama cooks
    client = ollama.AsyncClient(host=OLLAMA_HOST)
    content = ""
    thinking = ""

    def _fields(chunk):
        # ollama-py hands us message objects, older/fake clients hand us dicts. handle both
        msg = getattr(chunk, "message", None)
        if msg is None and isinstance(chunk, dict):
            msg = chunk.get("message", {})
        if isinstance(msg, dict):
            return msg.get("content", "") or "", msg.get("thinking", "") or ""
        return getattr(msg, "content", "") or "", getattr(msg, "thinking", "") or ""

    try:
        stream = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            format="json",
            options={"temperature": 0},
            stream=True,
        )
        async for chunk in stream:
            piece, think = _fields(chunk)
            if think:
                thinking += think
                log_feed(think.strip()[:100], "think")
            if piece:
                content += piece
    except Exception as e:
        log_feed(f"ollama call died: {type(e).__name__}", "err")
        return None
    return {"content": content, "thinking": thinking}


# ---------------- the allocator ----------------

async def allocate_tasks(rover_positions: dict, trash: list, client=None) -> dict:
    # the only llm job in this repo: stare at the board, hand out targets.
    # always returns {rover_name: (x, y) or None}, callers can trust the shape
    trash = [(int(x), int(y)) for x, y in trash]
    if not trash:
        return {name: None for name in rover_positions}

    payload = {
        "rovers": [{"name": name, "x": pos[0], "y": pos[1]} for name, pos in rover_positions.items()],
        "trash": [{"x": x, "y": y} for x, y in trash],
    }
    backend = brain_name

    raw = None
    if backend == "gemini":
        if client is None:
            client = get_client()
        if client is None:
            # no key / no sdk. greedy keeps the swarm moving anyway
            log_feed("no gemini key, greedy allocation this round", "warn")
            return greedy_assignment(rover_positions, trash)
        log_feed(f"gemini: allocating {len(trash)} trash to {len(rover_positions)} rovers", "brain")
        try:
            resp = await client.aio.models.generate_content(
                model=DEFAULT_MODEL,
                contents=json.dumps(payload),
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    # tiny allocation call, no reason to burn thinking tokens on it
                    "thinking_config": {"thinking_level": "low"},
                },
            )
            raw = resp.text
        except Exception as e:
            # fallback just in case the api throttles us
            log_feed(f"gemini call died ({type(e).__name__}), greedy this round", "err")
            return greedy_assignment(rover_positions, trash)

    elif backend.startswith("ollama:"):
        model = backend.split("ollama:", 1)[1]
        log_feed(f"asking {model} to allocate {len(trash)} trash", "brain")
        out = await _ollama_chat(model, payload)
        if out is None:
            return greedy_assignment(rover_positions, trash)
        raw = out["content"]
        if out["thinking"]:
            log_feed("...decision made", "think")

    else:
        return greedy_assignment(rover_positions, trash)

    parsed = _parse_assignments(raw, rover_positions, trash)
    if parsed is None:
        # model fumbled the format, fall back before the tick loop even notices
        log_feed("model replied garbage, greedy this round", "err")
        return greedy_assignment(rover_positions, trash)
    for name, coord in parsed.items():
        if coord is not None:
            log_feed(f"{name} -> ({coord[0]},{coord[1]})", "chat")
    return parsed


def _parse_assignments(raw, rover_positions, trash):
    # parses llm json output so it doesnt break the loop
    if not raw:
        return None
    text = raw.strip()
    # models love wrapping json in ``` fences even when you say json only. slice the braces out
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    valid = sorted(set(trash))
    taken = set()
    out = {}
    for name in rover_positions:
        coord = _extract_coord(data.get(name))
        # coord has to be a real trash tile nobody else claimed, else greedy fills the gap
        if coord is None or coord not in valid or coord in taken:
            coord = _greedy_pick(rover_positions[name], [c for c in valid if c not in taken])
        if coord is not None:
            taken.add(coord)
        out[name] = coord
    return out


def _extract_coord(entry):
    # handles {"x": 1, "y": 2} and straight [1, 2], models do both
    try:
        if isinstance(entry, dict):
            x, y = int(entry["x"]), int(entry["y"])
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            x, y = int(entry[0]), int(entry[1])
        else:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return (x, y)


def _greedy_pick(pos, candidates):
    # nearest trash to pos out of whats left, none if theres nothing to pick
    best, best_d = None, None
    for c in candidates:
        d = abs(c[0] - pos[0]) + abs(c[1] - pos[1])
        if best_d is None or d < best_d:
            best, best_d = c, d
    return best


def greedy_assignment(rover_positions, trash):
    # dumbest working allocator: each rover grabs the nearest unclaimed trash.
    # keeps the sim alive offline and rescues every bad llm reply
    candidates = sorted(set(trash))
    taken = set()
    out = {}
    for name, pos in rover_positions.items():
        pick = _greedy_pick(pos, [c for c in candidates if c not in taken])
        if pick is not None:
            taken.add(pick)
        out[name] = pick
    return out