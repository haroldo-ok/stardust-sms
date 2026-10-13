"""models.py - procedural 3D meshes for the Stardust clone art.

Convention: +X right, +Y up, +Z toward viewer.  Ships point along +Y.
"""
import numpy as np
from scene3d import Mesh, box, cylinder, sphere_mesh, torus, merge, rotate_mesh, normalize


# ---------------------------------------------------------------- primitives

def extrude(poly, z0, z1, color=(0.6, 0.6, 0.65), shift=0.0):
    """Extrude a 2-D polygon (list of (x, y)) along Z, with optional taper."""
    n = len(poly)
    verts = [(x, y, z0) for (x, y) in poly] + [(x * (1 - shift), y * (1 - shift), z1) for (x, y) in poly]
    faces = [tuple(range(n))[::-1], tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return Mesh(verts, faces, [np.asarray(color, np.float32)] * len(faces))


def prism(poly_a, poly_b, color=(0.6, 0.6, 0.65)):
    """Extrude between two arbitrary matching 2-D/3-D point lists."""
    a = [p if len(p) == 3 else (p[0], p[1], 0.0) for p in poly_a]
    b = [p if len(p) == 3 else (p[0], p[1], 1.0) for p in poly_b]
    n = len(a)
    verts = a + b
    faces = [tuple(range(n))[::-1], tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return Mesh(verts, faces, [np.asarray(color, np.float32)] * len(faces))


def spikes(r, count, length, thickness, seed=1, color=(0.7, 0.7, 0.72), axis_z=0.0):
    rng = np.random.default_rng(seed)
    parts = []
    for i in range(count):
        a = 2 * np.pi * i / count + rng.random() * 0.3
        ca, sa = np.cos(a), np.sin(a)
        base = (r * ca, r * sa, axis_z)
        tip = ((r + length) * ca, (r + length) * sa, axis_z)
        # spike as a thin 4-sided cone: approximate with a scaled sphere
        s = sphere_mesh(1.0, 6, 4, center=(0, 0, 0), color=color)
        L = np.hypot(tip[0] - base[0], tip[1] - base[1])
        sc = np.diag([thickness, L * 0.5, thickness]).astype(np.float32)
        v = s.v @ sc.T
        ang = np.arctan2(tip[1] - base[1], tip[0] - base[0]) - np.pi / 2
        c, si = np.cos(ang), np.sin(ang)
        R = np.array([[c, -si, 0], [si, c, 0], [0, 0, 1]], np.float32)
        v = v @ R.T + np.array([(base[0] + tip[0]) / 2, (base[1] + tip[1]) / 2, axis_z], np.float32)
        parts.append(Mesh(v, s.f, s.colors, s.groups))
    return merge(*parts)


def poly_star(points, r_out, r_in, n, rot0=0.0):
    poly = []
    for i in range(n):
        a0 = rot0 + 2 * np.pi * i / n
        a1 = a0 + np.pi / n
        poly.append((r_out * np.cos(a0), r_out * np.sin(a0)) if points == 'peak'
                    else (r_in * np.cos(a0), r_in * np.sin(a0)))
        poly.append((r_in * np.cos(a1), r_in * np.sin(a1)) if points == 'peak'
                    else (r_out * np.cos(a1), r_out * np.sin(a1)))
    return poly


# ---------------------------------------------------------------- ships

HULL_LIGHT = (0.62, 0.68, 0.76)
HULL_MID = (0.40, 0.45, 0.54)
HULL_DARK = (0.20, 0.23, 0.30)
GREEN = (0.10, 0.75, 0.35)
GREEN_HI = (0.45, 1.00, 0.55)
CYAN = (0.30, 0.85, 1.00)
ORANGE = (1.00, 0.62, 0.15)
YELLOW = (1.00, 0.90, 0.35)
RED = (0.95, 0.25, 0.10)
PURPLE = (0.65, 0.25, 0.85)
METAL = (0.55, 0.58, 0.66)


def build_player():
    """Green/steel dart fighter, pointing +Y, span ~0.9."""
    hull = [(0.00, 0.58), (0.075, 0.30), (0.10, 0.02), (0.46, -0.20), (0.50, -0.30),
            (0.16, -0.30), (0.13, -0.44), (-0.13, -0.44), (-0.16, -0.30), (-0.50, -0.30),
            (-0.46, -0.20), (-0.10, 0.02), (-0.075, 0.30)]
    parts = [extrude(hull, -0.055, 0.055, HULL_MID)]
    # dorsal spine
    spine = [(0.00, 0.44), (0.055, 0.10), (0.07, -0.36), (-0.07, -0.36), (-0.055, 0.10)]
    parts.append(extrude(spine, -0.02, 0.10, HULL_LIGHT, shift=0.35))
    # wing leading edge highlight
    lead = [(0.10, 0.02), (0.46, -0.20), (0.50, -0.30), (0.44, -0.32), (0.12, -0.10)]
    parts.append(extrude(lead, -0.058, 0.058, GREEN))
    lead2 = [(-0.10, 0.02), (-0.46, -0.20), (-0.50, -0.30), (-0.44, -0.32), (-0.12, -0.10)]
    parts.append(extrude(lead2, -0.058, 0.058, GREEN))
    # canopy
    parts.append(sphere_mesh(0.085, 8, 5, center=(0.0, 0.22, 0.045), color=CYAN))
    # engine nozzles
    for sx in (-1, 1):
        parts.append(cylinder(0.052, 0.062, 0.09, 8, center=(sx * 0.075, -0.44, 0.0),
                              axis='y', color=HULL_DARK))
        parts.append(cylinder(0.040, 0.040, 0.02, 8, center=(sx * 0.075, -0.455, 0.0),
                              axis='y', color=(1.0, 0.75, 0.35)))
    return merge(*parts)


def build_flame(len_scale=1.0):
    """Exhaust plume pointing -Y (behind the ship); drawn behind the hull."""
    parts = []
    for sx in (-1, 1):
        parts.append(cylinder(0.045, 0.012, 0.10 * len_scale, 7,
                              center=(sx * 0.075, -0.44, 0.0), axis='y',
                              color=(1.0, 0.85, 0.45)))
        parts.append(cylinder(0.030, 0.004, 0.17 * len_scale, 7,
                              center=(sx * 0.075, -0.44, 0.0), axis='y',
                              color=(1.0, 0.55, 0.12)))
    return merge(*parts)


def build_shield():
    return torus(0.50, 0.035, 20, 6, center=(0, 0, 0), axis='z', color=(0.35, 0.85, 1.0))


def build_blade():
    """Crescent stellar blade with a glowing core."""
    outer = [(0.50, 0.30), (0.34, -0.10), (0.05, -0.42), (-0.30, -0.46), (-0.16, -0.16),
             (0.02, 0.02), (0.14, 0.26)]
    inner = [(0.30, 0.16), (0.18, -0.09), (0.01, -0.28), (-0.07, -0.28), (-0.06, -0.13),
             (0.06, 0.02), (0.14, 0.18)]
    parts = [extrude(outer, -0.05, 0.05, (0.72, 0.30, 0.90)),
             extrude(inner, -0.06, 0.06, (0.18, 0.06, 0.28))]
    parts.append(sphere_mesh(0.13, 8, 5, center=(0.02, 0.02, 0.0), color=(1.0, 0.45, 0.9)))
    parts.append(sphere_mesh(0.07, 6, 4, center=(0.02, 0.02, 0.0), color=(1.0, 0.95, 1.0)))
    return merge(*parts)


def build_bomber():
    """Beetle-like bomber."""
    body = sphere_mesh(0.30, 10, 6, center=(0, 0, 0), color=(0.32, 0.30, 0.44))
    sc = np.diag([1.25, 0.9, 1.3]).astype(np.float32)
    body = Mesh(body.v @ sc.T, body.f, body.colors, body.groups)
    shell = [(0.0, 0.34), (0.30, 0.05), (0.26, -0.24), (-0.26, -0.24), (-0.30, 0.05)]
    parts = [body, extrude(shell, 0.06, 0.20, (0.55, 0.52, 0.66), shift=-0.12)]
    parts.append(sphere_mesh(0.11, 6, 4, center=(0, 0.16, 0.20), color=(0.95, 0.35, 0.25)))
    for sx in (-1, 1):
        parts.append(cylinder(0.05, 0.03, 0.30, 6, center=(sx * 0.16, 0.22, 0.0), axis='y',
                              color=(0.25, 0.22, 0.30)))
    parts.append(extrude([(0.0, -0.36), (0.10, -0.24), (0.0, -0.16), (-0.10, -0.24)], -0.05, 0.05,
                         (0.85, 0.55, 0.15)))
    return merge(*parts)


def build_trilon():
    poly = poly_star('peak', 0.46, 0.20, 3)
    parts = [extrude(poly, -0.06, 0.06, (0.55, 0.35, 0.75)),
             sphere_mesh(0.16, 8, 5, center=(0, 0, 0.02), color=(0.95, 0.75, 0.25)),
             sphere_mesh(0.08, 6, 4, center=(0, 0, 0.10), color=(1.0, 1.0, 0.9))]
    return merge(*parts)


def build_plate():
    """Orbit plate: armoured disc with a dome and side pods."""
    parts = [cylinder(0.44, 0.44, 0.10, 14, center=(0, 0, 0.0), axis='z', color=(0.45, 0.48, 0.56)),
             cylinder(0.30, 0.20, 0.10, 12, center=(0, 0, 0.09), axis='z', color=(0.28, 0.30, 0.38)),
             sphere_mesh(0.17, 8, 5, center=(0, 0, 0.16), color=(0.95, 0.30, 0.25))]
    for i in range(4):
        a = np.pi / 4 + i * np.pi / 2
        parts.append(cylinder(0.07, 0.07, 0.12, 6,
                              center=(0.34 * np.cos(a), 0.34 * np.sin(a), 0.05), axis='z',
                              color=(0.75, 0.65, 0.30)))
    return merge(*parts)


def build_speeder():
    hull = [(0.0, 0.56), (0.10, 0.20), (0.34, -0.10), (0.30, -0.22), (0.10, -0.30),
            (0.12, -0.46), (-0.12, -0.46), (-0.10, -0.30), (-0.30, -0.22), (-0.34, -0.10),
            (-0.10, 0.20)]
    parts = [extrude(hull, -0.06, 0.06, (0.62, 0.24, 0.20)),
             extrude([(0.0, 0.40), (0.07, -0.30), (-0.07, -0.30)], -0.03, 0.11, (0.85, 0.35, 0.20)),
             sphere_mesh(0.09, 8, 5, center=(0, 0.20, 0.06), color=(1.0, 0.85, 0.35))]
    for sx in (-1, 1):
        parts.append(cylinder(0.05, 0.02, 0.10, 6, center=(sx * 0.12, -0.48, 0.0), axis='y',
                              color=(1.0, 0.6, 0.2)))
    return merge(*parts)


def build_thorn(seed=3):
    body = sphere_mesh(0.30, 10, 7, center=(0, 0, 0), color=(0.30, 0.26, 0.34))
    sp = spikes(0.29, 11, 0.20, 0.055, seed=seed, color=(0.62, 0.55, 0.70))
    c1 = sphere_mesh(0.11, 6, 4, center=(0.2, 0.1, 0.18), color=(0.85, 0.35, 0.85))
    return merge(body, sp, c1)


def build_mine():
    body = sphere_mesh(0.26, 8, 6, center=(0, 0, 0), color=(0.5, 0.15, 0.15))
    sp = spikes(0.25, 8, 0.16, 0.05, seed=7, color=(0.85, 0.75, 0.5))
    c1 = sphere_mesh(0.10, 6, 4, center=(0, 0, 0.16), color=(1.0, 0.9, 0.4))
    return merge(body, sp, c1)


def build_drone():
    hull = [(0.0, 0.44), (0.16, 0.06), (0.42, -0.16), (0.38, -0.26), (0.12, -0.24),
            (0.0, -0.36), (-0.12, -0.24), (-0.38, -0.26), (-0.42, -0.16), (-0.16, 0.06)]
    parts = [extrude(hull, -0.05, 0.05, (0.45, 0.5, 0.6)),
             sphere_mesh(0.09, 6, 4, center=(0, 0.06, 0.05), color=(1.0, 0.35, 0.3)),
             cylinder(0.04, 0.03, 0.06, 6, center=(0, -0.38, 0), axis='y', color=(1.0, 0.7, 0.3))]
    return merge(*parts)


# ---------------------------------------------------------------- boss parts

def build_boss_gate():
    """Guardian 1: armoured gate whose doors slide open to fire."""
    parts = [box(1.9, 0.42, 0.42, (0, 0.62, 0), (0.42, 0.45, 0.54)),
             box(1.9, 0.42, 0.42, (0, -0.62, 0), (0.42, 0.45, 0.54))]
    for sx in (-1, 1):
        parts.append(box(0.30, 1.4, 0.40, (sx * 0.82, 0.0, 0), (0.3, 0.33, 0.42)))
        parts.append(cylinder(0.13, 0.10, 0.22, 8, center=(sx * 0.82, 0.55, 0.24), axis='z',
                              color=(0.85, 0.4, 0.2)))
    parts.append(sphere_mesh(0.28, 10, 6, center=(0, 0, 0.05), color=(1.0, 0.32, 0.12)))
    parts.append(sphere_mesh(0.16, 8, 5, center=(0, 0, 0.16), color=(1.0, 0.9, 0.5)))
    return merge(*parts)


def build_boss_door(sign=1, open_amount=0.0):
    w = 0.75
    parts = [box(w, 1.15, 0.34, (0, 0, 0), (0.55, 0.58, 0.66))]
    strip = []
    for i in range(5):
        strip.append(box(w * 0.95, 0.10, 0.07, (0, -0.45 + i * 0.22, 0.19), (0.28, 0.30, 0.38)))
    parts += strip
    parts.append(sphere_mesh(0.10, 6, 4, center=(0, 0.40, 0.18), color=(0.9, 0.7, 0.25)))
    return merge(*parts)


def build_boss_eye():
    parts = [sphere_mesh(0.62, 14, 9, center=(0, 0, 0), color=(0.55, 0.20, 0.25))]
    # iris
    parts.append(cylinder(0.30, 0.20, 0.18, 14, center=(0, 0, 0.50), axis='z', color=(0.9, 0.85, 0.95)))
    parts.append(sphere_mesh(0.16, 8, 5, center=(0, 0, 0.62), color=(0.15, 0.05, 0.10)))
    parts.append(sphere_mesh(0.07, 6, 4, center=(0.05, 0.04, 0.70), color=(1, 1, 1)))
    for i in range(6):
        a = 2 * np.pi * i / 6
        parts.append(cylinder(0.06, 0.03, 0.5, 6,
                              center=(0.55 * np.cos(a), 0.55 * np.sin(a), 0.1), axis='z',
                              color=(0.8, 0.45, 0.5)))
        parts.append(sphere_mesh(0.05, 5, 4, center=(0.62 * np.cos(a), 0.62 * np.sin(a), 0.45),
                                 color=(1.0, 0.85, 0.5)))
    return merge(*parts)


def build_boss_arm(k=0):
    """Tentacle segment / appendage for the eye guardian."""
    parts = [sphere_mesh(0.20 - 0.02 * k, 8, 5, center=(0, 0, 0), color=(0.45, 0.16, 0.20)),
             cylinder(0.09, 0.07, 0.16, 8, center=(0, -0.20, 0), axis='y', color=(0.62, 0.35, 0.35))]
    if k == 0:
        parts.append(sphere_mesh(0.10, 6, 4, center=(0, -0.34, 0), color=(1.0, 0.40, 0.35)))
    return merge(*parts)


def build_worm_head():
    parts = [sphere_mesh(0.55, 12, 8, center=(0, 0, 0), color=(0.25, 0.45, 0.22)),
             sphere_mesh(0.30, 8, 5, center=(0, -0.40, 0.10), color=(0.4, 0.6, 0.3))]
    for sx in (-1, 1):
        parts.append(cylinder(0.09, 0.02, 0.46, 6, center=(sx * 0.26, -0.42, 0.16), axis='y',
                              color=(0.85, 0.8, 0.6)))
    for sx in (-1, 1):
        parts.append(sphere_mesh(0.13, 7, 5, center=(sx * 0.24, -0.02, 0.42), color=(1.0, 0.9, 0.4)))
    return merge(*parts)


def build_worm_seg(k=0):
    r = 0.42 - 0.03 * k
    parts = [sphere_mesh(r, 10, 6, center=(0, 0, 0), color=(0.22, 0.40, 0.20))]
    for i in range(4):
        a = np.pi / 4 + i * np.pi / 2
        parts.append(sphere_mesh(r * 0.45, 6, 4,
                                 center=(r * 0.75 * np.cos(a), r * 0.62, r * 0.75 * np.sin(a)),
                                 color=(0.45, 0.62, 0.28)))
    return merge(*parts)


def build_morph_ball():
    parts = [sphere_mesh(0.58, 14, 9, center=(0, 0, 0), color=(0.45, 0.48, 0.58))]
    for i in range(6):
        a = 2 * np.pi * i / 6
        parts.append(sphere_mesh(0.13, 6, 4, center=(0.48 * np.cos(a), 0.48 * np.sin(a), 0.22),
                                 color=(0.95, 0.45, 0.20)))
    parts.append(sphere_mesh(0.24, 8, 5, center=(0, 0, 0.42), color=(1.0, 0.35, 0.25)))
    return merge(*parts)


def build_morph_plate():
    parts = [cylinder(0.62, 0.62, 0.14, 16, center=(0, 0, 0), axis='z', color=(0.5, 0.53, 0.62)),
             cylinder(0.44, 0.30, 0.14, 14, center=(0, 0, 0.12), axis='z', color=(0.30, 0.32, 0.42))]
    for i in range(8):
        a = 2 * np.pi * i / 8
        parts.append(cylinder(0.06, 0.04, 0.16, 6, center=(0.52 * np.cos(a), 0.52 * np.sin(a), 0.08),
                              axis='z', color=(0.9, 0.55, 0.25)))
    parts.append(sphere_mesh(0.20, 8, 5, center=(0, 0, 0.22), color=(0.95, 0.30, 0.55)))
    return merge(*parts)


def build_morph_blades():
    parts = []
    for i in range(3):
        a = 2 * np.pi * i / 3
        blade = [(0.0, 0.0), (0.95, 0.16), (1.05, 0.0), (0.95, -0.16)]
        m = extrude(blade, -0.05, 0.05, (0.62, 0.65, 0.75))
        c, s = np.cos(a), np.sin(a)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)
        parts.append(Mesh(m.v @ R.T, m.f, m.colors, m.groups))
    parts.append(sphere_mesh(0.32, 10, 6, center=(0, 0, 0), color=(0.5, 0.35, 0.6)))
    parts.append(sphere_mesh(0.15, 7, 5, center=(0, 0, 0.22), color=(1.0, 0.75, 0.3)))
    return merge(*parts)


def build_egg_machine():
    parts = [sphere_mesh(0.62, 16, 10, center=(0, 0, 0), color=(0.55, 0.52, 0.44))]
    sc = np.diag([1.0, 1.35, 1.0]).astype(np.float32)
    b = parts[0]
    parts[0] = Mesh(b.v @ sc.T, b.f, b.colors, b.groups)
    for i in range(8):
        a = 2 * np.pi * i / 8
        parts.append(box(0.10, 0.9, 0.10, (0.58 * np.cos(a), 0, 0.0), (0.30, 0.28, 0.24)))
    parts.append(cylinder(0.30, 0.24, 0.14, 14, center=(0, 0.85, 0), axis='y', color=(0.35, 0.32, 0.30)))
    parts.append(sphere_mesh(0.18, 8, 5, center=(0, 0.95, 0), color=(1.0, 0.5, 0.15)))
    parts.append(sphere_mesh(0.15, 8, 5, center=(0, -0.20, 0.55), color=(0.9, 0.25, 0.2)))
    return merge(*parts)


def build_professor():
    """Mad professor: round body, goggles, wild hair."""
    parts = [sphere_mesh(0.34, 10, 7, center=(0, -0.10, 0), color=(0.85, 0.85, 0.9))]
    parts.append(sphere_mesh(0.30, 10, 7, center=(0, 0.28, 0), color=(0.95, 0.82, 0.72)))
    parts.append(sphere_mesh(0.13, 8, 5, center=(0.22, 0.60, 0.05), color=(0.9, 0.9, 0.95)))
    parts.append(sphere_mesh(0.13, 8, 5, center=(-0.22, 0.60, 0.05), color=(0.9, 0.9, 0.95)))
    for sx in (-1, 1):
        parts.append(sphere_mesh(0.11, 8, 5, center=(sx * 0.11, 0.30, 0.24), color=(0.15, 0.15, 0.2)))
    parts.append(cylinder(0.05, 0.05, 0.6, 6, center=(0.0, 0.30, 0.10), axis='y', color=(0.2, 0.2, 0.25)))
    for i in range(7):
        a = np.pi * (i / 6.0)
        parts.append(cylinder(0.035, 0.005, 0.36, 5,
                              center=(0.28 * np.cos(a), 0.52 + 0.1 * np.sin(a), 0.0), axis='y',
                              color=(0.92, 0.92, 0.95)))
    return merge(*parts)


def build_token_ring():
    return merge(torus(0.54, 0.075, 16, 6, center=(0, 0, 0), axis='z', color=(0.95, 0.75, 0.25)))


def build_bolt(color=(1.0, 0.95, 0.5), r=0.20, h=0.7):
    return merge(sphere_mesh(r, 8, 5, center=(0, 0, 0), color=color),
                 cylinder(r * 0.55, 0.0, h, 6, center=(0, 0.1, 0), axis='y', color=color))


def build_orb(color=(1.0, 0.4, 0.3)):
    return merge(sphere_mesh(0.45, 10, 7, center=(0, 0, 0), color=color),
                 sphere_mesh(0.22, 6, 4, center=(0, 0, 0.30), color=(1, 1, 0.9)))


def build_missile():
    parts = [cylinder(0.11, 0.0, 0.55, 8, center=(0, 0.10, 0), axis='y', color=(0.85, 0.85, 0.9)),
             cylinder(0.13, 0.13, 0.35, 8, center=(0, -0.42, 0), axis='y', color=(0.55, 0.58, 0.66)),
             extrude([(0, -0.8), (0.26, -0.5), (0, -0.45), (-0.26, -0.5)], -0.02, 0.02, (0.6, 0.6, 0.68)),
             cylinder(0.08, 0.02, 0.16, 6, center=(0, -0.72, 0), axis='y', color=(1.0, 0.6, 0.2))]
    return merge(*parts)


# ---------------------------------------------------------------- props/bg

def build_terrain_rocks(seed=0):
    """A cluster of angular rocks used inside background scenes."""
    rng = np.random.default_rng(seed)
    parts = []
    for i in range(7):
        r = 0.25 + rng.random() * 0.5
        x = (rng.random() - 0.5) * 4.0
        y = (rng.random() - 0.5) * 1.2
        parts.append(sphere_mesh(r, 7, 5, center=(x, y, 0), color=(0.35, 0.36, 0.42)))
    return merge(*parts)


def build_ring_station():
    parts = [torus(0.9, 0.22, 22, 8, center=(0, 0, 0), axis='y', color=(0.5, 0.52, 0.6)),
             cylinder(0.16, 0.16, 2.0, 8, center=(0, -1.0, 0), axis='y', color=(0.42, 0.45, 0.53)),
             sphere_mesh(0.34, 10, 6, center=(0, 1.1, 0), color=(0.6, 0.63, 0.7))]
    for i in range(6):
        a = 2 * np.pi * i / 6
        parts.append(sphere_mesh(0.10, 6, 4, center=(0.9 * np.cos(a), 0, 0.9 * np.sin(a)),
                                 color=(1.0, 0.7, 0.3)))
    return merge(*parts)


def build_gate_ring():
    """Warp tunnel ring relay (the tunnel itself is drawn as bg art)."""
    return merge(torus(1.0, 0.16, 26, 7, center=(0, 0, 0), axis='y', color=(0.55, 0.6, 0.7)),
                 torus(1.0, 0.06, 26, 5, center=(0, 0, 0), axis='y', color=(0.9, 0.8, 0.4)))
