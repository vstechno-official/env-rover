import asyncio
import os
import sys
from pathlib import Path

import numpy as np
import pygame

# rendering the visual grid here. dark mode obviously, everything else is wrong

TILE = 22
HUD_H = 46
FOOTER_H = 30
PAD = 14

BG = (8, 11, 16)
BOARD_BG = (11, 15, 21)
GRID_LINE = (19, 26, 35)
GRID_LINE_MAJOR = (29, 39, 53)
TRASH_COLOR = (154, 255, 90)
ROVER_COLORS = [(0, 229, 255), (255, 70, 180), (255, 203, 63)]
CORE_COLOR = (235, 245, 250)
TEXT_DIM = (108, 130, 148)
TEXT_BRIGHT = (224, 236, 244)
ACCENT = (0, 229, 255)

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
    }
    _state["ready"] = True


def _surface_size(w_tiles, h_tiles):
    return PAD + w_tiles * TILE + PAD, HUD_H + h_tiles * TILE + PAD + FOOTER_H


def build_surface(w_tiles, h_tiles):
    if not _state["ready"]:
        init(headless=True)
    w, h = _surface_size(w_tiles, h_tiles)
    return pygame.Surface((w, h))


def _center(pos):
    # grid coord -> pixel center. the board starts right under the hud
    return PAD + pos[0] * TILE + TILE // 2, HUD_H + pos[1] * TILE + TILE // 2


def _fx(surface):
    # scanlines + vignette get precomputed once per size then reused every frame
    key = surface.get_size()
    if key not in _fx_cache:
        w, h = key
        scan = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(0, h, 2):
            pygame.draw.line(scan, (0, 0, 0, 26), (0, y), (w, y))
        ys, xs = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xs - w / 2) ** 2 + (ys - h / 2) ** 2) / (max(w, h) / 2)
        alpha = (np.clip((dist - 0.62) / 0.38, 0, 1) * 110).astype(np.uint8)
        vig = pygame.Surface((w, h), pygame.SRCALPHA)
        arr = pygame.surfarray.pixels_alpha(vig)
        arr[:] = alpha.T
        del arr
        _fx_cache[key] = (scan, vig)
    return _fx_cache[key]


def _draw_hud(sim, surface):
    from core import llm_brain

    fonts = _state["fonts"]
    w = surface.get_width()
    surface.blit(fonts["title"].render("ENV-ROVER // SWARM SIM", True, TEXT_BRIGHT), (PAD, 10))
    mode = f"{llm_brain.DEFAULT_MODEL} allocs - a-star drives" if sim.live else "offline greedy allocs - a-star drives"
    surface.blit(fonts["small"].render(mode, True, TEXT_DIM), (PAD, 30))

    tick = fonts["hud"].render(f"TICK {sim.tick_count:03d}", True, ACCENT)
    surface.blit(tick, (w - PAD - tick.get_width(), 10))
    trash = fonts["hud"].render(f"TRASH {sim.env.trash_left}/{sim.spawned}", True, TEXT_BRIGHT)
    surface.blit(trash, (w - PAD - trash.get_width(), 28))

    pygame.draw.line(surface, GRID_LINE_MAJOR, (PAD, HUD_H - 4), (w - PAD, HUD_H - 4))

    # footer chips, one per rover, count next to its color
    small = fonts["small"]
    x = PAD
    fy = surface.get_height() - FOOTER_H + 8
    for i, rover in enumerate(sim.rovers):
        color = ROVER_COLORS[i % len(ROVER_COLORS)]
        pygame.draw.circle(surface, color, (x + 4, fy + 6), 4)
        label = small.render(f"{rover.name} {rover.collected}", True, TEXT_DIM)
        surface.blit(label, (x + 13, fy))
        x += 13 + label.get_width() + 18
    info = small.render(f"{len(sim.rovers)} rovers - {sim.env.width}x{sim.env.height} grid", True, TEXT_DIM)
    surface.blit(info, (w - PAD - info.get_width(), fy))


