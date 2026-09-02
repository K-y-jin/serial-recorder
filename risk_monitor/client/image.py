"""Renders a risk-warning snapshot: the *current* pressure frame (not an
accumulated/historical one) with the cells that just fired a risk warning
overlaid in red, as a PNG suitable for POST /image."""
import io

import numpy as np
from PIL import Image

SCALE = 8  # upscale factor so individual cells are visible in the PNG
RISK_COLOR = (255, 0, 0)


def render_risk_image(pressure_vector, rows, cols, risky_idx, scale=SCALE):
    """pressure_vector: flat uint8-range array of length rows*cols (the
    current frame). risky_idx: cell indices to highlight (this frame's
    fired_idx -- not an accumulated history). Returns PNG bytes."""
    grid = np.clip(pressure_vector, 0, 255).astype(np.uint8).reshape(rows, cols)
    rgb = np.stack([grid, grid, grid], axis=-1).copy()

    risky_idx = np.asarray(risky_idx)
    if risky_idx.size:
        rgb[risky_idx // cols, risky_idx % cols] = RISK_COLOR

    img = Image.fromarray(rgb, mode="RGB").resize(
        (cols * scale, rows * scale), resample=Image.NEAREST
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
