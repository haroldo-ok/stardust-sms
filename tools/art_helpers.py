"""Shaded art, quantization and embossed interface helpers."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageFont, ImageDraw
BODY_FONT=str(Path(__file__).resolve().parents[1]/"assets/fonts/DejaVuSansMono-Bold.ttf")
TITLE_FONT=str(Path(__file__).resolve().parents[1]/"assets/fonts/DejaVuSans-Bold.ttf")


def to_sms(rgb):
    """float 0..1 RGB -> SMS 6-bit colour value (%--BBGGRR)"""
    r = int(round(np.clip(rgb[0], 0, 1) * 3))
    g = int(round(np.clip(rgb[1], 0, 1) * 3))
    b = int(round(np.clip(rgb[2], 0, 1) * 3))
    return (b << 4) | (g << 2) | r

def sms_to_rgb(v):
    return np.array([((v >> 0) & 3) / 3.0, ((v >> 2) & 3) / 3.0, ((v >> 4) & 3) / 3.0], np.float32)

def kmeans_palette(pixels, k, seed=1, iters=14, weights=None):
    """pixels: (N,3) float32 -> (k,3) centres"""
    rng = np.random.default_rng(seed)
    if len(pixels) > 40000:
        idx = rng.choice(len(pixels), 40000, replace=False)
        pixels = pixels[idx]
        weights = None
    if weights is None:
        weights = np.ones(len(pixels), np.float32)
    # k-means++ style init
    centres = [pixels[rng.integers(len(pixels))]]
    for _ in range(k - 1):
        d = np.min([np.sum((pixels - c) ** 2, -1) for c in centres], axis=0)
        d = d / max(d.sum(), 1e-9)
        centres.append(pixels[rng.choice(len(pixels), p=d)])
    C = np.array(centres, np.float32)
    for _ in range(iters):
        dist = ((pixels[:, None, :] - C[None, :, :]) ** 2).sum(-1)
        lab = dist.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = (pixels[m] * weights[m, None]).sum(0) / max(weights[m].sum(), 1e-9)
    # sort by luminance so palette indices look sensible
    lum = C @ np.array([0.3, 0.6, 0.1], np.float32)
    order = np.argsort(lum)
    return C[order]

BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21]], np.float32) / 64.0

def quantize(img_rgb, palette_rgb, valid_idx, dither=0.9):
    """img_rgb (h,w,3) -> index image using only palette entries in valid_idx."""
    h, w, _ = img_rgb.shape
    pal = palette_rgb[valid_idx]                       # (k,3)
    tile = np.tile(BAYER8, (h // 8 + 1, w // 8 + 1))[:h, :w]
    # amplitude of dithering ~ half the average palette spacing
    if len(pal) > 1:
        sp = np.median(np.linalg.norm(np.diff(pal, axis=0), axis=1))
    else:
        sp = 1.0
    amp = float(np.clip(dither * sp * 0.55, 0, 0.22))
    src = img_rgb + (tile[..., None] - 0.5) * amp
    d = ((src[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(-1)
    return np.array(valid_idx, np.uint8)[d.argmin(-1)]

def text_mask(text, size, font_path=BODY_FONT, w=None, h=None, tracking=0):
    font = ImageFont.truetype(font_path, size)
    tmp = Image.new("L", (8, 8))
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    W = w or (tw + 4 + tracking * (len(text) - 1))
    H = h or (th + 6)
    im = Image.new("L", (W, H), 0)
    dd = ImageDraw.Draw(im)
    x = (W - tw - tracking * (len(text) - 1)) // 2 - bbox[0]
    for ch in text:
        bb = dd.textbbox((x, 0), ch, font=font)
        dd.text((x, (H - th) // 2 - bbox[1] - 1), ch, font=font, fill=255)
        x += (bb[2] - bb[0]) + tracking + max(0, (tw + tracking * (len(text) - 1)) // max(1, len(text)) - (bb[2] - bb[0]))
    return np.asarray(im, np.float32) / 255.0

def blur2d(a, r=1, passes=2):
    out = a.astype(np.float32)
    for _ in range(passes):
        out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0)
               + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
    return out

def emboss_3d(mask, depth=1.0, bevel=1.6, ambient=0.14, height_scale=1.0):
    """Turn a text mask into a shaded, bevelled, metallic-looking RGBA image."""
    m = mask
    # height field: interior high, edges fall off (bevel)
    hh = m.copy()
    # squeeze the bevel: blur then remap
    b = blur2d(m, passes=2)
    height = np.clip(m * 0.75 + b * 0.25, 0, 1) * height_scale
    gx = np.roll(height, -1, 1) - np.roll(height, 1, 1)
    gy = np.roll(height, -1, 0) - np.roll(height, 1, 0)
    nz = np.ones_like(height) * (0.10 + 0.05 * bevel)
    n = np.stack([gx * bevel * 8, -gy * bevel * 8, nz], -1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    L1 = np.array([-0.5, 0.75, 0.45], np.float32); L1 /= np.linalg.norm(L1)
    L2 = np.array([0.7, -0.2, 0.4], np.float32); L2 /= np.linalg.norm(L2)
    L3 = np.array([0.1, -0.9, 0.3], np.float32); L3 /= np.linalg.norm(L3)
    V = np.array([0, 0, 1], np.float32)
    lam = np.clip((n * L1).sum(-1), 0, 1) * 1.5
    lam2 = np.clip((n * L2).sum(-1), 0, 1) * 0.45
    rim = np.clip((n * L3).sum(-1), 0, 1) ** 2 * 0.6
    spec = np.clip((n * (L1 + V) / np.linalg.norm(L1 + V)).sum(-1), 0, 1) ** 30 * 1.4
    # chrome ramp based on height
    lo = np.array([0.18, 0.22, 0.34], np.float32)
    mid = np.array([0.45, 0.55, 0.78], np.float32)
    hi = np.array([0.95, 0.97, 1.00], np.float32)
    t = np.clip(height, 0, 1)[..., None]
    col = lo[None, None, :] * (1 - t) ** 2 + mid[None, None, :] * (2 * t * (1 - t)) + hi[None, None, :] * t ** 2
    col = col * (ambient + lam)[..., None] + lam2[..., None] * np.array([0.9, 0.75, 0.5], np.float32)[None, None, :]
    col += rim[..., None] * np.array([0.4, 0.7, 1.0], np.float32)[None, None, :]
    col += spec[..., None] * np.array([1.0, 1.0, 1.0], np.float32)[None, None, :]
    rgba = np.zeros(m.shape + (4,), np.float32)
    rgba[..., :3] = col
    rgba[..., 3] = m
    return rgba

def panel_art(x, y, w, h, seed=0):
    """3D-looking metal HUD panel strip rendered procedurally (embossed)."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    plate = 0.45 + 0.30 * np.cos((yy / h) * np.pi * 0.9)
    # rivets and seams
    riv = np.zeros((h, w), np.float32)
    for rx in range(4, w, 24):
        for ry in ((3, h - 4)):
            if ry >= h - 1:
                continue
            d = np.sqrt((xx - rx) ** 2 + (yy - ry) ** 2)
            riv = np.maximum(riv, np.clip(1.3 - d / 2.2, 0, 1))
    seam = (np.abs(((xx + 4) % 32) - 0.5) < 1.2).astype(np.float32) * 0.3
    height = np.clip(plate - seam + riv * 0.5, 0, 1.2)
    gx = np.roll(height, -1, 1) - np.roll(height, 1, 1)
    gy = np.roll(height, -1, 0) - np.roll(height, 1, 0)
    n = np.stack([gx * 9, -gy * 9, np.ones_like(height) * 1.2], -1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    L = np.array([-0.35, 0.7, 0.6], np.float32); L /= np.linalg.norm(L)
    lam = np.clip((n * L).sum(-1), 0, 1)
    base = np.array([0.30, 0.33, 0.40], np.float32)
    col = base[None, None, :] * (0.45 + 1.1 * lam[..., None])
    col += riv[..., None] * np.array([0.55, 0.60, 0.70], np.float32)[None, None, :] * 0.9
    return np.clip(col, 0, 1)
