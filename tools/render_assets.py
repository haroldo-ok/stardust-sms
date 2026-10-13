"""render_assets.py - renders every sprite and background with the software 3D
renderer and caches them as float16 arrays for the SMS asset builder.

Usage:  python3 render_assets.py [--only sprites|bg|all] [--jobs N]
Output: assets/cache/*.npz   float16 RGBA/RGB, final SMS size
        assets/preview/*.png 4x nearest-neighbour previews
"""
import os, sys, time, argparse, zlib
import numpy as np
from PIL import Image

import scene3d as s3
from scene3d import Camera, Light, ValueNoise, render_ball, render_mesh, downsample, bloom, tone_map
import models as M

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
CACHE = os.path.join(ROOT, "cache")
PREV = os.path.join(ROOT, "preview")

S = 10          # supersample factor for sprites (final px -> render px)

# lighting: key from upper-left-front, cool fill from right, rim from behind
SPR_LIGHTS = [
    Light((-0.55, 0.62, 0.56), (1.00, 0.96, 0.88), 1.75, spec=1.0),
    Light((0.75, 0.05, 0.35), (0.30, 0.42, 0.72), 0.70),
    Light((0.10, -0.85, 0.35), (0.34, 0.40, 0.62), 0.35),
]


def save_sprite(name, img, cache_dict, scale_preview=6):
    """img: float RGBA at final pixel size."""
    cache_dict[name] = img.astype(np.float16)
    h, w = img.shape[:2]
    rgb = np.clip(tone_map(img[..., :3], exposure=1.25, gamma=0.95), 0, 1)
    a = np.clip(img[..., 3], 0, 1)
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = (rgb * 255).astype(np.uint8)
    out[..., 3] = (a * 255).astype(np.uint8)
    prev = np.zeros((h * scale_preview, w * scale_preview, 3), np.uint8)
    big = np.repeat(np.repeat(out, scale_preview, 0), scale_preview, 1)
    al = big[..., 3:4] / 255.0
    bg = np.zeros_like(big[..., :3]) + np.array([24, 24, 40], np.uint8)
    prev = (big[..., :3] * al + bg * (1 - al)).astype(np.uint8)
    Image.fromarray(prev).save(os.path.join(PREV, name + ".png"))


def render_mesh_sprite(mesh, w, h, S=S, lights=SPR_LIGHTS, fit=0.80, scale=1.0,
                       tint_boost=1.0, gloss=34.0, rim=0.22, extra=None):
    """Render a mesh with the ortho sprite camera, fit to (w,h) box."""
    W, H = w * S, h * S
    # Fit x and y extents to the camera's half-height, not its full height.
    # The former 0.5 camera cropped most ships and all of the token ring.
    v = mesh.v.copy()
    centre = (v.max(0) + v.min(0)) * 0.5
    centred = mesh.transformed(trans=-centre)
    extent = np.abs(centred.v).max(0)
    ext = max(float(extent[1]), float(extent[0]) / (w / h), 1e-6)
    sc = (fit / ext) * scale
    m = centred.transformed(scale=sc)
    cam = Camera((0, 0, 4.0), (0, 0, 0), up=(0, 1, 0), ortho=1.0, aspect=w / h)
    img, bufs = render_mesh(m, W, H, cam, lights, ambient=(0.09, 0.10, 0.15),
                            gloss=gloss, spec_strength=0.9, rim=rim)
    img[..., :3] *= tint_boost
    im = downsample(img, S)
    return im, cam


