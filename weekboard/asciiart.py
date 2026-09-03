"""Turn an image into ASCII art.

Two passes, blended: a Sobel edge pass that picks a line character matching the
direction of each edge (| / - \\), and a luminance pass that fills solid areas
from a density ramp. Edges win where they are strong, which is what gives the
contour-drawing look rather than the usual grey mush.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# Character cells are roughly twice as tall as they are wide.
CELL_ASPECT = 2.05

# Dark -> light. The blank at the start matters: it is most of the picture.
TONE_RAMP = " .:-=+*#%@"
TONE_RAMP_SOFT = " ..::--~=+"

# Edge direction (in degrees, 0 = horizontal edge) mapped to a line character.
EDGE_CHARS = ("-", "/", "|", "\\")


def _prepare(image: Image.Image, width: int, invert: bool, contrast: float) -> np.ndarray:
    """Grayscale, aspect-correct and resize the image to a character grid."""
    gray = ImageOps.grayscale(image)
    if invert:
        gray = ImageOps.invert(gray)
    if contrast != 1.0:
        gray = ImageOps.autocontrast(gray, cutoff=1)
    height = max(1, int(round(width * gray.height / gray.width / CELL_ASPECT)))
    # A slight blur before downsampling keeps edges continuous instead of dotty.
    gray = gray.filter(ImageFilter.GaussianBlur(max(0.4, gray.width / width / 3.0)))
    gray = gray.resize((width, height), Image.LANCZOS)
    data = np.asarray(gray, dtype=np.float32) / 255.0
    if contrast != 1.0:
        data = np.clip((data - 0.5) * contrast + 0.5, 0.0, 1.0)
    return data


def _sobel(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return gradient magnitude (normalised) and direction in degrees."""
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    padded = np.pad(data, 1, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    gx = np.einsum("ijkl,kl->ij", windows, kx)
    gy = np.einsum("ijkl,kl->ij", windows, ky)
    magnitude = np.hypot(gx, gy)
    peak = magnitude.max()
    if peak > 0:
        magnitude = magnitude / peak
    # Direction of the edge itself is perpendicular to the gradient.
    angle = (np.degrees(np.arctan2(gy, gx)) + 90.0) % 180.0
    return magnitude, angle


def _blur(data: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur, so this module needs nothing beyond numpy."""
    if sigma <= 0:
        return data
    radius = max(1, int(round(3 * sigma)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-(offsets ** 2) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    rows = np.pad(data, ((0, 0), (radius, radius)), mode="edge")
    out = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 1, rows)
    cols = np.pad(out, ((radius, radius), (0, 0)), mode="edge")
    return np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 0, cols)


def _orientation(coverage: np.ndarray, sigma: float = 1.4) -> np.ndarray:
    """Dominant line direction per cell, in degrees, via the structure tensor.

    Sobel alone traces both sides of a thick stroke and produces noise. The
    structure tensor, smoothed over a neighbourhood, reports the direction the
    stroke actually runs in, which is what we want a line character to follow.
    """
    smooth = _blur(coverage, 0.9)
    gy, gx = np.gradient(smooth)
    jxx = _blur(gx * gx, sigma)
    jyy = _blur(gy * gy, sigma)
    jxy = _blur(gx * gy, sigma)
    # Principal gradient direction; the stroke runs perpendicular to it.
    gradient_angle = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    return (np.degrees(gradient_angle) + 90.0) % 180.0


def from_line_art(
    path: str | Path,
    width: int = 46,
    *,
    invert: bool = False,
    ink_threshold: float = 0.16,
    sigma: float = 1.4,
) -> str:
    """Convert a line drawing (light strokes on a dark ground) to ASCII.

    Each inked cell becomes the line character matching the stroke's direction,
    so a drawing comes out as a contour drawing rather than grey shading.
    """
    with Image.open(path) as handle:
        image = handle.convert("RGB")
    gray = ImageOps.grayscale(image)
    if invert:
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray, cutoff=0.5)

    height = max(1, int(round(width * gray.height / gray.width / CELL_ASPECT)))
    # Area averaging gives each cell the fraction of it covered by ink.
    coverage = np.asarray(
        gray.resize((width, height), Image.BOX), dtype=np.float32
    ) / 255.0
    peak = coverage.max()
    if peak > 0:
        coverage = coverage / peak

    angle = _orientation(coverage, sigma=sigma)
    bucket = np.round(angle / 45.0).astype(int) % 4

    rows = [
        "".join(
            EDGE_CHARS[bucket[y, x]] if coverage[y, x] >= ink_threshold else " "
            for x in range(width)
        ).rstrip()
        for y in range(height)
    ]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return "\n".join(rows)


def from_image(
    path: str | Path,
    width: int = 46,
    *,
    invert: bool = False,
    edge_threshold: float = 0.22,
    fill: bool = True,
    contrast: float = 1.35,
    tone_ramp: str = TONE_RAMP_SOFT,
) -> str:
    """Convert an image file to ASCII art.

    width          columns of output
    invert         set for dark-on-light source images
    edge_threshold 0-1; lower draws more outline
    fill           also shade flat areas from the tone ramp
    """
    with Image.open(path) as handle:
        data = _prepare(handle.convert("RGB"), width, invert, contrast)

    magnitude, angle = _sobel(data)
    # Quantise edge angle into the four line characters.
    bucket = np.round(angle / 45.0).astype(int) % 4

    rows: list[str] = []
    for y in range(data.shape[0]):
        row: list[str] = []
        for x in range(data.shape[1]):
            if magnitude[y, x] >= edge_threshold:
                row.append(EDGE_CHARS[bucket[y, x]])
            elif fill:
                level = int(data[y, x] * (len(tone_ramp) - 1))
                row.append(tone_ramp[level])
            else:
                row.append(" ")
        rows.append("".join(row).rstrip())

    # Trim fully blank rows top and bottom.
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return "\n".join(rows)


BRAILLE_BASE = 0x2800
# Dot numbering inside one braille cell: (column, row) -> bit.
BRAILLE_BITS = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}


def _dither(data: np.ndarray) -> np.ndarray:
    """Floyd-Steinberg error diffusion to a 1-bit image."""
    out = data.astype(np.float32).copy()
    rows, cols = out.shape
    for y in range(rows):
        for x in range(cols):
            old = out[y, x]
            new = 1.0 if old > 0.5 else 0.0
            out[y, x] = new
            error = old - new
            if x + 1 < cols:
                out[y, x + 1] += error * 7 / 16
            if y + 1 < rows:
                if x:
                    out[y + 1, x - 1] += error * 3 / 16
                out[y + 1, x] += error * 5 / 16
                if x + 1 < cols:
                    out[y + 1, x + 1] += error * 1 / 16
    return out


def to_braille(
    path: str | Path,
    width: int = 60,
    *,
    invert: bool = False,
    threshold: float = 0.5,
    dither: bool = True,
    contrast: float = 1.0,
) -> str:
    """Convert an image to Unicode braille art.

    Braille packs 2x4 dots into every character cell, so this carries eight
    times the detail of character ASCII — close to a small photograph.
    """
    with Image.open(path) as handle:
        image = handle.convert("RGB")
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    if invert:
        gray = ImageOps.invert(gray)

    # Two dots across and four down per cell, so the pixel grid is 2w x 4h.
    dot_w = width * 2
    dot_h = max(4, int(round(dot_w * gray.height / gray.width / CELL_ASPECT / 2)) * 4)
    gray = gray.resize((dot_w, dot_h), Image.LANCZOS)

    data = np.asarray(gray, dtype=np.float32) / 255.0
    if contrast != 1.0:
        data = np.clip((data - 0.5) * contrast + 0.5, 0.0, 1.0)
    bits = _dither(data) > 0.5 if dither else data > threshold

    rows = []
    for cy in range(0, dot_h, 4):
        line = []
        for cx in range(0, dot_w, 2):
            mask = 0
            for (ox, oy), bit in BRAILLE_BITS.items():
                if bits[cy + oy, cx + ox]:
                    mask |= bit
            line.append(chr(BRAILLE_BASE + mask))
        # Trailing blanks are the blank braille cell, not a space.
        rows.append("".join(line).rstrip(chr(BRAILLE_BASE)))
    while rows and not rows[0].strip(chr(BRAILLE_BASE)):
        rows.pop(0)
    while rows and not rows[-1].strip(chr(BRAILLE_BASE)):
        rows.pop()
    return "\n".join(rows)


def normalise(art: str) -> str:
    """Strip common leading whitespace so the block sits flush left."""
    lines = [line.rstrip() for line in art.splitlines()]
    body = [line for line in lines if line.strip()]
    if not body:
        return art
    indent = min(len(line) - len(line.lstrip()) for line in body)
    return "\n".join(line[indent:] if line.strip() else "" for line in lines)
