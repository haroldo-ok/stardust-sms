"""scene3d.py - small software 3D renderer used to prerender art for the
Sega Master System Stardust clone.

Provides:
  * value-noise / fbm fields
  * ray-rendered displaced spheres (meteors, planets, suns, stars)
  * z-buffered triangle rasterizer with Phong shading (ships, bosses, props)
  * nebula/starfield volumetric backgrounds rendered from a camera
  * supersampling, bloom, tone mapping

All images are float32 linear RGB with an alpha (coverage) channel.
"""
import numpy as np

# --------------------------------------------------------------------------
# math helpers
# --------------------------------------------------------------------------

def normalize(v, eps=1e-12):
    n = np.sqrt(np.sum(v * v, axis=-1, keepdims=True))
    return v / np.maximum(n, eps)


def smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


class ValueNoise:
    """Seamless-ish 3D value noise with fbm."""

    def __init__(self, res=16, seed=0):
        rng = np.random.default_rng(seed)
        self.res = res
        self.g = rng.random((res, res, res)).astype(np.float32)

    def _trilerp(self, coords):
        res = self.res
        x, y, z = coords[..., 0], coords[..., 1], coords[..., 2]
        xi, yi, zi = np.floor(x), np.floor(y), np.floor(z)
        tx, ty, tz = smoothstep(x - xi), smoothstep(y - yi), smoothstep(z - zi)
        xi = xi.astype(np.int32) % res; yi = yi.astype(np.int32) % res; zi = zi.astype(np.int32) % res
        xi1 = (xi + 1) % res; yi1 = (yi + 1) % res; zi1 = (zi + 1) % res
        g = self.g
        c000 = g[xi, yi, zi];   c100 = g[xi1, yi, zi]
        c010 = g[xi, yi1, zi];  c110 = g[xi1, yi1, zi]
        c001 = g[xi, yi, zi1];  c101 = g[xi1, yi, zi1]
        c011 = g[xi, yi1, zi1]; c111 = g[xi1, yi1, zi1]
        c00 = c000 + (c100 - c000) * tx
        c10 = c010 + (c110 - c010) * tx
        c01 = c001 + (c101 - c001) * tx
        c11 = c011 + (c111 - c011) * tx
        c0 = c00 + (c10 - c00) * ty
        c1 = c01 + (c11 - c01) * ty
        return c0 + (c1 - c0) * tz

    def fbm(self, coords, octaves=4, gain=0.5, lac=2.03):
        total = np.zeros(coords.shape[:-1], np.float32)
        amp, freq, norm = 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += amp * self._trilerp(coords * freq)
            norm += amp
            amp *= gain
            freq *= lac
        return total / norm

    def ridged(self, coords, octaves=4):
        total = np.zeros(coords.shape[:-1], np.float32)
        amp, freq, norm = 1.0, 1.0, 0.0
        for _ in range(octaves):
            v = self._trilerp(coords * freq)
            total += amp * (1.0 - np.abs(v * 2.0 - 1.0))
            norm += amp
            amp *= 0.5
            freq *= 2.07
        return total / norm


# --------------------------------------------------------------------------
# lighting
# --------------------------------------------------------------------------

class Light:
    def __init__(self, direction, color, intensity=1.0, spec=0.0):
        self.dir = normalize(np.asarray(direction, np.float32))
        self.col = np.asarray(color, np.float32) * intensity
        self.spec = spec


def blinn_phong(n, l, v, albedo, lights, ambient=(0.10, 0.11, 0.16), gloss=24.0,
                spec_strength=0.7, rim=0.0, rim_col=(0.5, 0.6, 1.0)):
    """n,l,v: (...,3) unit vectors.  albedo: (...,3) or (3,)."""
    out = np.zeros(n.shape, np.float32)
    amb = np.asarray(ambient, np.float32) * np.asarray(albedo, np.float32)
    out += amb
    for lt in lights:
        ndl = np.maximum(np.sum(n * lt.dir, axis=-1), 0.0)
        out += ndl[..., None] * lt.col * np.asarray(albedo, np.float32)
        if lt.spec > 0:
            h = normalize(lt.dir + v)
            ndh = np.maximum(np.sum(n * h, axis=-1), 0.0)
            out += lt.spec * lt.col * (ndh ** gloss)[..., None] * spec_strength
    if rim > 0:
        ndv = np.maximum(np.sum(n * v, axis=-1), 0.0)
        f = (1.0 - ndv) ** 3.0
        out += rim * f[..., None] * np.asarray(rim_col, np.float32)
    return out