def render_rock_sprite(w, h, tint, seed, frames, S=S, rot_axis=(0.2, 0.5, 0.8),
                       disp=0.26, freq=1.5, tint_mul=1.0, glow=0.0):
    """Tumbling meteor: rotate the noise field, keep the light fixed."""
    out = []
    noise = ValueNoise(48, seed)
    ax = np.asarray(rot_axis, np.float32)
    ax = ax / np.linalg.norm(ax)
    for i in range(frames):
        th = 2 * np.pi * i / max(frames, 1)
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]], np.float32)
        R = (np.eye(3, dtype=np.float32) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)).astype(np.float32)
        img, _ = render_ball(w * S, h * S,
                             Camera((0, 0, 3.4), (0, 0, 0), up=(0, 1, 0),
                                    ortho=1.45 * max(1.0, h / w), aspect=w / h),
                             noise, radius=1.0, disp=disp, freq=freq, octaves=4,
                             tint=np.asarray(tint, np.float32) * tint_mul, lights=SPR_LIGHTS,
                             ambient=(0.13, 0.14, 0.19), gloss=18.0, spec_strength=0.5,
                             rim=0.22, rim_col=(0.45, 0.55, 0.9), texture="rock",
                             albedo_var=0.16, dark=0.30, steps=8, seed_off=(seed * 0.37, 0, 0), rot=R)
        im = downsample(img, S)
        if glow > 0:
            im[..., :3] += glow * np.clip(im[..., 3:4], 0, 1)
        out.append(im)
    return out


def render_fire_sprite(w, h, seed, frame, frames, S=S):
    """Explosion: displaced fireball shaded by a hot fire ramp."""
    noise = ValueNoise(20, seed)
    img, (mask, n, p, pr) = render_ball(
        w * S, h * S, Camera((0, 0, 3.4), (0, 0, 0), up=(0, 1, 0),
                             ortho=1.5 * max(1.0, h / w), aspect=w / h),
        noise, radius=1.0, disp=0.30, freq=2.4, octaves=4, tint=(1, 1, 1),
        lights=SPR_LIGHTS, ambient=(0.0, 0.0, 0.0), gloss=6.0, spec_strength=0.0,
        texture="rock", albedo_var=0.0, dark=0.0, steps=8,
        seed_off=(seed * 0.11, frame * 0.85, frame * 0.4))
    cool = np.clip(frame / max(1, frames - 1), 0, 1)
    # noise-driven heat: hot lumps cooled over time
    heat = np.clip(noise.fbm(p * 2.6 + seed + cool * 1.5, octaves=4) * 2.0 - 0.35 - cool * 0.7, 0, 1.4)
    yy, xx = np.mgrid[0:h * S, 0:w * S]
    cx = (xx - w * S / 2) / (w * S * 0.5); cy = (yy - h * S / 2) / (h * S * 0.5)
    rad = np.sqrt(cx * cx + cy * cy)
    core = np.clip(1.55 - rad * 1.55 - cool * 0.55, 0, 1)
    heat = np.clip(heat * (0.55 + 0.9 * core), 0, 1.25)
    dark_c = np.asarray([0.34, 0.045, 0.02], np.float32)
    mid_c = np.asarray([1.00, 0.34, 0.03], np.float32)
    hot_c = np.asarray([1.00, 0.78, 0.18], np.float32)
    wht_c = np.asarray([1.00, 0.97, 0.82], np.float32)
    c = (dark_c[None, None, :] * (1 - np.clip(heat * 1.6, 0, 1))[..., None]
         + mid_c[None, None, :] * np.clip(heat * 1.6, 0, 1)[..., None] * (1 - np.clip(heat * 1.6 - 1, 0, 1))[..., None])
    c += hot_c[None, None, :] * np.clip(heat * 1.6 - 1.0, 0, 1)[..., None]
    c += wht_c[None, None, :] * np.clip(heat * 1.6 - 1.35, 0, 1)[..., None] * 1.5
    c = c * (1.0 - 0.55 * cool * np.clip(rad * 0.8, 0, 1))[..., None]
    rgba = np.zeros((w * S, h * S, 4), np.float32)
    rgba[..., :3] = c
    grow = 1.0 + 0.55 * cool
    keep = mask & (rad / grow < 1.0) & (heat > 0.07 + 0.5 * cool)
    rgba[..., 3] = keep.astype(np.float32)
    return downsample(rgba, S)


