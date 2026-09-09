import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pygame

from core import llm_brain

# rendering the minecraft dirt blocks. isometric 2.5d so we get the 3d feel
# without dragging in a whole engine. doing isometric math here bc full 3d engines are bloat

TILE_W = 44  # tile width in px
TILE_H = 22  # tile height in px (half of W, classic iso ratio)
BLOCK_H = 18  # how tall blocks stand off the ground
TILE = 22  # legacy flat-tile size, kept for hud math

PAD_X = 60
HUD_H = 46
FOOTER_H = 30

BG = (10, 12, 14)
GRID_TOP = (94, 133, 64)
GRID_TOP_ALT = (84, 120, 58)
GRID_LEFT = (66, 96, 48)
GRID_RIGHT = (52, 76, 40)
TRASH_TOP = (188, 122, 46)
TRASH_LEFT = (150, 92, 30)
TRASH_RIGHT = (118, 70, 22)
ROVER_BODY = (120, 124, 130)
ROVER_LEFT = (88, 92, 98)
ROVER_RIGHT = (70, 74, 80)
ROVER_ACCENT = (0, 229, 255)
TRAIL_COLOR = (0, 229, 255)
TARGET_COLOR = (255, 203, 63)
TEXT_DIM = (108, 130, 148)
TEXT_BRIGHT = (224, 236, 244)
FEED_BG_ALPHA = 170
FEED_W = 400

_state = {"ready": False}
_fx_cache = {}


def init(headless=False):
    # dummy video driver so this also works on a box with no display (gif gen, CI, etc)
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    if not pygame.get_init():
        pygame.init()
    pygame.font.init()
    mono = "consolas,menlo,dejavusansmono,monospace"
    _state["fonts"] = {
        "title": pygame.font.SysFont(mono, 17, True),
        "hud": pygame.font.SysFont(mono, 14),
        "small": pygame.font.SysFont(mono, 13),
        "feed": pygame.font.SysFont(mono, 12),
    }
    _state["ready"] = True


def _surface_size(w_tiles, h_tiles):
    # iso world is a diamond: total width = (w+h)*TILE_W/2, height = (w+h)*TILE_H/2 + block lift
    diamond_w = (w_tiles + h_tiles) * TILE_W // 2
    diamond_h = (w_tiles + h_tiles) * TILE_H // 2
    return PAD_X * 2 + diamond_w + FEED_W, HUD_H + diamond_h + BLOCK_H + PAD_X + FOOTER_H


def build_surface(w_tiles, h_tiles):
    if not _state["ready"]:
        init(headless=True)
    w, h = _surface_size(w_tiles, h_tiles)
    return pygame.Surface((w, h))