def tone_map(img, exposure=1.0, gamma=1.0):
    x = np.clip(img * exposure, 0.0, None)
    x = x / (1.0 + x)                      # Reinhard
    return np.clip(x, 0, 1) ** gamma


# --------------------------------------------------------------------------
# camera / rays
# --------------------------------------------------------------------------

class Camera:
    def __init__(self, eye, target, up=(0, 1, 0), fov=40.0, aspect=1.0, ortho=None):
        self.eye = np.asarray(eye, np.float32)
        self.fwd = normalize(np.asarray(target, np.float32) - self.eye)
        self.right = normalize(np.cross(self.fwd, np.asarray(up, np.float32)))
        self.up = np.cross(self.right, self.fwd)
        self.fov = fov
        self.aspect = aspect
        self.ortho = ortho              # if set: half-height of ortho view

    def rays(self, w, h):
        xs = (np.arange(w, dtype=np.float32) + 0.5) / w * 2 - 1
        ys = 1 - (np.arange(h, dtype=np.float32) + 0.5) / h * 2
        xg, yg = np.meshgrid(xs, ys)
        if self.ortho is None:
            t = np.tan(np.radians(self.fov) * 0.5)
            d = (self.fwd[None, None, :]
                 + self.right[None, None, :] * (xg * t * self.aspect)[..., None]
                 + self.up[None, None, :] * (yg * t)[..., None])
            o = np.broadcast_to(self.eye, d.shape).copy()
            return o, normalize(d)
        o = (self.eye[None, None, :]
             + self.right[None, None, :] * (xg * self.ortho * self.aspect)[..., None]
             + self.up[None, None, :] * (yg * self.ortho)[..., None])
        d = np.broadcast_to(self.fwd, o.shape).copy()
        return o.astype(np.float32), normalize(d)


# --------------------------------------------------------------------------
# ray-rendered displaced sphere (meteors, planets, moons)
# --------------------------------------------------------------------------

