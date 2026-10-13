#!/usr/bin/env python3
"""Encode PSG frames into the cartridge music stream and pack the music banks.

Stream format (one song = sequence of commands):
  1cc1vvvv            volume latch for channel cc  (written as-is)
  1cc0llll 00hhhhhh   tone latch + data, channels 0-2
  111001rr / 1110xxxx noise control
  0x00..0x3F          end of frame, then idle N more frames
  0x40                end of song: jump to the loop point
  0x41 b lo hi n      play the n frames (end-of-frame bytes) stored at bank b /
                      address hi:lo, then resume here (never nested)
"""

BANK = 16384


def frame_cmds(f, prev):
    out = []
    for c in range(3):
        n = f['tone'][c]
        if prev is None or prev['tone'][c] != n:
            out += [0x80 | (c << 5) | (n & 15), (n >> 4) & 63]
    if prev is None or prev['noise'] != f['noise']:
        out.append(f['noise'])
    for c in range(4):
        if prev is None or prev['att'][c] != f['att'][c]:
            out.append(0x90 | (c << 5) | f['att'][c])
    return out


def tokens_of(frames, loop):
    """Frames -> list of (bytes, frame_index) tokens; idle frames fold into waits."""
    toks = []
    prev = None
    for k, f in enumerate(frames):
        force = k == 0 or k == loop
        cmds = frame_cmds(f, None if force else prev)
        prev = f
        if not cmds and toks and toks[-1][0][-1] < 0x3F and not force:
            b = toks[-1][0]
            toks[-1] = (b[:-1] + bytes([b[-1] + 1]), toks[-1][1])
            continue
        toks.append((bytes(cmds + [0]), k))
    return toks


def lz(toks, barrier):
    """Greedy whole-token substring compression. Returns list of items:
       ('raw', bytes) or ('ref', rel_offset, length)."""
    items = []
    raw_off = {}          # token index -> byte offset (only raw tokens)
    out_len = 0
    index = {}            # (tok_i, tok_i+1) -> [token positions]
    i = 0
    n = len(toks)
    tb = [t[0] for t in toks]
    while i < n:
        best_len, best_j, best_bytes = 0, None, 0
        limit = n if i >= barrier else barrier
        if i + 1 < limit:
            key = (tb[i], tb[i + 1])
            for j in index.get(key, ()):
                L = 0; nbytes = 0
                while (i + L < limit and j + L < i and j + L in raw_off and tb[j + L] == tb[i + L]
                       and L < 255
                       and (L == 0 or raw_off[j + L] == raw_off[j + L - 1] + len(tb[j + L - 1]))):
                    nbytes += len(tb[i + L]); L += 1
                if nbytes > best_bytes:
                    best_len, best_j, best_bytes = L, j, nbytes
        if best_bytes >= 8:
            items.append(('ref', raw_off[best_j], best_len, i))
            out_len += 5
            i += best_len
        else:
            raw_off[i] = out_len
            items.append(('raw', tb[i], i))
            out_len += len(tb[i])
            if i >= 1 and (i - 1) in raw_off:
                index.setdefault((tb[i - 1], tb[i]), []).append(i - 1)
            i += 1
    return items


def assemble(items, base, loop_tok):
    """Lay out a song at absolute ROM offset `base`. Returns bytes, loop offset."""
    out = bytearray()
    loop_off = None
    def absaddr(off):
        a = base + off
        return a // BANK, 0x8000 + a % BANK
    for it in items:
        if it[-1] == loop_tok and loop_off is None:
            loop_off = len(out)
        if it[0] == 'raw':
            out += it[1]
        else:
            bank, addr = absaddr(it[1])
            out += bytes([0x41, bank, addr & 255, addr >> 8, it[2]])
    out.append(0x40)
    assert loop_off is not None
    return bytes(out), loop_off


def encode_song(frames, loop):
    toks = tokens_of(frames, loop)
    loop_tok = next(i for i, t in enumerate(toks) if t[1] == loop)
    items = lz(toks, loop_tok)
    return items, loop_tok, sum(len(t[0]) for t in toks)


def decode_check(blob, start_abs, loop_abs, music_base, nframes_expected, frames, loop):
    """Run the stream exactly as the Z80 player does and compare register state."""
    rom = {}
    def rd_at(bank, addr):
        return blob[bank * BANK + (addr - 0x8000) - music_base]
    bank, ptr = start_abs // BANK, 0x8000 + start_abs % BANK
    sub = 0; left = 0; rb = rp = 0
    state = dict(tone=[0, 0, 0], att=[15] * 4, noise=0)
    lo = [0, 0, 0]
    wait = 0
    out = []
    def rd():
        nonlocal bank, ptr
        b = rd_at(bank, ptr); ptr += 1
        if ptr == 0xC000: ptr = 0x8000; bank += 1
        return b
    total = len(frames) + (len(frames) - loop)       # play through the loop once
    while len(out) < total:
        if wait:
            wait -= 1
        else:
            while True:
                b = rd()
                if b & 0x80:
                    ch = (b >> 5) & 3
                    if b & 0x10: state['att'][ch] = b & 15
                    elif ch == 3: state['noise'] = b
                    else:
                        d = rd(); state['tone'][ch] = (b & 15) | (d << 4)
                elif b < 0x40:
                    wait = b
                    if left:
                        left -= 1
                        if not left: bank, ptr = rb, rp
                    break
                elif b == 0x40:
                    bank, ptr = loop_abs // BANK, 0x8000 + loop_abs % BANK
                else:
                    nb = rd(); l = rd(); h = rd(); n = rd()
                    assert left == 0 and n > 0
                    rb, rp = bank, ptr
                    bank, ptr = nb, l | (h << 8); left = n
        out.append(dict(tone=list(state['tone']), att=list(state['att']), noise=state['noise']))
    exp = frames + frames[loop:]
    for k in range(total):
        a, e = out[k], exp[k]
        if a['tone'] != e['tone'] or a['att'] != e['att'] or (a['att'][3] < 15 and a['noise'] != e['noise']):
            raise AssertionError(f'decode mismatch at frame {k}: {a} vs {e}')
    return True