# --------------------------------------------------------------------------

def build_sprite_assets(save):
    t0 = time.time()

    def save_frames(name, imgs):
        for i, im in enumerate(imgs):
            save(f"{name}_{i:02d}", im)

    # ---- player: 16 rotations ----
    ship = M.build_player()
    fr = []
    for i in range(16):
        m = M.rotate_mesh(ship, -2 * np.pi * i / 16, 'z')
        im, _ = render_mesh_sprite(m, 16, 16, fit=0.74)
        fr.append(im)
    save_frames("player", fr)
    print("player done", time.time() - t0)

    flame = M.build_flame()
    fr = []
    for i in range(8):
        m = M.rotate_mesh(flame, -2 * np.pi * i / 8, 'z')
        im, _ = render_mesh_sprite(m, 8, 16, fit=0.95)
        fr.append(im)
    save_frames("flame", fr)

    sh = M.build_shield()
    fr = []
    for i, sc in enumerate([0.94, 1.02]):
        m = sh.transformed(scale=sc)
        im, _ = render_mesh_sprite(m, 16, 16, fit=0.96, gloss=60, rim=0.5)
        fr.append(im)
    save_frames("shield", fr)

    # ---- meteors: 4 tints ----
    tints = {
        "rock_grey":   ((0.52, 0.53, 0.56), 1),
        "rock_blue":   ((0.34, 0.42, 0.62), 1),
        "rock_purple": ((0.48, 0.32, 0.60), 1),
        "rock_gold":   ((0.72, 0.58, 0.26), 1),
    }
    sizes = {"big": (24, 24, 4, 0.24, 2.2), "med": (16, 16, 4, 0.24, 2.2),
             "small": (8, 8, 4, 0.22, 2.6)}
    for name, (tint, tm) in tints.items():
        for sz, (w, h, nf, disp, freq) in sizes.items():
            imgs = render_rock_sprite(w, h, tint, seed=zlib.crc32((name + sz).encode()) % 9999,
                                      frames=nf, rot_axis=(0.3, 0.55, -0.75),
                                      disp=disp, freq=freq, tint_mul=tm)
            save_frames(f"{name}_{sz}", imgs)
    print("rocks done", time.time() - t0)

    # ---- enemies ----
    ENEMY = {
        "blade":  (M.build_blade(), 16, 16, 8, -1),
        "bomber": (M.build_bomber(), 16, 16, 4, 0.5),
        "trilon": (M.build_trilon(), 16, 16, 4, 0.33),
        "plate":  (M.build_plate(), 16, 16, 4, -1),
        "speeder": (M.build_speeder(), 16, 16, 4, -1),
        "thorn":  (M.build_thorn(), 16, 16, 4, 0.20),
        "drone":  (M.build_drone(), 16, 16, 4, -1),
    }
    for name, (mesh, w, h, nf, r0) in ENEMY.items():
        imgs = []
        for i in range(nf):
            m = M.rotate_mesh(mesh, (r0 if r0 >= 0 else 0) + 2 * np.pi * i / nf, 'z')
            im, _ = render_mesh_sprite(m, w, h, fit=0.78)
            imgs.append(im)
        save_frames(name, imgs)

    # mine
    imgs = [render_mesh_sprite(M.rotate_mesh(M.build_mine(), 2 * np.pi * i / 2, 'z'), 8, 16, fit=0.9)[0]
            for i in range(2)]
    save_frames("mine", imgs)

    # ---- tokens / projectiles ----
    ring = M.build_token_ring()
    imgs = [render_mesh_sprite(M.rotate_mesh(ring, 2 * np.pi * i / 4, 'z'), 16, 16, fit=0.86, gloss=70)[0]
            for i in range(4)]
    save_frames("token", imgs)

    bolt = M.build_bolt(color=(1.0, 0.95, 0.55))
    imgs = [render_mesh_sprite(bolt.transformed(scale=0.9 + 0.2 * i), 8, 16, fit=0.9, rim=0.5)[0]
            for i in range(2)]
    save_frames("bolt", imgs)

    orb = M.build_orb(color=(1.0, 0.35, 0.25))
    imgs = [render_mesh_sprite(orb.transformed(scale=0.85 + 0.25 * i), 8, 16, fit=0.9, rim=0.4)[0]
            for i in range(2)]
    save_frames("orb", imgs)

    miss = M.build_missile()
    imgs = []
    for i in range(4):
        m = M.rotate_mesh(miss, -2 * np.pi * i / 4, 'z')
        im, _ = render_mesh_sprite(m, 8, 16, fit=0.92)
        imgs.append(im)
    save_frames("missile", imgs)
    print("enemies/tokens done", time.time() - t0)

    # ---- explosions ----
    save_frames("expl_big", [render_fire_sprite(16, 16, 991, i, 5) for i in range(5)])
    save_frames("expl_small", [render_fire_sprite(8, 8, 313, i, 5) for i in range(5)])
    print("explosions done", time.time() - t0)

    # ---- boss part ----
    boss_parts(save)
    print("all sprites done", time.time() - t0)