def render_ball(w, h, cam, noise, *, radius=1.0, disp=0.22, freq=2.6, octaves=4,
                tint=(0.55, 0.55, 0.58), lights=None, ambient=(0.10, 0.11, 0.16),
                gloss=18.0, spec_strength=0.5, rim=0.0, rim_col=(0.5, 0.6, 1.0), texture="rock",
                seed_off=(0.0, 0.0, 0.0), albedo_var=0.25, dark=0.25, steps=9, rot=None,
                bump_amt=0.9, detail_col=0.35):
    """Ray-march a displaced sphere; the craggy silhouette is found by bisection so
    the outline itself looks hand-modelled.  Normals come from the true gradient of
    the implicit surface |x| - surf_r(x)."""
    o, d = cam.rays(w, h)
    b = np.sum(o * d, axis=-1)
    c = np.sum(o * o, axis=-1) - radius * radius
    disc = b * b - c
    hit = disc > 0
    t = np.where(hit, -b - np.sqrt(np.maximum(disc, 0)), 0.0).astype(np.float32)
    soff = np.asarray(seed_off, np.float32)
    R = rot
    freq = float(freq)

    def surf_r(p):                       # p: (...,3) points (any length)
        q = (p @ R) if R is not None else p
        pl = np.sqrt(np.maximum(np.sum(q * q, axis=-1, keepdims=True), 1e-9))
        qu = q / pl * freq + soff
        if texture == "rock":
            f = noise.fbm(qu, octaves=octaves) * 2.0 - 1.0
            cr = noise.ridged(qu * 2.4 + 5.0, octaves=3) - 0.5
            return radius * (1.0 + disp * f) - 0.055 * cr * radius
        if texture == "planet":
            f = noise.fbm(qu * 0.8, octaves=4) * 2.0 - 1.0
            return radius * (1.0 + disp * 0.3 * f)
        return radius * (1.0 + disp * (noise.fbm(qu, octaves=octaves) * 2 - 1))

    # bisection for the front surface
    lo = t.copy()
    hi = t + 0.6 * radius
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        p = o + mid[..., None] * d
        f = np.sqrt(np.maximum(np.sum(p * p, axis=-1), 1e-9)) - surf_r(p)
        inside = f < 0
        hi = np.where(inside, mid, hi)
        lo = np.where(inside, lo, mid)
    ts = 0.5 * (lo + hi)
    p = o + ts[..., None] * d
    sdf = np.sqrt(np.maximum(np.sum(p * p, axis=-1), 1e-9)) - surf_r(p)
    mask = hit & (sdf < 0.03 * radius)

    def F(x):
        return np.sqrt(np.maximum(np.sum(x * x, axis=-1), 1e-9)) - surf_r(x)

    eps = 0.012 * radius
    g = np.empty(p.shape, np.float32)
    for i in range(3):
        dp = np.zeros(3, np.float32); dp[i] = eps
        g[..., i] = F(p + dp) - F(p - dp)
    n = normalize(g)
    nrm_unit = normalize(p)
    flip = np.sum(n * nrm_unit, axis=-1, keepdims=True) < 0
    n = np.where(flip, -n, n)

    v = -d
    alb = np.asarray(tint, np.float32) * np.ones(p.shape, np.float32)
    if texture == "rock":
        det = noise.fbm(p * freq * 2.6 + soff * 1.7, octaves=3)
        alb = alb * (1.0 - albedo_var + albedo_var * 2.0 * det)[..., None]
        cav = np.clip(0.5 - sdf / (max(disp, 1e-3) * radius) * 0.5, 0, 1)
        alb = alb * (1.0 - dark * (1.0 - cav))[..., None]
    elif texture == "planet":
        cont = noise.fbm(p * freq * 0.5 + soff, octaves=4)
        land = smoothstep(np.clip((cont - 0.44) * 6.0 + 0.5, 0, 1))
        sea = np.asarray([0.02, 0.08, 0.22], np.float32)
        land_c = np.asarray([0.30, 0.38, 0.15], np.float32)
        alb = (sea[None, None, :] * (1 - land)[..., None] + land_c[None, None, :] * land[..., None])
        alb = alb * (1.0 + detail_col * (noise.fbm(p * freq * 5.0, octaves=3)[..., None] - 0.5) * 2.0)
        alb = alb * np.asarray(tint, np.float32)[None, None, :]
    lights = lights or []
    col = blinn_phong(n, v, v, alb, lights, ambient=ambient, gloss=gloss,
                      spec_strength=spec_strength, rim=rim, rim_col=rim_col)
    rgba = np.zeros((h, w, 4), np.float32)
    rgba[..., :3] = col
    rgba[..., 3] = mask.astype(np.float32)
    return rgba, (mask, n, p, np.sqrt(np.sum(p * p, axis=-1)))


# --------------------------------------------------------------------------
# mesh rasterizer
# --------------------------------------------------------------------------

class Mesh:
    def __init__(self, verts, faces, colors=None, groups=None):
        self.v = np.asarray(verts, np.float32)
        self.f = [np.asarray(f, np.int32) for f in faces]
        self.colors = colors if colors is not None else [np.array([0.6, 0.6, 0.65], np.float32)] * len(self.f)
        self.groups = groups if groups is not None else ["body"] * len(self.f)

    def transformed(self, scale=1.0, rot=None, trans=(0, 0, 0)):
        v = self.v * scale
        if rot is not None:
            v = v @ np.asarray(rot, np.float32).T
        v = v + np.asarray(trans, np.float32)
        return Mesh(v, self.f, self.colors, self.groups)


def box(w, h, d, center=(0, 0, 0), color=(0.6, 0.6, 0.65)):
    cx, cy, cz = center
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    z0, z1 = cz - d / 2, cz + d / 2
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (3, 2, 6, 7), (4, 5, 1, 0)]
    return Mesh(v, f, [np.asarray(color, np.float32)] * 6)


def cylinder(r0, r1, h, seg=12, center=(0, 0, 0), axis='y', color=(0.6, 0.6, 0.65)):
    """cone/cylinder/frustum along an axis, origin at base center."""
    cx, cy, cz = center
    v, f = [], []
    for i in range(seg):
        a = 2 * np.pi * i / seg
        ca, sa = np.cos(a), np.sin(a)
        for (rr, hh) in ((r0, 0.0), (r1, h)):
            if axis == 'y':
                v.append((cx + rr * ca, cy + hh, cz + rr * sa))
            elif axis == 'z':
                v.append((cx + rr * ca, cy + rr * sa, cz + hh))
            else:
                v.append((cx + hh, cy + rr * ca, cz + rr * sa))
    for i in range(seg):
        a0, a1 = 2 * i, 2 * ((i + 1) % seg)
        f.append((a0, a0 + 1, a1 + 1, a1))
    return Mesh(v, f, [np.asarray(color, np.float32)] * len(f))