def draw(sim, surface):
    if not _state["ready"]:
        init(headless=True)
    w, h = surface.get_size()
    surface.fill(BG)
    env = sim.env
    gw, gh = env.width, env.height
    ox, oy = PAD, HUD_H

    pygame.draw.rect(surface, BOARD_BG, (ox - 4, oy - 4, gw * TILE + 8, gh * TILE + 8), border_radius=6)

    # grid lines, every 6th one brighter so the board has some texture
    for x in range(gw + 1):
        color = GRID_LINE_MAJOR if x % 6 == 0 else GRID_LINE
        pygame.draw.line(surface, color, (ox + x * TILE, oy), (ox + x * TILE, oy + gh * TILE))
    for y in range(gh + 1):
        color = GRID_LINE_MAJOR if y % 6 == 0 else GRID_LINE
        pygame.draw.line(surface, color, (ox, oy + y * TILE), (ox + gw * TILE, oy + y * TILE))

    overlay = pygame.Surface((w, h), pygame.SRCALPHA)

    # trash diamonds with a tiny pulse so the gif feels alive
    half = 4 if sim.tick_count % 2 == 0 else 5
    for tx, ty in env.trash:
        cx, cy = _center((int(tx), int(ty)))
        glow = [(cx, cy - half - 3), (cx + half + 3, cy), (cx, cy + half + 3), (cx - half - 3, cy)]
        pygame.draw.polygon(overlay, (*TRASH_COLOR, 40), glow)
        body = [(cx, cy - half), (cx + half, cy), (cx, cy + half), (cx - half, cy)]
        pygame.draw.polygon(overlay, (*TRASH_COLOR, 235), body)

    # trails + target lines first, they sit under everything else
    for i, rover in enumerate(sim.rovers):
        color = ROVER_COLORS[i % len(ROVER_COLORS)]
        n = len(rover.trail)
        for j, tile in enumerate(rover.trail):
            fade = int(24 + 100 * j / (n - 1)) if n > 1 else 60
            cx, cy = _center(tile)
            pygame.draw.rect(overlay, (*color, fade), (cx - 1, cy - 1, 3, 3))
        if rover.target is not None:
            rx, ry = _center(rover.pos)
            tx, ty = _center(rover.target)
            pygame.draw.line(overlay, (*color, 80), (rx, ry), (tx, ty))
            pygame.draw.circle(overlay, (*color, 170), (tx, ty), 3, 1)

    # fake bloom: two stacked translucent circles per rover. cheap and it reads well
    for i, rover in enumerate(sim.rovers):
        color = ROVER_COLORS[i % len(ROVER_COLORS)]
        cx, cy = _center(rover.pos)
        pygame.draw.circle(overlay, (*color, 60), (cx, cy), 7)
        pygame.draw.circle(overlay, (*color, 34), (cx, cy), 11)

    surface.blit(overlay, (0, 0))

    # rover bodies go on top of everything, they are the main characters
    for i, rover in enumerate(sim.rovers):
        color = ROVER_COLORS[i % len(ROVER_COLORS)]
        cx, cy = _center(rover.pos)
        pygame.draw.circle(surface, color, (cx, cy), 5)
        pygame.draw.circle(surface, CORE_COLOR, (cx, cy), 2)

    _draw_hud(sim, surface)
    scan, vig = _fx(surface)
    surface.blit(scan, (0, 0))
    surface.blit(vig, (0, 0))


def snapshot(surface):
    # pygame hands us (W, H, 3), imageio wants (H, W, 3). classic
    return np.ascontiguousarray(np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2)))


def render_frame(sim):
    surface = build_surface(sim.env.width, sim.env.height)
    draw(sim, surface)
    return snapshot(surface)


def run_live(fps=10, seed=11, live=None):
    # actual window mode. q or the x button bails out
    from core import llm_brain
    from core.swarm_async import SwarmSim

    init(headless=False)
    if live is None:
        live = llm_brain.get_client() is not None
    sim = SwarmSim(live=live, seed=seed, respawn=(20, 8))
    surface = build_surface(sim.env.width, sim.env.height)
    pygame.display.set_caption("env-rover // swarm sim")
    screen = pygame.display.set_mode(surface.get_size())
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_q):
                running = False
        asyncio.run(sim.tick())
        draw(sim, screen)
        pygame.display.flip()
        clock.tick(fps)
    pygame.quit()


if __name__ == "__main__":
    run_live()