def boss_parts(save):
    def frames(name, mesh, w, h, nf, rot_axis='z', fit=0.8, r0=0.0, **kw):
        out = []
        for i in range(nf):
            m = M.rotate_mesh(mesh, r0 + 2 * np.pi * i / nf, rot_axis) if nf > 1 else mesh
            im, _ = render_mesh_sprite(m, w, h, fit=fit, **kw)
            out.append(im)
        for i, im in enumerate(out):
            save(f"{name}_{i:02d}", im)

    # guardian 1 - the gate
    frames("b1_housing", M.box(1.9, 0.44, 0.44, (0, 0, 0), (0.42, 0.45, 0.54)), 32, 16, 1, fit=0.95)
    frames("b1_pillar", M.box(0.42, 1.5, 0.44, (0, 0, 0), (0.30, 0.33, 0.42)), 16, 32, 1, fit=0.95)
    frames("b1_door", M.build_boss_door(), 16, 32, 1, fit=0.95)
    frames("b1_core", M.merge(M.sphere_mesh(0.42, 12, 8, center=(0, 0, 0), color=(1.0, 0.32, 0.12)),
                              M.sphere_mesh(0.24, 8, 5, center=(0, 0, 0.28), color=(1.0, 0.9, 0.5))),
           16, 16, 4, fit=0.9)
    frames("b1_turret", M.cylinder(0.22, 0.16, 0.34, 10, center=(0, 0, 0), axis='z', color=(0.85, 0.4, 0.2)),
           16, 16, 4, fit=0.9, r0=0.3)

    # guardian 2 - tailed eye
    frames("b2_eye", M.build_boss_eye(), 32, 32, 4, fit=0.9)
    frames("b2_arm", M.build_boss_arm(0), 16, 16, 4, fit=0.85, r0=0.5)

    # guardian 3 - space worm
    frames("b3_head", M.build_worm_head(), 32, 32, 4, fit=0.9)
    frames("b3_seg", M.build_worm_seg(0), 24, 24, 2, fit=0.92)
    frames("b3_tail", M.build_worm_seg(2), 24, 24, 2, fit=0.92)

    # guardian 4 - morph runner
    frames("b4_ball", M.build_morph_ball(), 32, 32, 4, fit=0.9)
    frames("b4_plate", M.build_morph_plate(), 32, 32, 4, fit=0.9)
    frames("b4_blades", M.build_morph_blades(), 32, 32, 4, fit=0.9)

    # guardian 5 - the professor
    frames("b5_egg", M.build_egg_machine(), 32, 48, 4, fit=0.9)
    frames("b5_hatch", M.cylinder(0.34, 0.30, 0.18, 12, center=(0, 0, 0), axis='z',
                                  color=(0.32, 0.30, 0.28)), 16, 16, 1, fit=0.9)
    frames("b5_prof", M.build_professor(), 32, 32, 4, fit=0.85)


