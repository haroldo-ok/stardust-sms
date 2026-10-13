"""Load libxmp dumps (info.txt, ticks.txt, sNN.raw) and analyse samples."""
import numpy as np, re
from pathlib import Path

PAL_CLOCK = 3546895.0

class Sample:
    pass

def load_dump(d):
    d = Path(d)
    info = d.joinpath('info.txt').read_text().splitlines()
    samples = {}
    ins_map = {}
    for line in info:
        m = re.match(r'sample (\d+) len (\d+) lps (\d+) lpe (\d+) flg (\d+)', line)
        if m:
            i, ln, lps, lpe, flg = map(int, m.groups())
            s = Sample(); s.idx = i; s.len = ln; s.lps = lps; s.lpe = lpe; s.loop = bool(flg & 2)
            raw = d.joinpath(f's{i:02d}.raw').read_bytes()
            s.data = np.frombuffer(raw, dtype=np.int8).astype(np.float64) / 128.0
            samples[i] = s
        m = re.match(r'ins (\d+) nsm (\d+) vol (\d+) sid (\d+)', line)
        if m:
            ins_map[int(m.group(1))] = int(m.group(4))
    ticks = []
    end = None
    for line in d.joinpath('ticks.txt').read_text().splitlines():
        if line.startswith('END'):
            p = line.split(); end = (int(p[2]), int(p[3])); continue
        parts = line.split('|')
        h = parts[0].split()
        t = dict(time=int(h[1]), pos=int(h[2]), pat=int(h[3]), row=int(h[4]), frame=int(h[5]), speed=int(h[6]), bpm=int(h[7]), gvol=int(h[8]), ch=[])
        for c in parts[1:]:
            v = list(map(int, c.split()))
            t['ch'].append(dict(period=v[0] / 4096.0, position=v[1], note=v[2], ins=v[3], smp=v[4], vol=v[5],
                                ev_note=v[6], ev_ins=v[7], ev_vol=v[8], fxt=v[9], fxp=v[10]))
        ticks.append(t)
    return samples, ins_map, ticks, end

def yin(x, tmin=2, tmax=None, thresh=0.15):
    """Return (period_in_samples, aperiodicity)."""
    n = len(x)
    if tmax is None: tmax = n // 2
    tmax = min(tmax, n // 2)
    if tmax <= tmin + 2: return None, 1.0
    W = n - tmax
    d = np.zeros(tmax + 1)
    x0 = x[:W]
    for tau in range(1, tmax + 1):
        diff = x0 - x[tau:tau + W]
        d[tau] = np.dot(diff, diff)
    cm = np.ones_like(d)
    cs = np.cumsum(d[1:])
    cm[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(cs, 1e-12)
    tau = None
    for t in range(tmin, tmax):
        if cm[t] < thresh:
            while t + 1 < tmax and cm[t + 1] < cm[t]: t += 1
            tau = t; break
    if tau is None:
        tau = int(np.argmin(cm[tmin:tmax])) + tmin
    ap = cm[tau]
    # parabolic interpolation
    if 1 <= tau < tmax:
        a, b, c = cm[tau - 1], cm[tau], cm[tau + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-12:
            tau = tau + 0.5 * (a - c) / den
    return float(tau), float(ap)

def analyse_sample(s):
    """Fill pitch (cycles/sample), aperiodicity, centroid (fraction of fs), rms envelope."""
    x = s.data
    s.env_step = 32
    if len(x) == 0:
        s.f0 = None; s.aper = 1; s.centroid = 0; s.env = np.zeros(1); s.peak = 0; return s
    # RMS envelope
    nwin = (len(x) + s.env_step - 1) // s.env_step
    env = np.zeros(nwin)
    for i in range(nwin):
        seg = x[max(0, i * s.env_step - 32): i * s.env_step + 64]
        env[i] = np.sqrt(np.mean(seg * seg)) if len(seg) else 0
    s.env = env
    s.peak = float(env.max())
    # analysis window: looped region if a meaningful loop, otherwise the
    # loudest stable region after the attack
    if s.loop and s.lpe - s.lps >= 16:
        seg = x[s.lps:s.lpe]
        reps = max(1, 2048 // len(seg) + 2)
        seg = np.tile(seg, reps)[:4096]
    else:
        st = min(len(x) // 8, 400)
        seg = x[st: st + 2048]
        if len(seg) < 256: seg = x[:2048]
    seg = seg - seg.mean()
    if len(seg) >= 32 and np.abs(seg).max() > 1e-3:
        tau, ap = yin(seg, tmin=3, tmax=min(800, len(seg) // 2))
    else:
        tau, ap = None, 1.0
    s.f0 = (1.0 / tau) if tau else None
    s.aper = ap
    # spectral centroid of the first 1024 samples (fraction of sample rate)
    a = x[:1024] - x[:1024].mean()
    if len(a) >= 32:
        sp = np.abs(np.fft.rfft(a * np.hanning(len(a))))
        fr = np.fft.rfftfreq(len(a))
        s.centroid = float((sp * fr).sum() / max(sp.sum(), 1e-12))
    else:
        s.centroid = 0
    # high-frequency energy ratio (noise-iness)
    return s