def iso_center(x, y, w_tiles, h_tiles):
    # the iso projection. screen_x = (x - y) * TILE_W/2, screen_y = (x + y) * TILE_H/2
    sx = (x - y) * (TILE_W // 2)
    sy = (x + y) * (TILE_H // 2)
    # recenter the diamond into the board area (board sits left of the feed panel)
    board_x = PAD_X + (w_tiles - 1) * (TILE_W // 2)
    return board_x + sx, HUD_H + (h_tiles - 1) * (TILE_H // 2) + sy


def _draw_tile(surface, x, y, w_tiles, h_tiles, top, left, right, z=0):
    # one iso block = three quads: top face + the two visible sides
    cx, cy = iso_center(x, y, w_tiles, h_tiles)
    cy -= z  # lift blocks up by z for stack effects
    hw = TILE_W // 2
    hh = TILE_H // 2
    top_pts = [(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)]
    left_pts = [(cx - hw, cy), (cx, cy + hh), (cx, cy + hh + BLOCK_H), (cx - hw, cy + BLOCK_H)]
    right_pts = [(cx + hw, cy), (cx, cy + hh), (cx, cy + hh + BLOCK_H), (cx + hw, cy + BLOCK_H)]
    pygame.draw.polygon(surface, top, top_pts)
    pygame.draw.polygon(surface, left, left_pts)
    pygame.draw.polygon(surface, right, right_pts)


def _draw_feed_panel(sim, surface):
    # transparent black terminal pinned bottom-left, prints the brain's live chat
    fonts = _state["fonts"]
    w, h = surface.get_size()
    panel_h = 196
    panel = pygame.Surface((FEED_W - 24, panel_h), pygame.SRCALPHA)
    panel.fill((8, 10, 12, FEED_BG_ALPHA))
    pygame.draw.rect(surface, (8, 10, 12, FEED_BG_ALPHA), (12, h - panel_h - 12, FEED_W - 24, panel_h), border_radius=8)
    pygame.draw.rect(surface, GRID_RIGHT, (12, h - panel_h - 12, FEED_W - 24, panel_h), 2, border_radius=8)

    # title bar with the brain name
    brain_label = fonts["small"].render(f"BRAIN FEED // {llm_brain.brain_name}", True, ROVER_ACCENT)
    surface.blit(brain_label, (24, h - panel_h - 2))
    tag_colors = {
        "brain": (0, 229, 255),
        "think": (138, 160, 180),
        "chat": (154, 255, 90),
        "err": (255, 90, 90),
        "warn": (255, 203, 63),
        "sys": (140, 152, 165),
    }
    lines = list(llm_brain.brain_feed)[-9:]
    y = h - panel_h + 14
    for line in lines:
        # feed lines are "[tag] text", color by tag
        tag = line[1:].split("]", 1)[0] if line.startswith("[") else "sys"
        color = tag_colors.get(tag, TEXT_DIM)
        txt = fonts["feed"].render(line[:64], True, color)
        surface.blit(txt, (24, y))
        y += 17


def _draw_hud(sim, surface):
    fonts = _state["fonts"]
    w = surface.get_width()
    surface.blit(fonts["title"].render("ENV-ROVER // ISOMETRIC SWARM SIM", True, TEXT_BRIGHT), (PAD_X, 10))
    mode = f"{llm_brain.brain_name} allocs - a-star drives" if llm_brain.brain_name != "greedy" else "greedy allocs - a-star drives"
    surface.blit(fonts["small"].render(mode, True, TEXT_DIM), (PAD_X, 30))

    tick = fonts["hud"].render(f"TICK {sim.tick_count:03d}", True, ROVER_ACCENT)
    surface.blit(tick, (w - PAD_X - tick.get_width(), 10))
    trash = fonts["hud"].render(f"TRASH {sim.env.trash_left}/{sim.spawned}", True, TEXT_BRIGHT)
    surface.blit(trash, (w - PAD_X - trash.get_width(), 28))

    pygame.draw.line(surface, GRID_RIGHT, (PAD_X, HUD_H - 4), (w - PAD_X, HUD_H - 4))

    # footer chips, one per rover, count next to its color
    small = fonts["small"]
    x = PAD_X
    fy = surface.get_height() - FOOTER_H + 8
    for i, rover in enumerate(sim.rovers):
        color = [ROVER_ACCENT, (255, 70, 180), TARGET_COLOR][i % 3]
        pygame.draw.circle(surface, color, (x + 4, fy + 6), 4)
        label = small.render(f"{rover.name} {rover.collected}", True, TEXT_DIM)
        surface.blit(label, (x + 13, fy))
        x += 13 + label.get_width() + 18
    info = small.render(f"{len(sim.rovers)} rovers - {sim.env.width}x{sim.env.height} grid - iso 2.5d", True, TEXT_DIM)
    surface.blit(info, (w - PAD_X - info.get_width(), fy))


def draw(sim, surface):
    if not _state["ready"]:
        init(headless=True)
    surface.fill(BG)
    env = sim.env
    w_t, h_t = env.width, env.height

    # trails first so they sit under the blocks. faint iso footprints
    for i, rover in enumerate(sim.rovers):
        color = [ROVER_ACCENT, (255, 70, 180), TARGET_COLOR][i % 3]
        n = len(rover.trail)
        for j, tile in enumerate(rover.trail[:-1]):
            fade = int(30 + 70 * j / max(n - 1, 1))
            cx, cy = iso_center(tile[0], tile[1], w_t, h_t)
            s = pygame.Surface((TILE_W, TILE_H + BLOCK_H), pygame.SRCALPHA)
            pts = [(TILE_W // 2, 0), (TILE_W, TILE_H // 2), (TILE_W // 2, TILE_H), (0, TILE_H // 2)]
            pygame.draw.polygon(s, (*color, fade), pts)
            surface.blit(s, (cx - TILE_W // 2, cy - TILE_H // 2))

    # ground checker, two greens like grass blocks
    for y in range(h_t):
        for x in range(w_t):
            top = GRID_TOP if (x + y) % 2 == 0 else GRID_TOP_ALT
            _draw_tile(surface, x, y, w_t, h_t, top, GRID_LEFT, GRID_RIGHT)

    # trash = dirt-ish brown blocks standing taller than grass
    for tx, ty in env.trash:
        _draw_tile(surface, int(tx), int(ty), w_t, h_t, TRASH_TOP, TRASH_LEFT, TRASH_RIGHT, z=BLOCK_H)

    # target markers: gold rings on top of the assigned trash tile
    for rover in sim.rovers:
        if rover.target is not None:
            cx, cy = iso_center(rover.target[0], rover.target[1], w_t, h_t)
            hw, hh = TILE_W // 2, TILE_H // 2
            pts = [(cx, cy - hh - BLOCK_H), (cx + hw, cy - BLOCK_H), (cx, cy + hh - BLOCK_H), (cx - hw, cy - BLOCK_H)]
            pygame.draw.polygon(surface, TARGET_COLOR, pts, 2)

    # rovers on top. gray chassis, cyan core, slight bob so they feel alive
    for i, rover in enumerate(sim.rovers):
        cx, cy = iso_center(rover.pos[0], rover.pos[1], w_t, h_t)
        color = [ROVER_ACCENT, (255, 70, 180), TARGET_COLOR][i % 3]
        _draw_tile(surface, rover.pos[0], rover.pos[1], w_t, h_t, ROVER_BODY, ROVER_LEFT, ROVER_RIGHT, z=BLOCK_H + 4 + (i * 2))
        hw, hh = TILE_W // 2, TILE_H // 2
        z = BLOCK_H + 4 + (i * 2)
        core = [(cx, cy - hh - z - 3), (cx + 10, cy - z - 3), (cx, cy + hh - z - 3), (cx - 10, cy - z - 3)]
        pygame.draw.polygon(surface, color, core)

    _draw_hud(sim, surface)
    _draw_feed_panel(sim, surface)


def snapshot(surface):
    # pygame hands us (W, H, 3), imageio wants (H, W, 3). classic
    return np.ascontiguousarray(np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2)))


def render_frame(sim):
    surface = build_surface(sim.env.width, sim.env.height)
    draw(sim, surface)
    return snapshot(surface)


def run_live(fps=10, seed=11, brain=None):
    # actual window mode. q or the x button bails out
    from core.swarm_async import SwarmSim

    init(headless=False)
    if brain is None:
        brain = "greedy"
    sim = SwarmSim(brain=brain, seed=seed, respawn=(20, 8))
    surface = build_surface(sim.env.width, sim.env.height)
    pygame.display.set_caption("env-rover // isometric swarm sim")
    screen = pygame.display.set_mode(surface.get_size())
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_q):
                running = False
        asyncio.run(sim.tick())
        draw(sim, surface)
        screen.blit(surface, (0, 0))
        pygame.display.flip()
        clock.tick(fps)
    pygame.quit()


if __name__ == "__main__":
    run_live()