# --------------------------------------------------------------------------
# backgrounds
# --------------------------------------------------------------------------

BG_W, BG_H = 256, 192
BG_S = 4


def render_bg_sky(seed, palette, nebula_col, nebula_col2, nebula_col3=None, density=0.8,
                  scale=1.5, stars=1400, grad=(0.0, 0.0, 0.0), planets=None, sun=None,
                  glow=0.0, extra_meshes=None, mesh_light=None, mesh_scale=1.0, cam_eye=(0, 0, 0),
                  cam_tgt=(0, 0, 1), fov=60.0, clouds_hi=0.0):
    noise = ValueNoise(20, seed)
    W, H = BG_W * BG_S, BG_H * BG_S
    cam = Camera(cam_eye, cam_tgt, up=(0, 1, 0), fov=fov, aspect=BG_W / BG_H)
    acc, _ = s3.render_space_bg(W, H, cam, noise, palette=palette, nebula_col=nebula_col,
                                nebula_col2=nebula_col2, density=density, scale=scale,
                                steps=13, stars=stars, grad=grad, planets=planets,
                                clouds_hi=clouds_hi)
    if sun and sun[2] > 0:
        sx, sy, r, col = sun
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2) / r
        acc += np.asarray(col, np.float32)[None, None, :] * np.exp(-d * d * 1.6)[..., None] * 0.32
        acc += np.asarray(col, np.float32)[None, None, :] * np.exp(-d * d * 12.0)[..., None] * 0.70
    if extra_meshes:
        lights = mesh_light or [Light((-0.5, 0.55, 0.6), (1.0, 0.95, 0.85), 1.0, spec=1.0),
                                Light((0.6, -0.2, 0.5), (0.3, 0.4, 0.7), 0.4)]
        for mesh, params in extra_meshes:
            m = mesh.transformed(scale=params.get("scale", 1.0) * mesh_scale,
                                 rot=params.get("rot"), trans=params.get("pos", (0, 0, 0)))
            img, _ = render_mesh(m, W, H, cam, lights, ambient=params.get("amb", (0.08, 0.09, 0.14)),
                                 gloss=params.get("gloss", 24.0), spec_strength=0.7,
                                 rim=params.get("rim", 0.25), rim_col=params.get("rimcol", (0.4, 0.5, 0.9)))
            a = img[..., 3:4]
            acc = acc * (1 - a) + img[..., :3] * a
    if glow > 0:
        acc = s3.bloom(np.concatenate([acc, np.ones((H, W, 1), np.float32)], -1), threshold=0.6,
                       radius=4, strength=glow)[..., :3]
    rgb = downsample(acc[..., None] if False else np.concatenate(
        [acc, np.ones((H, W, 1), np.float32)], -1), BG_S)[..., :3]
    return tone_map(rgb, exposure=1.45, gamma=1.05)


