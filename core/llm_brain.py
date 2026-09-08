import json
import os

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None  # sdk not installed = offline mode, the greedy allocator still runs

# keys go in .env (see .env.example). never commit the real one lol
load_dotenv()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = (
    "you are the task allocator for a swarm of trash-collecting rovers on a 2d grid. "
    "you get json with 'rovers' (name + position) and 'trash' (coordinates still on the grid). "
    "assign exactly one trash target to each rover. spread them out, never send two rovers "
    "after the same trash, prefer trash that is close to each rover. "
    'reply with json only, exactly like {"rover-1": {"x": 3, "y": 7}, "rover-2": {"x": 11, "y": 2}}. '
    "every x and y is an integer and must come from the trash list."
)

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


async def allocate_tasks(rover_positions: dict, trash: list, client=None) -> dict:
    # the only llm job in this repo: stare at the board, hand out targets.
    # always returns {rover_name: (x, y) or None}, callers can trust the shape
    trash = [(int(x), int(y)) for x, y in trash]
    if not trash:
        return {name: None for name in rover_positions}
    if client is None:
        client = get_client()
    if client is None:
        # offline mode, greedy keeps the swarm moving anyway
        return greedy_assignment(rover_positions, trash)

    payload = {
        "rovers": [{"name": name, "x": pos[0], "y": pos[1]} for name, pos in rover_positions.items()],
        "trash": [{"x": x, "y": y} for x, y in trash],
    }

    try:
        resp = await client.aio.models.generate_content(
            model=DEFAULT_MODEL,
            contents=json.dumps(payload),
            config={
                "system_instruction": SYSTEM_PROMPT,
                "response_mime_type": "application/json",
            },
        )
    except Exception as e:
        # fallback just in case the api throttles us
        print(f"  [brain] gemini call died ({type(e).__name__}), greedy allocation this round")
        return greedy_assignment(rover_positions, trash)

    parsed = _parse_assignments(resp.text, rover_positions, trash)
    if parsed is None:
        # model fumbled the format, fall back before the tick loop even notices
        print("  [brain] gemini replied garbage, greedy allocation this round")
        return greedy_assignment(rover_positions, trash)
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