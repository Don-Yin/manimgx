"""The site's sharing card: original vector art, with the existing ManimGX lockup.

Run `uv run --frozen python -m scripts.showcase.social` to write the committed SVG
and 1200 × 630 PNG in `docs/content/images/`. Rasterization uses `rsvg-convert`
(librsvg); the docs build only copies the finished PNG and needs no extra tools.
Type is outlined by ManimGX's Typst, as in the logo, so the SVG needs no fonts.
"""

import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image
from scripts.showcase import logo

IMAGES = Path(__file__).parents[2] / "docs" / "content" / "images"
WIDTH, HEIGHT = 1200, 630
INK, MUTED, BLUE = "#ece6e2", "#a5afb9", "#58c4dd"


def lettering(
    text: str, x: float, y: float, size: float, color: str, weight: int = 400
) -> str:
    """Outlined Noto Sans, positioned by its top left and scaled by its em."""
    outline = logo.set_type(
        f'#text(font: "Noto Sans", weight: {weight})[x#h(1em){text}]'
    )
    canvas = logo.Canvas(logo.extent(outline), margin=0)
    canvas.s = size
    paths = "".join(canvas.curve(path) for path in outline)
    return f'<path transform="translate({x} {y})" fill="{color}" d="{paths}"/>'


def lockup(name: str, x: float, y: float, width: float) -> str:
    """Embed the committed logo paths, preserving their aspect ratio."""
    root = ET.fromstring((IMAGES / name).read_text(encoding="utf-8"))
    _, _, w, h = (float(v) for v in root.attrib["viewBox"].split())
    # Keep the original SVG verbatim inside a viewport; no external image requests.
    svg = (IMAGES / name).read_text(encoding="utf-8").strip()
    return (
        f'<svg x="{x}" y="{y}" width="{width}" height="{width * h / w}" '
        f'viewBox="0 0 {w} {h}">{svg}</svg>'
    )


def knot() -> str:
    """A trefoil tube, projected and lit, with fine transverse construction lines."""
    count, sides = 288, 28
    t = np.linspace(0, 2 * math.pi, count, endpoint=False)
    radius = 2 + 0.62 * np.cos(3 * t)
    center = np.column_stack(
        [radius * np.cos(2 * t), radius * np.sin(2 * t), 0.9 * np.sin(3 * t)]
    )
    rotation = logo.rotation(np.array([1, 0, 0]), 0.62) @ logo.rotation(
        np.array([0, 1, 0]), -0.24
    )
    # Ease the small cyan return into one sweep. Only its projected centerline moves;
    # its depth, the crossings and the rest of the knot retain their original positions.
    first, last = count // 12, count * 5 // 18
    projected = center @ rotation.T
    p0, p3 = projected[[first, last], :2]
    handles = (
        projected[[first + 1, last + 1], :2] - projected[[first - 1, last - 1], :2]
    )
    handles *= (0.45 * np.linalg.norm(p3 - p0)) / np.linalg.norm(handles, axis=1)[
        :, None
    ]
    p1, p2 = p0 + handles[0], p3 - handles[1]
    u = np.linspace(0, 1, last - first + 1)[:, None]
    sweep = (1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1
    sweep += 3 * (1 - u) * u**2 * p2 + u**3 * p3
    edge = np.clip(np.minimum(u, 1 - u) / 0.15, 0, 1)
    blend = edge**3 * (10 - 15 * edge + 6 * edge**2)
    delta = np.zeros_like(center)
    delta[first : last + 1, :2] = blend * (sweep - projected[first : last + 1, :2])
    center += delta @ rotation
    tangent = np.roll(center, -1, axis=0) - np.roll(center, 1, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    normal = np.cross(tangent, [0, 0, 1])
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    binormal = np.cross(tangent, normal)
    angle = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    normals = (
        normal[:, None] * np.cos(angle)[None, :, None]
        + binormal[:, None] * np.sin(angle)[None, :, None]
    )
    points = (center[:, None] + 0.22 * normals) @ rotation.T
    normals = normals @ rotation.T
    light = np.array([-0.45, -0.6, 0.85])
    light /= np.linalg.norm(light)
    palette = [BLUE, logo.GREEN, logo.RED, BLUE]
    faces: list[tuple[float, str]] = []
    for i in range(count):
        j = (i + 1) % count
        phase = i / count * 3
        color = logo.mix(palette[int(phase)], palette[int(phase) + 1], phase % 1)
        for a in range(sides):
            b = (a + 1) % sides
            face = np.array([points[i, a], points[j, a], points[j, b], points[i, b]])
            n = normals[i, a] + normals[i, b]
            n /= np.linalg.norm(n)
            if n[2] < -0.15:
                continue
            diffuse = max(0, float(n @ light))
            shade = logo.shade(color, 0.38 + 0.65 * diffuse + 0.25 * diffuse**12)
            xy = face[:, :2] * 87 + [927, 298]
            path = "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in xy) + "Z"
            # The narrow same-color stroke closes raster seams between adjacent faces.
            body = (
                f'<path d="{path}" fill="{shade}" stroke="{shade}" stroke-width="0.6"/>'
            )
            if i % 12 == 0:
                p, q = xy[0], xy[3]
                body += (
                    f'<path d="M{p[0]:.2f} {p[1]:.2f}L{q[0]:.2f} {q[1]:.2f}" '
                    'fill="none" stroke="#0b0c0f" stroke-opacity="0.3" stroke-width="0.7"/>'
                )
            faces.append((float(face[:, 2].mean()), body))
    return "".join(body for _, body in sorted(faces))


def card() -> str:
    """The full, self-contained sharing artwork."""
    background = """<defs>
      <radialGradient id="glow">
        <stop stop-color="#203c48" stop-opacity="0.65"/>
        <stop offset="1" stop-color="#0b0c0f" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="shadow">
        <stop stop-color="#000" stop-opacity="0.65"/>
        <stop offset="1" stop-color="#000" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <rect width="1200" height="630" fill="#0b0c0f"/>
    <ellipse cx="922" cy="285" rx="400" ry="335" fill="url(#glow)"/>
    <ellipse cx="933" cy="494" rx="237" ry="36" fill="url(#shadow)"/>
    <g fill="none" stroke="#58c4dd" stroke-opacity="0.09" stroke-width="1">
      <ellipse cx="926" cy="312" rx="247" ry="230"/>
      <path d="M653 312H1186M926 62V549"/>
    </g>"""
    body = background + knot()
    body += lockup("logo-dark.svg", 55, 109, 568)
    body += lettering("Blazingly fast 3D animations,", 65, 284, 39, INK, 500)
    body += lettering("for creators and agents.", 65, 340, 35, BLUE, 500)
    body += lettering("Open source · Python API · Rust + GPU", 65, 419, 23, MUTED)
    body += lockup("byline-dark.svg", 64, 492, 246)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">{body}</svg>\n'
    )


def main() -> None:
    """Write the editable vector source and the crawler-compatible RGB PNG."""
    svg, png = IMAGES / "social-preview.svg", IMAGES / "social-preview.png"
    svg.write_text(card(), encoding="utf-8")
    subprocess.run(["rsvg-convert", str(svg), "--output", str(png)], check=True)
    with Image.open(png) as image:
        image.convert("RGB").save(png, optimize=True)
    print(f"{png}: {WIDTH} × {HEIGHT}, {png.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