def build_bg_assets(save):
    t0 = time.time()
    # --- title art: big logo scene ---
    title = render_bg_sky(
        11, palette=(0.015, 0.02, 0.05), nebula_col=(0.42, 0.16, 0.55),
        nebula_col2=(0.08, 0.22, 0.55), density=0.9, scale=1.35, stars=1800,
        planets=[dict(x=78 * BG_S, y=120 * BG_S, r=62 * BG_S, seed=(3.0, 1.0, 0.0),
                      sea=(0.05, 0.09, 0.25), land=(0.30, 0.34, 0.16), tfreq=2.2,
                      atmo=0.85, atmocol=(0.35, 0.55, 1.0), light=(-0.55, 0.55, 0.62)),
                 dict(x=205 * BG_S, y=52 * BG_S, r=26 * BG_S, seed=(9.0, 2.0, 1.0),
                      sea=(0.35, 0.15, 0.10), land=(0.45, 0.22, 0.12), tfreq=3.0, atmo=0.4,
                      atmocol=(1.0, 0.6, 0.4), light=(-0.55, 0.55, 0.62))],
        sun=(120 * BG_S, 40 * BG_S, 90 * BG_S, (1.0, 0.85, 0.6)), glow=0.5)
    save("bg_title", np.concatenate([title, np.ones(title.shape[:2] + (1,), np.float32)], -1))

    # --- per-world playfield backgrounds ---
    worlds = [
        # W1 - blue/teal nebula, gas giant
        dict(seed=21, palette=(0.015, 0.02, 0.05), nebula_col=(0.10, 0.35, 0.60),
             nebula_col2=(0.25, 0.10, 0.45), density=0.75, scale=1.3, stars=1200,
             grad=(0.02, 0.03, 0.07),
             planets=[dict(x=196 * BG_S, y=150 * BG_S, r=54 * BG_S, seed=(1.0, 4.0, 2.0),
                           sea=(0.06, 0.14, 0.30), land=(0.25, 0.30, 0.20), band=0.8,
                           bandcol=(0.6, 0.75, 0.95), bandfreq=16.0, tfreq=2.0,
                           atmo=0.9, atmocol=(0.35, 0.65, 1.0), light=(-0.5, 0.6, 0.62))],
             sun=(60 * BG_S, 34 * BG_S, 70 * BG_S, (0.7, 0.85, 1.0)), glow=0.45),
        # W2 - red rocky world with a surface at the bottom
        dict(seed=33, palette=(0.05, 0.02, 0.02), nebula_col=(0.55, 0.16, 0.10),
             nebula_col2=(0.30, 0.12, 0.25), density=0.7, scale=1.5, stars=900,
             grad=(0.04, 0.015, 0.02),
             planets=[dict(x=52 * BG_S, y=40 * BG_S, r=40 * BG_S, seed=(5.0, 1.0, 3.0),
                           sea=(0.28, 0.10, 0.06), land=(0.55, 0.22, 0.10), tfreq=3.4,
                           atmo=0.55, atmocol=(1.0, 0.45, 0.25), light=(-0.5, 0.6, 0.62))],
             sun=(210 * BG_S, 150 * BG_S, 80 * BG_S, (1.0, 0.55, 0.25)), glow=0.5,
             extra_meshes=[(M.build_terrain_rocks(2),
                            dict(pos=(0, -1.15, 0.4), scale=0.5, rot=None,
                                 amb=(0.06, 0.04, 0.05), rim=0.35, rimcol=(1.0, 0.5, 0.3)))],
             mesh_light=[Light((-0.5, 0.45, 0.7), (1.0, 0.55, 0.35), 1.1, spec=1.0),
                         Light((0.5, 0.1, 0.5), (0.4, 0.12, 0.2), 0.5)]),
        # W3 - green nebula, crystal field
        dict(seed=47, palette=(0.01, 0.03, 0.02), nebula_col=(0.12, 0.55, 0.30),
             nebula_col2=(0.05, 0.25, 0.40), density=0.85, scale=1.2, stars=1000,
             grad=(0.01, 0.04, 0.02),
             planets=[dict(x=210 * BG_S, y=44 * BG_S, r=30 * BG_S, seed=(7.0, 2.0, 5.0),
                           sea=(0.10, 0.30, 0.20), land=(0.45, 0.60, 0.25), tfreq=3.0,
                           atmo=0.6, atmocol=(0.5, 1.0, 0.6), light=(-0.5, 0.6, 0.62))],
             sun=(30 * BG_S, 150 * BG_S, 70 * BG_S, (0.6, 1.0, 0.7)), glow=0.4,
             extra_meshes=[(M.build_terrain_rocks(5),
                            dict(pos=(0, -1.2, 0.4), scale=0.55, amb=(0.03, 0.07, 0.04),
                                 rim=0.4, rimcol=(0.4, 1.0, 0.5)))],
             mesh_light=[Light((-0.5, 0.5, 0.7), (0.7, 1.0, 0.8), 1.0, spec=1.0),
                         Light((0.5, -0.2, 0.4), (0.15, 0.35, 0.25), 0.5)]),
        # W4 - violet, dying star, ringed planet
        dict(seed=59, palette=(0.03, 0.01, 0.05), nebula_col=(0.45, 0.15, 0.60),
             nebula_col2=(0.15, 0.10, 0.45), density=0.9, scale=1.4, stars=1500,
             grad=(0.03, 0.01, 0.05),
             planets=[dict(x=64 * BG_S, y=118 * BG_S, r=44 * BG_S, seed=(4.0, 7.0, 1.0),
                           sea=(0.14, 0.08, 0.24), land=(0.34, 0.16, 0.40), tfreq=2.6,
                           atmo=0.7, atmocol=(0.8, 0.45, 1.0), light=(-0.55, 0.5, 0.62),
                           ring=1.0, ringcol=(0.75, 0.62, 0.55))],
             sun=(0, 0, 0, (0, 0, 0)), glow=0.5),
        # W5 - fortress world, dark with orange machinery
        dict(seed=71, palette=(0.02, 0.015, 0.02), nebula_col=(0.35, 0.14, 0.10),
             nebula_col2=(0.20, 0.10, 0.22), density=0.6, scale=1.6, stars=700,
             grad=(0.03, 0.02, 0.02),
             planets=[dict(x=190 * BG_S, y=42 * BG_S, r=36 * BG_S, seed=(8.0, 3.0, 3.0),
                           sea=(0.10, 0.08, 0.10), land=(0.28, 0.16, 0.10), tfreq=3.2,
                           atmo=0.35, atmocol=(1.0, 0.55, 0.3), light=(-0.5, 0.6, 0.62))],
             sun=(120 * BG_S, 160 * BG_S, 90 * BG_S, (1.0, 0.5, 0.2)), glow=0.55,
             extra_meshes=[(M.build_ring_station(),
                            dict(pos=(0.1, -0.95, 0.5), scale=0.42, amb=(0.05, 0.04, 0.05),
                                 rim=0.45, rimcol=(1.0, 0.6, 0.3)))],
             mesh_light=[Light((-0.5, 0.5, 0.7), (1.0, 0.75, 0.5), 1.0, spec=1.0),
                         Light((0.6, -0.1, 0.4), (0.5, 0.2, 0.1), 0.5)]),
    ]
    for i, wdef in enumerate(worlds, start=1):
        rgb = render_bg_sky(**wdef)
        save(f"bg_world{i}", np.concatenate([rgb, np.ones(rgb.shape[:2] + (1,), np.float32)], -1))
        print(f"world {i} bg done", time.time() - t0)

    # --- warp tunnel: perspective rings ---
    noise = ValueNoise(20, 99)
    W, H = BG_W * BG_S, BG_H * BG_S
    rings = []
    for i in range(14):
        z = 1.4 + i * 0.85
        r = 1.8
        rings.append((M.torus(r, 0.08, 40, 8, center=(0, 0, z), axis='z',
                              color=(0.45 + 0.03 * i, 0.55, 0.72)),
                      dict(amb=(0.10, 0.14, 0.23), rim=0.4, rimcol=(0.4, 0.8, 1.0))))
    tun = render_bg_sky(83, palette=(0.005, 0.005, 0.02), nebula_col=(0.10, 0.20, 0.55),
                        nebula_col2=(0.25, 0.10, 0.45), density=0.45, scale=2.0, stars=2200,
                        planets=None, sun=(128 * BG_S, 96 * BG_S, 25 * BG_S, (0.3, 0.5, 1.0)), glow=0.6,
                        extra_meshes=rings, mesh_scale=1.0,
                        mesh_light=[Light((-0.4, 0.4, -0.8), (0.9, 0.95, 1.0), 1.1, spec=1.0),
                                    Light((0.6, 0.1, -0.3), (0.4, 0.3, 0.8), 0.6)],
                        cam_eye=(0, 0, 0), cam_tgt=(0, 0, 1), fov=70.0)
    save("bg_tunnel", np.concatenate([tun, np.ones(tun.shape[:2] + (1,), np.float32)], -1))
    print("tunnel done", time.time() - t0)

    # --- map screen: star chart ---
    mp = render_bg_sky(97, palette=(0.01, 0.012, 0.03), nebula_col=(0.20, 0.15, 0.45),
                       nebula_col2=(0.06, 0.18, 0.40), density=0.6, scale=1.7, stars=900,
                       planets=[dict(x=226 * BG_S, y=164 * BG_S, r=40 * BG_S, seed=(2.0, 9.0, 4.0),
                                     sea=(0.10, 0.16, 0.30), land=(0.30, 0.26, 0.22), tfreq=3.0,
                                     atmo=0.6, atmocol=(0.4, 0.7, 1.0), light=(-0.5, 0.6, 0.62))],
                       glow=0.35)
    save("bg_map", np.concatenate([mp, np.ones(mp.shape[:2] + (1,), np.float32)], -1))

    # --- ending: victory over the professor's world ---
    en = render_bg_sky(113, palette=(0.02, 0.02, 0.06), nebula_col=(0.30, 0.35, 0.65),
                       nebula_col2=(0.50, 0.20, 0.45), density=0.8, scale=1.3, stars=1600,
                       planets=[dict(x=128 * BG_S, y=126 * BG_S, r=52 * BG_S, seed=(6.0, 6.0, 6.0),
                                     sea=(0.08, 0.16, 0.30), land=(0.30, 0.34, 0.20), tfreq=2.4,
                                     atmo=1.0, atmocol=(0.5, 0.75, 1.0), light=(-0.5, 0.6, 0.62))],
                       sun=(30 * BG_S, 30 * BG_S, 110 * BG_S, (1.0, 0.9, 0.7)), glow=0.55)
    save("bg_end", np.concatenate([en, np.ones(en.shape[:2] + (1,), np.float32)], -1))
    print("all backgrounds done", time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="all")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(PREV, exist_ok=True)

    # sprite cache: accumulate in a dict, save at the end
    if args.only in ("all", "sprites"):
        store = {}

        def save(name, img):
            store[name] = img.astype(np.float16)
            h, w = img.shape[:2]
            sp = max(1, int(96 // max(w, h)))
            rgb = np.clip(tone_map(img[..., :3], exposure=1.3, gamma=0.95), 0, 1)
            a = np.clip(img[..., 3], 0, 1)
            big = np.repeat(np.repeat(np.dstack([rgb, a]), sp, 0), sp, 1)
            al = big[..., 3:4]
            bg = np.zeros_like(big[..., :3]) + np.array([26, 26, 44], np.float32) / 255
            prev = ((big[..., :3] * al + bg * (1 - al)) * 255).astype(np.uint8)
            Image.fromarray(prev).save(os.path.join(PREV, name + ".png"))
        build_sprite_assets(save)
        np.savez_compressed(os.path.join(CACHE, "sprites.npz"), **store)
        print("saved", len(store), "sprites")

    if args.only in ("all", "bg"):
        store = {}

        def save(name, img):
            store[name] = img.astype(np.float16)
            rgb = np.clip(tone_map(img[..., :3], exposure=1.2, gamma=0.95), 0, 1)
            Image.fromarray((rgb * 255).astype(np.uint8)).resize(
                (256 * 3, 192 * 3), Image.NEAREST).save(os.path.join(PREV, name + ".png"))
        build_bg_assets(save)
        np.savez_compressed(os.path.join(CACHE, "bg.npz"), **store)
        print("saved", len(store), "backgrounds")


if __name__ == "__main__":
    main()