def sphere_mesh(r, seg=10, rings=6, center=(0, 0, 0), color=(0.6, 0.6, 0.65)):
    verts, faces = [], []
    for j in range(1, rings):
        th = np.pi * j / rings
        for i in range(seg):
            ph = 2 * np.pi * i / seg
            verts.append((center[0] + r * np.sin(th) * np.cos(ph),
                          center[1] + r * np.cos(th),
                          center[2] + r * np.sin(th) * np.sin(ph)))
    top = len(verts); verts.append((center[0], center[1] + r, center[2]))
    bot = len(verts); verts.append((center[0], center[1] - r, center[2]))
    for j in range(rings - 2):
        for i in range(seg):
            a = j * seg + i; b = j * seg + (i + 1) % seg
            c = (j + 1) * seg + (i + 1) % seg; d = (j + 1) * seg + i
            faces.append((a, b, c, d))
    for i in range(seg):
        faces.append((top, (i + 1) % seg, i))
        faces.append((bot, (rings - 2) * seg + i, (rings - 2) * seg + (i + 1) % seg))
    return Mesh(verts, faces, [np.asarray(color, np.float32)] * len(faces))


def torus(R, r, seg=16, sides=8, center=(0, 0, 0), axis='z', color=(0.6, 0.6, 0.65)):
    verts, faces = [], []
    for i in range(seg):
        a = 2 * np.pi * i / seg
        for j in range(sides):
            b = 2 * np.pi * j / sides
            x = (R + r * np.cos(b)) * np.cos(a)
            y = (R + r * np.cos(b)) * np.sin(a)
            z = r * np.sin(b)
            if axis == 'z':
                verts.append((center[0] + x, center[1] + y, center[2] + z))
            elif axis == 'y':
                verts.append((center[0] + x, center[1] + z, center[2] + y))
            else:
                verts.append((center[0] + z, center[1] + x, center[2] + y))
    for i in range(seg):
        for j in range(sides):
            a = i * sides + j
            b = i * sides + (j + 1) % sides
            c = ((i + 1) % seg) * sides + (j + 1) % sides
            d = ((i + 1) % seg) * sides + j
            faces.append((a, b, c, d))
    return Mesh(verts, faces, [np.asarray(color, np.float32)] * len(faces))


def merge(*meshes):
    verts, faces, cols, grp = [], [], [], []
    off = 0
    for m in meshes:
        verts.extend(m.v.tolist())
        for fc, c, g in zip(m.f, m.colors, m.groups):
            faces.append([i + off for i in fc])
            cols.append(c); grp.append(g)
        off += len(m.v)
    return Mesh(verts, faces, cols, grp)


def rotate_mesh(m, angle, axis='y'):
    c, s = np.cos(angle), np.sin(angle)
    if axis == 'y':
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float32)
    elif axis == 'z':
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)
    else:
        R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)
    return Mesh(m.v @ R.T, m.f, m.colors, m.groups)


