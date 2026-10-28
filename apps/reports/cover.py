"""Artwork for the report's front and back covers: topographic contour lines and a colour
stripe, both drawn from the report reference so each report gets its own, reproducibly."""

import math
import random

# Okabe-Ito hues (the report's rating palette) plus lighter and deeper tints
STRIPE_COLOURS = [
    "#D55E00",
    "#E69F00",
    "#F0E442",
    "#F4B183",
    "#CC79A7",
    "#009E73",
    "#3FB68E",
    "#0A6B50",
    "#56B4E9",
    "#0072B2",
    "#7FA7D9",
    "#3B4A7A",
]


def _rng(seed):
    return random.Random(str(seed))


def contours_svg(seed, width=210, height=297, rings=26):
    """Concentric, gently irregular rings around a point near the top right, like contour
    lines around a hilltop; warm near the summit and fading to blue."""
    rng = _rng(seed)
    cx, cy = width * rng.uniform(0.72, 0.9), height * rng.uniform(0.04, 0.14)
    waves = [
        (rng.randint(2, 6), rng.uniform(0, 2 * math.pi), rng.uniform(0.03, 0.08)) for _ in range(4)
    ]
    paths = []
    for ring in range(1, rings + 1):
        radius = 4 + ring * 4.6
        points = []
        for step in range(181):
            angle = 2 * math.pi * step / 180
            wobble = sum(a * math.sin(k * angle + phase + ring * 0.09) for k, phase, a in waves)
            r = radius * (1 + wobble)
            points.append(f"{cx + r * math.cos(angle):.2f},{cy + r * math.sin(angle):.2f}")
        t = ring / rings
        colour = _blend("#F4B183", "#7FA7D9", t)
        opacity = 0.85 - 0.55 * t
        paths.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{colour}" '
            f'stroke-opacity="{opacity:.2f}" stroke-width="0.28"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">{"".join(paths)}</svg>'
    )


def stripe(seed, segments=34):
    """[(colour, height in %)] for the vertical colour stripe."""
    rng = _rng(f"stripe-{seed}")
    heights = [rng.uniform(1, 5) for _ in range(segments)]
    total = sum(heights)
    colours, previous = [], None
    for _ in range(segments):
        colour = rng.choice([c for c in STRIPE_COLOURS if c != previous])
        colours.append(colour)
        previous = colour
    return [(c, round(100 * h / total, 3)) for c, h in zip(colours, heights, strict=True)]


def _blend(a, b, t):
    a, b = (tuple(int(h[i : i + 2], 16) for i in (1, 3, 5)) for h in (a, b))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b, strict=True))
