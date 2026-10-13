#!/usr/bin/env python3
"""Convert a 4-channel Amiga module (libxmp tick dump) into SN76489 PSG frames.

Each 50 Hz tick of the module becomes one PSG frame:
  tone[0..2]  10-bit dividers, att[0..3] 4-bit attenuations, noise control.

Approach
  * every sample is analysed once: pitch (YIN on the loop or sustain), whether
    it is tonal or percussive, its spectral centroid and an RMS envelope;
  * per tick, every Amiga channel becomes a voice whose loudness is
    channel volume x the sample's RMS at the current play position (so plucks
    and drums decay naturally) and whose frequency is
    sample_f0 x Paula_clock / period (so arpeggios, vibrato, slides survive);
  * tonal voices compete for the three square channels (sticky allocation,
    quietest dropped); percussive voices go to the noise channel;
  * per-instrument octave transposition keeps bass lines inside the PSG range
    (lowest note ~109 Hz) without breaking melodic contour.
"""
import sys, math, json
import numpy as np
from modload import load_dump, analyse_sample, yin, PAL_CLOCK

SMS_CLOCK = 3579545.0
FMIN = SMS_CLOCK / 32 / 1023          # ~109.3 Hz


def pitch_track(s):
    x = s.data; out = []
    step = max(256, len(x) // 6)
    for off in range(0, max(1, len(x) - 256), step):
        seg = x[off:off + 768]; seg = seg - seg.mean()
        if len(seg) < 200 or np.sqrt(np.mean(seg ** 2)) < 0.02:
            continue
        tau, ap = yin(seg, tmin=3, tmax=min(380, len(seg) // 2))
        out.append((1.0 / tau, ap))
    return out


def classify(s, override=None):
    """Return ('tone', f0_cycles_per_sample) or ('drum', None)."""
    if override:
        kind = override.get('kind')
        if kind == 'drum':
            return 'drum', None
        if kind == 'tone' and 'f0' in override:
            return 'tone', override['f0']
    if s.f0 is None or s.len < 8:
        return 'drum', None
    if s.loop and s.lpe - s.lps >= 16 and s.aper < 0.2:
        return 'tone', s.f0
    tr = pitch_track(s)
    good = [f for f, ap in tr if ap < 0.25]
    if len(tr) >= 2 and len(good) >= max(2, 0.6 * len(tr)):
        med = float(np.median(good))
        close = [f for f in good if abs(f / med - 1) < 0.04]
        if len(close) >= 0.6 * len(tr):
            return 'tone', med
    if override and override.get('kind') == 'tone':
        return 'tone', s.f0
    return 'drum', None


def noise_rate(centroid_hz):
    if centroid_hz >= 3000: return 0      # hi-hat / cymbal
    if centroid_hz >= 1000: return 1      # snare
    return 2                               # kick / tom


def convert(dump_dir, opts=None):
    opts = opts or {}
    samples, ins_map, ticks, end = load_dump(dump_dir)
    for s in samples.values():
        analyse_sample(s)
    overrides = opts.get('samples', {})
    nch = len(ticks[0]['ch'])

    # usage statistics per sample (median playback rate, frequencies)
    used = {}
    for t in ticks:
        for c in t['ch']:
            if c['vol'] > 0 and c['smp'] < 255 and c['period'] > 0 and c['smp'] in samples:
                used.setdefault(c['smp'], []).append(c['period'])
    info = {}
    for i, pers in used.items():
        s = samples[i]
        kind, f0 = classify(s, overrides.get(str(i)))
        rate = PAL_CLOCK / np.median(pers)
        d = dict(kind=kind, f0=f0, centroid=s.centroid * rate)
        if kind == 'tone':
            freqs = f0 * PAL_CLOCK / np.array(pers)
            lo = np.percentile(freqs, 5)
            shift = 0
            while lo * (2 ** shift) < FMIN * 1.0:
                shift += 1
            d['oct'] = overrides.get(str(i), {}).get('oct', shift)
        else:
            d['rate'] = overrides.get(str(i), {}).get('rate', noise_rate(d['centroid']))
        d['gain'] = overrides.get(str(i), {}).get('gain', 1.0)
        info[i] = d

    def loud(c):
        s = samples.get(c['smp'])
        if s is None or c['vol'] <= 0 or c['period'] <= 0 or len(s.env) == 0:
            return 0.0
        p = c['position']
        if p >= s.len:
            if not s.loop: return 0.0
            p = s.lps
        e = s.env[min(len(s.env) - 1, p // s.env_step)]
        return (c['vol'] / 64.0) * e * info[c['smp']]['gain'] * (t_gvol / 64.0)

    # pass 1: voices per tick
    voices = []
    prev_smp = [None] * nch
    for t in ticks:
        t_gvol = t['gvol']
        vs = []
        for ch, c in enumerate(t['ch']):
            if c['smp'] not in info:
                prev_smp[ch] = None; continue
            L = loud(c)
            trig = (c['ev_note'] > 0 and t['frame'] == 0 and c['fxt'] not in (3, 5)) or prev_smp[ch] != c['smp']
            prev_smp[ch] = c['smp'] if L > 0 else None
            if L <= 0: continue
            d = info[c['smp']]
            if d['kind'] == 'tone':
                f = d['f0'] * PAL_CLOCK / c['period'] * (2 ** d['oct'])
                while f < FMIN: f *= 2
                while f > 8000: f /= 2
                vs.append(dict(ch=ch, kind='tone', f=f, L=L, trig=trig))
            else:
                vs.append(dict(ch=ch, kind='drum', rate=d['rate'], L=L, trig=trig))
        voices.append(vs)

    # loudness reference
    tl = [v['L'] for vs in voices for v in vs if v['kind'] == 'tone']
    dl = [v['L'] for vs in voices for v in vs if v['kind'] == 'drum']
    ref_t = np.percentile(tl, 97) if tl else 1
    ref_d = np.percentile(dl, 97) if dl else 1
    base_t = opts.get('base', 1)
    base_d = opts.get('noise_base', 3)

    def att_of(L, ref, base):
        if L <= 1e-6: return 15
        a = base + round(-20 * math.log10(L / ref) / 2)
        return int(min(15, max(0, a)))

    # pass 2: allocation
    frames = []
    assign = {}            # amiga ch -> psg ch
    last_psg = {}          # amiga ch -> last psg ch used
    tone = [0x3ff, 0x3ff, 0x3ff]
    noise = 0xE4 | 2
    dips = []
    kick_age = {}
    for k, vs in enumerate(voices):
        att = [15, 15, 15, 15]
        tv = [v for v in vs if v['kind'] == 'tone']
        for v in tv:
            v['a'] = att_of(v['L'], ref_t, base_t)
        tv = [v for v in tv if v['a'] < 15]
        tv.sort(key=lambda v: -(v['L'] * (1.5 if v['ch'] in assign else 1.0)))
        keep = tv[:3]
        keepch = {v['ch'] for v in keep}
        for ch in list(assign):
            if ch not in keepch: del assign[ch]
        used_psg = set(assign.values())
        for v in keep:
            if v['ch'] not in assign:
                pref = [last_psg.get(v['ch'])] + [0, 1, 2]
                for p in pref:
                    if p is not None and p not in used_psg:
                        assign[v['ch']] = p; used_psg.add(p); break
        for v in keep:
            p = assign[v['ch']]
            last_psg[v['ch']] = p
            n = int(round(SMS_CLOCK / (32 * v['f'])))
            n = max(1, min(1023, n))
            if v['trig'] and k > 0 and frames[k - 1]['att'][p] < 15 and frames[k - 1]['tone'][p] == n:
                dips.append((k - 1, p))
            tone[p] = n
            att[p] = v['a']
        dv = [v for v in vs if v['kind'] == 'drum']
        for v in dv:
            if v['trig']: kick_age[v['ch']] = 0
            v['a'] = att_of(v['L'], ref_d, base_d)
        dv = [v for v in dv if v['a'] < 15]
        # kicks/toms: a free square channel plays a fast falling pitch sweep
        if opts.get('tone_kicks', True):
            kicks = sorted([v for v in dv if v['rate'] == 2], key=lambda v: -v['L'])
            free = [p for p in (2, 1, 0) if p not in used_psg]
            for v in kicks[:len(free)]:
                p = free.pop(0); used_psg.add(p)
                age = kick_age.get(v['ch'], 8)
                f = max(FMIN * 1.01, opts.get('kick_hz', 280) * (0.70 ** age))
                tone[p] = max(1, min(1023, int(round(SMS_CLOCK / (32 * f)))))
                att[p] = max(0, v['a'] - 1)
                dv.remove(v)
        if dv:
            v = max(dv, key=lambda v: v['L'] * (1.3 if v['trig'] else 1.0))
            noise = 0xE4 | v['rate']
            att[3] = v['a']
        for ch in kick_age: kick_age[ch] += 1
        frames.append(dict(tone=list(tone), att=att, noise=noise))
    for k, p in dips:
        frames[k]['att'][p] = min(15, frames[k]['att'][p] + 4)

    # loop point
    loop = 0
    if end is not None:
        for k, t in enumerate(ticks):
            if t['pos'] == end[0] and t['row'] == end[1] and t['frame'] == 0:
                loop = k; break
    return frames, loop, info


def legacy_frames():
    """The project's original title/menu tune, rendered at 50 Hz."""
    notes = [855, 762, 679, 640, 571, 508, 453, 428, 381, 339, 320, 285, 254, 226, 214, 190]
    melody = [7, 9, 11, 9, 7, 4, 6, 7, 9, 11, 12, 11, 9, 7, 6, 4,
              7, 9, 11, 14, 12, 11, 9, 7, 6, 4, 2, 4, 6, 7, 9, 6,
              11, 12, 14, 12, 11, 9, 7, 9, 12, 11, 9, 7, 6, 4, 6, 7,
              9, 11, 9, 7, 6, 4, 2, 4, 7, 9, 11, 9, 7, 6, 4, 6]
    bass = [0, 0, 0, 0, 3, 3, 3, 3, 5, 5, 5, 5, 2, 2, 2, 2]
    frames = []
    for step in range(64):
        dur = 7 if step % 3 != 2 else 6       # 4 logic frames @30 Hz ~ 6.67 ticks
        for j in range(dur):
            frames.append(dict(tone=[notes[melody[step]], notes[bass[(step >> 2) & 15]], 0x3ff],
                               att=[8, 10, 15, 15], noise=0xE6))
    return frames, 0


def render(frames, path, sr=44100, fps=50):
    """Simple SN76489 model for previews and comparisons."""
    spf = sr // fps
    out = np.zeros(len(frames) * spf)
    vol = np.array([10 ** (-2 * a / 20) for a in range(15)] + [0.0])
    phase = [0.0, 0.0, 0.0]
    lfsr = 0x8000; ncount = 0.0
    tt = np.arange(spf)
    for k, f in enumerate(frames):
        seg = np.zeros(spf)
        for c in range(3):
            fr = SMS_CLOCK / (32 * max(1, f['tone'][c]))
            if f['att'][c] < 15 and fr < sr / 2:
                ph = phase[c] + tt * fr / sr
                seg += vol[f['att'][c]] * np.where((ph % 1.0) < 0.5, 1.0, -1.0)
                phase[c] = (phase[c] + spf * fr / sr) % 1.0
        if f['att'][3] < 15:
            rate = f['noise'] & 3
            shift_hz = SMS_CLOCK / 16 / (16 << rate) if rate < 3 else SMS_CLOCK / (32 * max(1, f['tone'][2]))
            step = shift_hz / sr
            ns = np.zeros(spf)
            for i in range(spf):
                ncount += step
                while ncount >= 1:
                    ncount -= 1
                    bit = (lfsr ^ (lfsr >> 3)) & 1 if f['noise'] & 4 else lfsr & 1
                    lfsr = (lfsr >> 1) | (bit << 15)
                ns[i] = 1.0 if lfsr & 1 else -1.0
            seg += vol[f['att'][3]] * ns
        out[k * spf:(k + 1) * spf] = seg
    out = out / 4.0
    import wave
    w = wave.open(path, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(out, -1, 1) * 30000).astype(np.int16).tobytes()); w.close()
    return out


if __name__ == '__main__':
    frames, loop, info = convert(sys.argv[1])
    for i, d in sorted(info.items()):
        print(i, d)
    print('frames', len(frames), 'loop', loop)