def render_mesh(mesh, w, h, cam, lights, *, ambient=(0.10, 0.11, 0.16), gloss=30.0,
                spec_strength=0.8, rim=0.0, rim_col=(0.5, 0.6, 1.0), alpha_floor=0.0):
    """Z-buffer rasterizer, per-pixel Phong via barycentric interpolation."""
    v = mesh.v
    # camera space
    rel = v - cam.eye
    cz = rel @ cam.fwd
    cx = rel @ cam.right
    cy = rel @ cam.up
    if cam.ortho is None:
        t = np.tan(np.radians(cam.fov) * 0.5)
        sx = (cx / (cz * t * cam.aspect)) * 0.5 + 0.5
        sy = 0.5 - (cy / (cz * t)) * 0.5
    else:
        sx = cx / (cam.ortho * cam.aspect) * 0.5 + 0.5
        sy = 0.5 - cy / cam.ortho * 0.5
    px = sx * w
    py = sy * h

    zbuf = np.full((h, w), 1e9, np.float32)
    cbuf = np.zeros((h, w, 3), np.float32)
    abuf = np.zeros((h, w), np.float32)
    nbuf = np.zeros((h, w, 3), np.float32)
    vbuf = np.zeros((h, w, 3), np.float32)

    for fi, face in enumerate(mesh.f):
        n = len(face)
        tris = [(face[0], face[k], face[k + 1]) for k in range(1, n - 1)]
        for tri in tris:
            idx = np.array(tri)
            if np.any(cz[idx] < 0.02):
                continue
            x = px[idx]; y = py[idx]; z = cz[idx]
            area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
            if abs(area) < 1e-9:
                continue
            x0 = max(int(np.floor(x.min())), 0); x1 = min(int(np.ceil(x.max())) + 1, w)
            y0 = max(int(np.floor(y.min())), 0); y1 = min(int(np.ceil(y.max())) + 1, h)
            if x0 >= x1 or y0 >= y1:
                continue
            xs = np.arange(x0, x1) + 0.5
            ys = np.arange(y0, y1) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
            w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            iz = w0 / z[0] + w1 / z[1] + w2 / z[2]
            zz = np.where(iz > 1e-9, 1.0 / np.maximum(iz, 1e-9), 1e9)
            sub = zbuf[y0:y1, x0:x1]
            upd = inside & (zz < sub)
            if not upd.any():
                continue
            sub[upd] = zz[upd]
            # perspective-correct barycentrics
            b0 = (w0 / z[0]) / np.maximum(iz, 1e-9)
            b1 = (w1 / z[1]) / np.maximum(iz, 1e-9)
            b2 = (w2 / z[2]) / np.maximum(iz, 1e-9)
            wp = b0[..., None] * v[idx[0]] + b1[..., None] * v[idx[1]] + b2[..., None] * v[idx[2]]
            e1 = v[idx[1]] - v[idx[0]]; e2 = v[idx[2]] - v[idx[0]]
            fn = normalize(np.cross(e1, e2))
            if np.dot(fn, wp[upd][0] - cam.eye) > 0:
                fn = -fn
            view = normalize(cam.eye - wp)
            col = blinn_phong(np.broadcast_to(fn, view.shape).copy(), view, view,
                              mesh.colors[fi], lights, ambient=ambient, gloss=gloss,
                              spec_strength=spec_strength, rim=rim, rim_col=rim_col)
            cbuf[y0:y1, x0:x1][upd] = col[upd]
            abuf[y0:y1, x0:x1][upd] = 1.0
            nbuf[y0:y1, x0:x1][upd] = fn
            vbuf[y0:y1, x0:x1][upd] = view[upd]

    # edge antialias: soften alpha at silhouette (cheap 3x3 coverage)
    a = abuf
    cov = (a
           + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)
           + np.roll(np.roll(a, 1, 0), 1, 1) + np.roll(np.roll(a, 1, 0), -1, 1)
           + np.roll(np.roll(a, -1, 0), 1, 1) + np.roll(np.roll(a, -1, 0), -1, 1)) / 9.0
    rgba = np.zeros((h, w, 4), np.float32)
    # fill uncovered neighbours with nearest colour so downsampling doesn't bleed black
    c_filled = cbuf.copy()
    for _ in range(2):
        for sh in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(c_filled, sh, axis=(0, 1))
            srcm = np.roll(abuf, sh, axis=(0, 1)) > 0
            fill = (abuf == 0) & srcm
            c_filled[fill] = src[fill]
    rgba[..., :3] = c_filled
    rgba[..., 3] = np.clip(cov * 1.6, 0, 1)
    return rgba, (abuf, nbuf, vbuf)


# --------------------------------------------------------------------------
# backgrounds: volumetric nebula + starfield + planet
# --------------------------------------------------------------------------

