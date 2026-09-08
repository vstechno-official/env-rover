import json
import os
import random

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None  # sdk not installed = offline mode, the greedy fallback still runs

# keys go in .env (see .env.example). never commit the real one lol
load_dotenv()

VALID_MOVES = ("UP", "DOWN", "LEFT", "RIGHT")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = (
    "you are the navigation brain of a trash-collecting rover on a 2d grid. "
    "you get the rover's position and the nearest trash coordinates. "
    "reply with the single best next move to get closer to trash. "
    'respond with json only, exactly like {"move": "UP", "reason": "short why"}. '
    "move must be one of UP DOWN LEFT RIGHT. y grows downward, so UP decreases y and DOWN increases y."
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


async def ask_brain(rover_pos, trash, client=None):
    # main entry. returns (move, reason) and move is ALWAYS one of VALID_MOVES
    # no matter what the model says. callers can trust that
    if client is None:
        client = get_client()

    if client is None:
        # no key or no sdk, offline mode. greedy keeps the sim moving anyway
        return _greedy_move(rover_pos, trash), "offline mode, greedy homing"

    payload = {
        "rover": {"x": rover_pos[0], "y": rover_pos[1]},
        "trash_nearby": [{"x": x, "y": y, "dist": d} for x, y, d in trash],
        "reminder": "y grows downward. UP = y-1, DOWN = y+1. json only.",
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
        # rate limit, timeout, network hiccup, whatever. one bad call cant kill the swarm
        print(f"  [brain] gemini call died ({type(e).__name__}), going greedy")
        return _greedy_move(rover_pos, trash), f"api error: {type(e).__name__}"

    move, reason = _parse_move(resp.text)
    if move is None:
        # model fumbled the format, fall back before the tick loop even notices
        return _greedy_move(rover_pos, trash), f"bad reply ({reason}), greedy"
    return move, reason


def _parse_move(raw):
    # parses llm json output so it doesnt break the loop
    if not raw:
        return None, "empty reply"
    text = raw.strip()
    # models love wrapping json in ``` fences even when you say json only. slice the braces out
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, "not json at all"
    if not isinstance(data, dict):
        return None, f"json but not an object ({type(data).__name__})"
    move = str(data.get("move", "")).upper()
    if move not in VALID_MOVES:
        return None, f"illegal move {move!r}"
    return move, str(data.get("reason", ""))[:80]


def _greedy_move(rover_pos, trash):
    # dumbest working policy: step toward the nearest trash. keeps the sim alive
    # offline and rescues us every time the model replies with nonsense
    if not trash:
        return random.choice(VALID_MOVES)  # nothing in sensor range, just wander
    x, y = rover_pos
    tx, ty = trash[0][0], trash[0][1]  # nearby_trash sorts nearest first, trust it
    dx, dy = tx - x, ty - y
    if abs(dx) >= abs(dy):
        return "RIGHT" if dx > 0 else "LEFT"
    return "DOWN" if dy > 0 else "UP"