def render_space_bg(w, h, cam, noise, *, palette=(0.05, 0.06, 0.14),
                    nebula_col=(0.35, 0.18, 0.55), nebula_col2=(0.10, 0.30, 0.55),
                    density=0.75, scale=1.6, steps=14, near=0.6, far=26.0,
                    stars=900, star_seed=1, glow=0.0, grad=(0.0, 0.0, 0.0),
                    planets=None, clouds_hi=0.0):
    """Ray-march a soft nebula volume and add procedural stars."""
    o, d = cam.rays(w, h)
    acc = np.zeros((h, w, 3), np.float32)
    base = np.asarray(palette, np.float32)
    # vertical gradient
    g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    acc += base[None, None, :] * (1 - g) + np.asarray(grad, np.float32)[None, None, :] * g
    trans = np.ones((h, w), np.float32)
    ts = np.linspace(near, far, steps, dtype=np.float32)
    for t in ts:
        p = o + d * t[()] if False else (o + d * t)
        q = p * scale
        dens = noise.fbm(q, octaves=4)
        dens = np.clip((dens - 0.52) * 2.6, 0, 1) * density
        if clouds_hi > 0:
            dens = np.clip(dens + clouds_hi * np.clip((noise.fbm(q * 3.1 + 11.0, octaves=3) - 0.5) * 4, 0, 1), 0, 1.4)
        c1 = noise.fbm(q * 0.6 + 3.0, octaves=3)
        col = (np.asarray(nebula_col, np.float32)[None, None, :] * c1[..., None]
               + np.asarray(nebula_col2, np.float32)[None, None, :] * (1 - c1)[..., None])
        a = np.clip(dens * 0.16, 0, 1)
        acc += trans[..., None] * col * a[..., None]
        trans = trans * (1 - a)
    # stars
    rng = np.random.default_rng(star_seed)
    for _ in range(stars):
        # random direction on the view frustum
        u = rng.random() * 2 - 1
        vv = rng.random() * 2 - 1
        if u * u + vv * vv > 1:
            continue
        if cam.ortho is None:
            t = np.tan(np.radians(cam.fov) * 0.5)
            dd = normalize(cam.fwd + cam.right * (u * t * cam.aspect) + cam.up * (vv * t))
        else:
            dd = cam.fwd
            o = cam.eye + cam.right * (u * cam.ortho * cam.aspect) + cam.up * (vv * cam.ortho)
        # project star direction into pixel space
        rel = dd
        cz = rel @ cam.fwd; cx = rel @ cam.right; cy = rel @ cam.up
        if cam.ortho is None:
            if cz <= 1e-4:
                continue
            t = np.tan(np.radians(cam.fov) * 0.5)
            sxp = (cx / (cz * t * cam.aspect)) * 0.5 + 0.5
            syp = 0.5 - (cy / (cz * t)) * 0.5
        else:
            sxp = cx / (cam.ortho * cam.aspect) * 0.5 + 0.5
            syp = 0.5 - cy / cam.ortho * 0.5
        px = int(sxp * w); py = int(syp * h)
        if not (0 <= px < w and 0 <= py < h):
            continue
        mag = rng.random() ** 3
        col = np.array([0.8 + 0.2 * rng.random(), 0.85, 1.0], np.float32) * (0.35 + mag * 1.5)
        rad = 0.0 if mag < 0.75 else 1.0
        yy, xx = np.mgrid[-2:3, -2:3]
        gk = np.exp(-(xx * xx + yy * yy) / (0.6 + rad))
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                y2, x2 = py + dy, px + dx
                if 0 <= y2 < h and 0 <= x2 < w:
                    acc[y2, x2] += col * gk[dy + 2, dx + 2] * 0.8
    if planets:
        for pl in planets:
            _draw_planet_sprite(acc, w, h, cam, pl, noise)
    return acc, np.ones((h, w), np.float32)


def _draw_planet_sprite(acc, w, h, cam, pl, noise):
    """Composite a simple lit sphere (with optional ring) into a bg image."""
    cx, cy, r = pl["x"], pl["y"], pl["r"]
    y0 = max(int(cy - r * 2.2), 0); y1 = min(int(cy + r * 2.2) + 1, h)
    x0 = max(int(cx - r * 2.2), 0); x1 = min(int(cx + r * 2.2) + 1, w)
    if x0 >= x1 or y0 >= y1:
        return
    W, H = x1 - x0, y1 - y0
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx = (xx - cx) / r; dy = (yy - cy) / r
    rr = np.sqrt(dx * dx + dy * dy)
    ins = rr <= 1.0
    dz = np.sqrt(np.maximum(1.0 - rr * rr, 0))
    n = np.stack([dx, -dy, dz], -1)          # fake sphere normal (screen space)
    n = normalize(n)
    tex_u = np.arctan2(dx, dz); tex_v = dy
    seed = np.asarray(pl.get("seed", (0, 0, 0)), np.float32)
    q = np.stack([tex_u * 1.1, tex_v * 1.1, np.zeros_like(tex_u)], -1) * pl.get("tfreq", 3.0) + seed
    cont = noise.fbm(q, octaves=4)
    land = smoothstep(np.clip((cont - 0.44) * 5.0 + 0.5, 0, 1))
    sea = np.asarray(pl.get("sea", (0.03, 0.09, 0.26)), np.float32)
    lnd = np.asarray(pl.get("land", (0.36, 0.30, 0.14)), np.float32)
    alb = sea[None, None, :] * (1 - land)[..., None] + lnd[None, None, :] * land[..., None]
    band = pl.get("band", None)
    if band is not None:
        stripes = 0.5 + 0.5 * np.sin(tex_v * pl.get("bandfreq", 14.0) + noise.fbm(q * 0.7, octaves=3) * 4)
        base = alb
        banded = base * (0.55 + 0.9 * stripes)[..., None] * np.asarray(pl.get("bandcol", (1, 1, 1)), np.float32)[None, None, :]
        mix = float(band)
        alb = base * (1 - mix) + banded * mix
    L = normalize(np.asarray(pl.get("light", (-0.6, 0.6, 0.55)), np.float32))
    ndl = np.maximum(np.sum(n * L, -1), 0)
    col = alb * ndl[..., None] * np.asarray(pl.get("lcol", (1.0, 0.96, 0.9)), np.float32)[None, None, :]
    col += alb * 0.06
    # rim / atmosphere
    atm = pl.get("atmo", 0.0)
    if atm > 0:
        ndv = np.maximum(n[..., 2], 0)
        col += atm * ((1 - ndv) ** 2.5)[..., None] * np.asarray(pl.get("atmocol", (0.3, 0.6, 1.0)), np.float32)[None, None, :]
    ring = pl.get("ring", 0.0)
    if ring > 0:
        ry = (yy - cy) / (r * 0.26)
        rx = (xx - cx) / (r * 1.85)
        rd = np.sqrt(rx * rx + ry * ry)
        rm = (rd > 0.83) & (rd < 1.0) & (yy > cy)
        col = np.where((rm & ~ins)[..., None], np.asarray(pl.get("ringcol", (0.5, 0.45, 0.4)), np.float32)[None, None, :] * 1.2, col)
        rm2 = (rd > 0.78) & (rd < 1.06) & (yy <= cy)
        col = np.where((rm2 & ~ins)[..., None], np.asarray(pl.get("ringcol", (0.5, 0.45, 0.4)), np.float32)[None, None, :] * 0.85, col)
    m = (ins | (yy > cy) & (np.sqrt(((xx - cx) / (r * 1.85)) ** 2 + ((yy - cy) / (r * 0.26)) ** 2) > 0.83) &
         (np.sqrt(((xx - cx) / (r * 1.85)) ** 2 + ((yy - cy) / (r * 0.26)) ** 2) < 1.0) | (yy <= cy) &
         (np.sqrt(((xx - cx) / (r * 1.85)) ** 2 + ((yy - cy) / (r * 0.26)) ** 2) > 0.78) &
         (np.sqrt(((xx - cx) / (r * 1.85)) ** 2 + ((yy - cy) / (r * 0.26)) ** 2) < 1.06)) if ring > 0 else ins
    acc[y0:y1, x0:x1] = np.where(m[..., None], col, acc[y0:y1, x0:x1])


# --------------------------------------------------------------------------
# post processing
# --------------------------------------------------------------------------

def downsample(img, factor):
    h, w = img.shape[:2]
    h2, w2 = h // factor, w // factor
    img = img[:h2 * factor, :w2 * factor].reshape(h2, factor, w2, factor, -1)
    if img.shape[-1] == 4:
        a = img[..., 3:4]
        wsum = np.maximum(a.sum(axis=(1, 3)), 1e-6)
        rgb = (img[..., :3] * a).sum(axis=(1, 3)) / wsum
        alpha = img[..., 3].mean(axis=(1, 3))
        return np.concatenate([rgb, alpha[..., None]], -1)
    return img.mean(axis=(1, 3))


def bloom(img, threshold=0.78, radius=3, strength=0.55):
    lum = img[..., :3].mean(-1)
    m = np.clip((lum - threshold) / max(1e-6, 1 - threshold), 0, 1)
    add = img[..., :3] * m[..., None]
    for _ in range(radius):
        add = (add + np.roll(add, 1, 0) + np.roll(add, -1, 0) +
               np.roll(add, 1, 1) + np.roll(add, -1, 1)) / 5.0
    out = img.copy()
    out[..., :3] = img[..., :3] + add * strength * 1.6
    return out
