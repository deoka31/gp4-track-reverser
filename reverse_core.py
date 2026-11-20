#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reverse_core.py

Core of the GP4 track reverser: turns the circuit file of a Grand Prix 4 track around so that the track is driven
in the opposite direction. The command line front end is reverse_track.py; details are in docs/METHOD.md.

Needs gp4track.py (unchanged copy from the gp4-decomp project, next to this file).

Principle (everything is a mirror image of the ring):
  Main track (N points):   point j (new) <-> point (N-j) % N (old)
                           segment j (new) <-> segment N-1-j (old)
  Pit lane (linear, NP points): point i <-> NP-1-i, segment i <-> NP-2-i
  Heading + 0x80000000, gradient negated, heading change per segment negated, width left <-> right, bank angle
  negated, boundary lines and kerbs left <-> right, cameras mirrored (same distance to the switch point),
  racing line backwards (radii with the opposite sign, order reversed).
"""
import sys, os, json, copy, struct, math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gp4track as gt


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def d32(hi, lo):
    return s32(((hi & 0xFFFF) << 16) | (lo & 0xFFFF))


def hi16(v):
    return s16((v >> 16) & 0xFFFF)


def lo16(v):
    return s16(v & 0xFFFF)


# ---------------------------------------------------------------------------
# Split the command stream into groups (the commands in front of a section belong to it)

def split_groups(stream):
    groups, cur = [], []
    for it in stream:
        if 'sec' in it:
            groups.append({'cmds': cur, 'sec': it})
            cur = []
        else:
            cur.append(it)
    if cur:
        raise ValueError('commands after the last section')
    return groups


def cmds(g, name):
    return [c for c in g['cmds'] if c['cmd'] == name]


def mk(cmd, args, seg=0):
    it = {'cmd': cmd, 'seg': seg, 'args': [s16(a) for a in args]}
    note = gt.CMD_NOTE.get(int(cmd, 16))
    if note:
        it['note'] = note
    return it


SIDE_NEG, SIDE_POS = -32768, 16384


def swap_side(rec, to_neg):
    r = list(rec)
    r[0] = SIDE_NEG if to_neg else SIDE_POS
    return r


def swap_flags(fl):
    """Section flags: swap the bits 0x800 and 0x400 (one side / other side)."""
    a, b = fl & 0x800, fl & 0x400
    fl &= ~0xC00
    if a:
        fl |= 0x400
    if b:
        fl |= 0x800
    return s16(fl)


def swap_f7(v):
    return list(v[4:8]) + list(v[0:4])


# ---------------------------------------------------------------------------
# Split the track (ring or line) into fields and put it together again mirrored

def read_track(groups, ring):
    n = len(groups)
    T = {'N': n, 'ring': ring}
    T['F6'] = [cmds(g, 'F6')[0]['args'] for g in groups]
    f0 = [cmds(g, 'F0')[0]['args'] for g in groups]
    T['H'] = [d32(a[2], a[3]) for a in f0]
    T['G'] = [d32(a[4], a[5]) for a in f0]
    T['F7'] = [cmds(g, 'F7')[0]['args'] for g in groups]
    T['hd'] = [s32(((g['sec']['words'][0] & 0xFFFF) << 16) | (f0[i][0] & 0xFFFE)) for i, g in enumerate(groups)]
    T['gd'] = [s32(((g['sec']['words'][1] & 0xFFFF) << 16) | (f0[i][1] & 0xFFFE)) for i, g in enumerate(groups)]
    T['bit0'] = [(a[0] & 1, a[1] & 1) for a in f0]
    T['flags'] = [g['sec']['words'][2] for g in groups]
    T['w3'] = [g['sec']['words'][3] for g in groups]
    T['secn'] = [g['sec']['sec'] for g in groups]
    # Width / bank: group g delivers point g+1, group 0 additionally point 0
    Wn, Wp, Bk = [None] * (n + 1), [None] * (n + 1), [None] * (n + 1)
    for gi, g in enumerate(groups):
        b4, b5, ad = cmds(g, 'B4'), cmds(g, 'B5'), cmds(g, 'AD')
        if gi == 0:
            Wn[0], Wp[0], Bk[0] = b4[0]['args'][1], b5[0]['args'][1], ad[0]['args'][1]
        Wn[gi + 1], Wp[gi + 1], Bk[gi + 1] = b4[-1]['args'][1], b5[-1]['args'][1], ad[-1]['args'][1]
    if ring:
        if (Wn[n], Wp[n], Bk[n]) != (Wn[0], Wp[0], Bk[0]):
            # Mod tracks may jump at the start line (end-of-lap values differ from the start values)
            T['end_wb'] = (Wn[n], Wp[n], Bk[n])
        Wn, Wp, Bk = Wn[:n], Wp[:n], Bk[:n]
    T['Wn'], T['Wp'], T['Bk'] = Wn, Wp, Bk
    # Boundary lines (F5 = end values at point g+1, F4 = start values at point 0)
    E = [None] * (n + 1)
    for gi, g in enumerate(groups):
        f5 = cmds(g, 'F5')
        if f5:
            neg = [c['args'] for c in f5 if c['args'][0] < 0][0]
            pos = [c['args'] for c in f5 if c['args'][0] >= 0][0]
            E[gi + 1] = (neg, pos)
    f4 = cmds(groups[0], 'F4')
    if f4:
        neg = [c['args'] for c in f4 if c['args'][0] < 0][0]
        pos = [c['args'] for c in f4 if c['args'][0] >= 0][0]
        T['F4'] = (neg, pos)
        if ring:
            if E[n] != (neg, pos):
                T['E_end'] = E[n]        # mod tracks: edge lines jump at the start line
            E[0] = (neg, pos)
    if ring:
        E = E[:n]
    T['E'] = E
    T['CA'] = [[c['args'] for c in cmds(g, 'CA')] for g in groups]
    kerbs = []
    for gi, g in enumerate(groups):
        for c in g['cmds']:
            if c['cmd'] in ('F2', 'F3'):
                kerbs.append((gi, c['cmd'], list(c['args'])))
    T['kerbs'] = kerbs
    return T


def _wrap32(x):
    return (x + 2 ** 31) % 2 ** 32 - 2 ** 31


def integrated_headings(T, start):
    """Heading of every point as the game rebuilds it: start heading plus the summed per-segment turns
    ('hd'). The game derives the local frame direction of each segment (seg+0, used for the along-track
    position of cars) from this sum, not from the absolute headings (command F0)."""
    out = [start]
    for i in range(T['N'] - 1):
        out.append(s32(out[-1] + T['hd'][i]))
    return out


def _main_join_heading(TM, mg, cmd):
    """Integrated main-track heading at the group that holds the pit lane join command (86 = pit entry)."""
    gi = [i for i, g in enumerate(mg) for c in g['cmds'] if c['cmd'] == cmd]
    if not gi:
        return None
    return integrated_headings(TM, TM['H'][0])[gi[0]]


def _align_pit_heading(RM, RP, mg_new_join):
    """The pit lane build starts from the main track's integrated heading at the join (command 86). After
    mirroring, that heading differs from the first absolute pit heading by up to a few degrees (the original
    files agree exactly). The local frame of every pit segment is then rotated by that error, and cars
    parked 4-6 m beside the lane (the boxes) get an along-track position that is too small by
    lateral * sin(error): the pit stop is never accepted (stuck car, crew never starts). Fix: put the
    difference into the turn of the first pit segment, so that the integrated pit headings equal the
    absolute ones again. The main track itself is left untouched (changing its turns crashes the game)."""
    h = mg_new_join
    if h is None or RP['N'] < 2:
        return
    RP['hd'][0] = s32(RP['H'][1] - h)



def reverse_track_arrays(T, ring):
    n = T['N']
    R = {'N': n, 'ring': ring}
    if ring:
        P = lambda j: (n - j) % n                                   # point new -> old
        S = lambda j: n - 1 - j                                     # segment new -> old
    else:
        P = lambda j: n - 1 - j
        S = lambda j: n - 2 - j if j < n - 1 else n - 1             # last segment = dummy
    R['F6'] = [list(T['F6'][P(j)]) for j in range(n)]
    R['H'] = [s32(T['H'][P(j)] + 0x80000000) for j in range(n)]
    R['G'] = [s32(-T['G'][P(j)]) for j in range(n)]
    R['F7'] = [swap_f7(T['F7'][P(j)]) for j in range(n)]
    R['hd'] = [s32(-T['hd'][S(j)]) for j in range(n)]
    R['gd'] = [T['gd'][S(j)] for j in range(n)]
    R['bit0'] = [T['bit0'][S(j)] for j in range(n)]
    R['flags'] = [swap_flags(T['flags'][S(j)]) for j in range(n)]
    R['w3'] = [T['w3'][S(j)] for j in range(n)]
    R['secn'] = [T['secn'][S(j)] for j in range(n)]
    if ring:
        Q = lambda p: (n - p) % n
        R['Wn'] = [T['Wp'][Q(p)] for p in range(n)]
        R['Wp'] = [T['Wn'][Q(p)] for p in range(n)]
        R['Bk'] = [-T['Bk'][Q(p)] for p in range(n)]
        if T.get('end_wb'):
            ew = T['end_wb']
            R['end_wb'] = (T['Wp'][0], T['Wn'][0], -T['Bk'][0])
            R['Wn'][0], R['Wp'][0], R['Bk'][0] = ew[1], ew[0], -ew[2]
    else:
        Q = lambda p: n - 1 - p
        R['Wn'] = [T['Wp'][Q(p)] for p in range(n)] + [T['Wp'][0]]
        R['Wp'] = [T['Wn'][Q(p)] for p in range(n)] + [T['Wn'][0]]
        R['Bk'] = [-T['Bk'][Q(p)] for p in range(n)] + [-T['Bk'][0]]
    E = T['E']
    newE = [None] * len(E)
    for p in range(len(E)):
        if ring or p <= n - 1:
            q = Q(p)
            if E[q] is not None:
                neg, pos = E[q]
                newE[p] = (swap_side(pos, True), swap_side(neg, False))
    R['E'] = newE
    R['CA'] = []
    for j in range(n):
        lst = []
        for a in T['CA'][P(j)]:
            a2 = list(a)
            a2[0] = {2: 3, 3: 2}.get(a2[0], a2[0])
            lst.append(a2)
        R['CA'].append(lst)
    R['kerbs'] = []
    for (gi, c, a) in T['kerbs']:
        d, l, s_, e_ = a
        if d != 0:
            raise ValueError('kerb with delay not supported')
        if ring:
            if gi + l >= n:
                raise ValueError('kerb across the start line not supported')
            ng = n - gi - l
        else:
            ng = n - 1 - gi - l
        c2 = 'F3' if c == 'F2' else 'F2'
        R['kerbs'].append((ng, c2, [0, l, 0x4000 - e_, 0x4000 - s_]))
    return R


def emit_groups(R, extra_first=None, ring=True, e8_items=None):
    n = R['N']
    out = []
    for j in range(n):
        items = []
        if extra_first and j in extra_first:
            items += extra_first[j]
        if e8_items and j in e8_items and e8_items[j][0] == 'front':
            items += e8_items[j][1]
        for (gi, c, a) in sorted([k for k in R['kerbs'] if k[0] == j], key=lambda k: k[1]):
            items.append(mk(c, a))
        for a in sorted(R['CA'][j], key=lambda a: a[0]):
            items.append(mk('CA', a))
        if j == 0:
            items += [mk('B4', [0, R['Wn'][0]]), mk('B5', [0, R['Wp'][0]]), mk('AD', [0, R['Bk'][0]])]
            if R.get('F4'):
                items += [mk('F4', R['F4'][0]), mk('F4', R['F4'][1])]
        p1 = (j + 1) % n if ring else j + 1
        wnv, wpv, bkv = R['Wn'][p1], R['Wp'][p1], R['Bk'][p1]
        if ring and j == n - 1 and R.get('end_wb'):
            wnv, wpv, bkv = R['end_wb']
        items += [mk('B4', [1, wnv]), mk('B5', [1, wpv]), mk('AD', [1, bkv])]
        e = R['E'][p1]
        if e is not None:
            items += [mk('F5', e[0]), mk('F5', e[1])]
        items.append(mk('F7', R['F7'][j]))
        items.append(mk('F6', R['F6'][j]))
        hd, gd, b0 = R['hd'][j], R['gd'][j], R['bit0'][j]
        items.append(mk('F0', [(lo16(hd) & 0xFFFE) | b0[0], (lo16(gd) & 0xFFFE) | b0[1],
                               hi16(R['H'][j]), lo16(R['H'][j]), hi16(R['G'][j]), lo16(R['G'][j])]))
        if e8_items and j in e8_items and e8_items[j][0] == 'end':
            items += e8_items[j][1]
        out.append(items)
    return out


def assemble_stream(group_items, R):
    stream = []
    for j, items in enumerate(group_items):
        stream += items
        stream.append({'sec': R['secn'][j],
                       'words': [hi16(R['hd'][j]), hi16(R['gd'][j]), R['flags'][j], R['w3'][j]]})
    return stream


# ---------------------------------------------------------------------------
# Racing line

def racing_pieces(rl, N):
    """From the section list (it runs a little more than one lap) the really valid
    division of the ring: list of (start, count, radius_at_start, radius_step)."""
    gov = [None] * N
    k = 0
    for si, s in enumerate(rl):
        for j in range(s['len']):
            gov[k % N] = (si, j)
            k += 1
    if any(g is None for g in gov):
        raise ValueError('racing line does not cover the whole ring')
    info = []
    for s in rl:
        fl = int(s['flags'], 16)
        if not fl & 0x1000:
            raise ValueError('radii times 8 not supported')
        n = s['len']
        step = 0
        if fl & 0x2000:
            diff = s['end_radius'] - s['radius']
            step = abs(diff) // n * (1 if diff >= 0 else -1)
        info.append((s['radius'], step))
    starts = [p for p in range(N) if not (gov[p - 1][0] == gov[p][0] and gov[p - 1][1] + 1 == gov[p][1])]
    pieces = []
    for idx, p in enumerate(starts):
        nxt = starts[(idx + 1) % len(starts)]
        cnt = (nxt - p) % N or N
        si, j0 = gov[p]
        R0, step = info[si]
        pieces.append((p, cnt, R0 + j0 * step, step))
    if sum(c for _, c, _, _ in pieces) != N:
        raise ValueError('racing line division is inconsistent')
    return pieces


def merge_pieces(pieces, N):
    """Merge neighbouring pieces with a continuous radius progression (for comparison only)."""
    ps = sorted(pieces)
    out = []
    for p in ps:
        if out and out[-1][0] + out[-1][1] == p[0] and out[-1][3] == p[3] \
                and out[-1][2] + out[-1][1] * out[-1][3] == p[2]:
            a = out.pop()
            out.append((a[0], a[1] + p[1], a[2], a[3]))
        else:
            out.append(p)
    if len(out) > 1 and out[-1][0] + out[-1][1] == N and out[0][0] == 0 and out[-1][3] == out[0][3] \
            and out[-1][2] + out[-1][1] * out[-1][3] == out[0][2]:
        a, b = out.pop(), out.pop(0)
        out.insert(0, (a[0], a[1] + b[1], a[2], a[3]))
    return sorted(out)


def reverse_pieces(pieces, N):
    out = []
    for (a, n, R0, step) in pieces:
        r_last = R0 + (n - 1) * step
        out.append(((N - a - n) % N, n, -r_last, step))
    return out


TWO_PI = 2 * math.pi


def bam(a):
    return a * TWO_PI / 65536.0


def vf(a):                                   # forward vector (X, Z) for a 16 bit angle
    r = bam(a)
    return math.sin(r), math.cos(r)


def vn(a):                                   # side vector (right), same convention as the game
    r = bam(a)
    return math.cos(r), -math.sin(r)


def line_geometry(T):
    """Track values needed by the racing line calculation of the game
    (racing_line_build.asm: segment origin, heading, lateral angle)."""
    n = T['N']
    O = [(d32(*T['F6'][p][0:2]) / 256.0, d32(*T['F6'][p][4:6]) / 256.0) for p in range(n)]
    h = [(T['H'][p] >> 16) & 0xFFFF for p in range(n)]
    c = [hi16(T['hd'][p]) for p in range(n)]
    A = [(h[p] - (((c[p] >> 1) * 0x517D) >> 15)) & 0xFFFF for p in range(n)]
    return {'N': n, 'O': O, 'h': h, 'c': c, 'A': A, 'Wn': T['Wn'], 'Wp': T['Wp']}


def sim_piece(g, rec, n, L, psi, R):
    """A racing line section starting at segment rec with a fixed start state (lateral position L,
    angle psi) and radius R (0 = straight). Result: lateral position at the n cross lines
    rec+1 .. rec+n, or None if the calculation is not possible."""
    N = g['N']
    p0 = rec % N
    fh, nh = vf(g['h'][p0]), vn(g['h'][p0])
    along = L * g['c'][p0] / 32768.0
    px = g['O'][p0][0] + along * fh[0] + L * nh[0]
    pz = g['O'][p0][1] + along * fh[1] + L * nh[1]
    if R:
        sd = vn(psi)
        sg = 1 if R > 0 else -1
        rx, rz = px + sg * abs(R) * sd[0], pz + sg * abs(R) * sd[1]
    else:
        rx, rz = px, pz
    out = []
    for j in range(n):
        p = (rec + j + 1) % N
        A = g['A'][p]
        nn, ff = vn(A), vf(A)
        vx, vz = rx - g['O'][p][0], rz - g['O'][p][1]
        q = vx * nn[0] + vz * nn[1]
        l = vx * ff[0] + vz * ff[1]
        if R == 0:
            d = bam(psi - A)
            d = (d + math.pi) % TWO_PI - math.pi
            if abs(d) > 1.2:
                return None
            lat = q - l * math.tan(d)
        else:
            s2 = R * R - l * l
            if s2 <= 0:
                return None
            lat = q - (math.sqrt(s2) if R > 0 else -math.sqrt(s2))
        out.append(lat)
    return out


def _cost(g, rec, n, L, delta, R, prev_end, next_L, lam=40.0):
    N = g['N']
    psi = (g['A'][rec % N] + int(delta)) & 0xFFFF
    lats = sim_piece(g, rec, n, int(L), psi, R)
    if lats is None:
        return None, None
    states = [int(L)] + lats[:-1]
    cost = 0.0
    for k, lat in enumerate(states):
        p = (rec + k) % N
        w = g['Wn'][p] if lat < 0 else g['Wp'][p]
        r = lat / float(w)
        cost += r * r
        if abs(r) > 0.8:
            cost += 80.0 * (abs(r) - 0.8) ** 2
    w0 = float(min(g['Wn'][rec % N], g['Wp'][rec % N]))
    if prev_end is not None:
        cost += lam * ((L - prev_end) / w0) ** 2
    if next_L is not None:
        cost += lam * ((lats[-1] - next_L) / w0) ** 2
    return cost, lats[-1]


def _fit_piece(g, rec, n, R, prev_end, next_L):
    N = g['N']
    w = float(min(g['Wn'][rec % N], g['Wp'][rec % N]))
    cands = []
    deltas = [0] if n == 1 else range(-3000, 3001, 500)
    for fl in (-0.6, -0.3, 0.0, 0.3, 0.6):
        for dl in deltas:
            c, e = _cost(g, rec, n, fl * w, dl, R, prev_end, next_L)
            if c is not None:
                cands.append((c, fl * w, dl))
    if not cands:
        return None
    cands.sort()
    best = None
    for c0, L0, d0 in cands[:4]:
        L, d, c = L0, d0, c0
        sL, sd = 0.15 * w, 250.0
        for _ in range(7):
            improved = True
            while improved:
                improved = False
                moves = [(L + sL, d), (L - sL, d)] + ([] if n == 1 else [(L, d + sd), (L, d - sd)])
                for (xL, xd) in moves:
                    if abs(xL) > 0.9 * w:
                        continue
                    cc, e = _cost(g, rec, n, xL, xd, R, prev_end, next_L)
                    if cc is not None and cc < c - 1e-9:
                        L, d, c = xL, xd, cc
                        improved = True
            sL, sd = sL / 2, sd / 2
        if best is None or c < best[0]:
            best = (c, int(round(L)), int(round(d)))
    c, e = _cost(g, rec, n, best[1], best[2], R, prev_end, next_L)
    return best[1], best[2], e


def piece_mid_radius(R0, n, step):
    return R0 + int(((n - 1) * step) / 2.0)


def linearize(pieces, N):
    lin = []
    for (a, n, R0, step) in sorted(pieces):
        if a + n > N:                                   # across point 0: split
            na = N - a
            lin.append((a, na, R0, step))
            lin.append((0, n - na, R0 + na * step, step))
        else:
            lin.append((a, n, R0, step))
    lin.sort()
    pos = 0
    for a, n, _, _ in lin:
        if a != pos:
            raise ValueError('racing line has a gap')
        pos += n
    if pos != N:
        raise ValueError('racing line does not cover the ring')
    return lin


def chain_step(g, rec, n, pen_lat, pen_A, R, cx):
    """A section that takes over the state (lateral position, angle) of the previous one - as the
    game does it (racing_line_build.asm). cx = shift (arc) or kink (straight).
    Result: stored lateral positions at segments rec .. rec+n-1, end position, end angle."""
    N = g['N']
    p0 = rec % N
    if R == 0:
        pen_A = (pen_A + cx) & 0xFFFF
        fwd = 0
    else:
        fwd = cx * 4
    fh, nh = vf(g['h'][p0]), vn(g['h'][p0])
    along = pen_lat * g['c'][p0] / 32768.0
    px = g['O'][p0][0] + along * fh[0] + pen_lat * nh[0]
    pz = g['O'][p0][1] + along * fh[1] + pen_lat * nh[1]
    fa = vf(pen_A)
    rx, rz = px + fwd * fa[0], pz + fwd * fa[1]
    if R:
        sd = vn(pen_A)
        sg = 1 if R > 0 else -1
        rx, rz = rx + sg * abs(R) * sd[0], rz + sg * abs(R) * sd[1]
    stored, lat = [], pen_lat
    for j in range(n):
        stored.append(lat)
        p = (rec + j + 1) % N
        A = g['A'][p]
        nn, ff = vn(A), vf(A)
        vx, vz = rx - g['O'][p][0], rz - g['O'][p][1]
        q = vx * nn[0] + vz * nn[1]
        l = vx * ff[0] + vz * ff[1]
        if R == 0:
            d = (bam(pen_A - A) + math.pi) % TWO_PI - math.pi
            if abs(d) > 1.2:
                return None
            lat = q - l * math.tan(d)
        else:
            s2 = R * R - l * l
            if s2 <= 0:
                return None
            ss = math.sqrt(s2) if R > 0 else -math.sqrt(s2)
            lat = q - ss
            phi = int(round(math.atan2(ss, l) * 65536 / TWO_PI))
            pen_A = (phi - 0x4000 + A) & 0xFFFF if R > 0 else (phi + 0x4000 + A) & 0xFFFF
    return stored, lat, pen_A


def _chain_cost(g, rec, n, pen_lat, pen_A, R, cx):
    res = chain_step(g, rec, n, pen_lat, pen_A, R, cx)
    if res is None:
        return None
    stored, lat, A = res
    N = g['N']
    cost = 0.0
    for k, x in enumerate(stored):
        p = (rec + k) % N
        r = x / float(g['Wn'][p] if x < 0 else g['Wp'][p])
        cost += r * r
        if abs(r) > 0.75:
            cost += 80.0 * (abs(r) - 0.75) ** 2
    pe = (rec + n) % N
    w0 = float(min(g['Wn'][pe], g['Wp'][pe]))
    cost += 3.0 * (lat / w0) ** 2
    cost += 3.0 * (s16(A - g['A'][pe]) / 1500.0) ** 2
    return cost, lat, A


LINE_KINK_MAX = 0            # largest kink of a straight (original: always 0 - only that is known for sure)
LINE_CX_MAX = 0              # largest shift of an arc (original: almost always 0)
LINE_SPLIT_MIN = 12          # pieces from this length on are halved
LINE_STRAIGHT_RADII = (250000, 400000, 800000, 1600000)   # very wide arcs as steering for straights
LINE_SCALES = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5)


def chain_fit(g, lin, N, extra_steps=40, beam=800):
    """Like chain_fit_greedy, but with beam search: several intermediate states are
    followed at the same time, so that a later corner does not fail because of a too early
    decision."""
    # split long pieces into two halves: more steering options through the radius alone
    parts = []
    for (a, n, R0, st) in lin:
        if n >= LINE_SPLIT_MIN:
            n1 = n // 2
            parts += [(a, n1, R0, st), (a + n1, n - n1, R0 + n1 * st, st)]
        else:
            parts.append((a, n, R0, st))
    lin = parts
    seq, extra, i = list(lin), 0, 0
    while extra < extra_steps:
        seq.append(lin[i])
        extra += lin[i][1]
        i += 1
    states = [(0.0, 0, g['h'][0], None, None)]
    rec = 0
    for idx, (a, n, R0, st) in enumerate(seq):
        R = piece_mid_radius(R0, n, st)
        opts = []
        if n == 1:
            opts.append((0, R))
        else:
            if R == 0:
                opts.append((0, 0))
                opts += [(0, sg * r) for r in LINE_STRAIGHT_RADII for sg in (1, -1)]
            elif abs(R) > 200000:
                opts += [(kk, 0) for kk in range(-LINE_KINK_MAX, LINE_KINK_MAX + 1, max(LINE_KINK_MAX // 5, 1))]
            if R != 0:
                opts += [(cc, int(R * sc)) for cc in range(-LINE_CX_MAX, LINE_CX_MAX + 1, max(LINE_CX_MAX // 5, 1))
                         for sc in LINE_SCALES]
        cand = {}
        for (c0, lat0, A0, par, info) in states:
            res = []
            for cx, Rt in opts:
                r = _chain_cost(g, rec, n, lat0, A0, Rt, cx)
                if r is not None:
                    res.append((r[0], cx, Rt, r[1], r[2]))
            res.sort()
            for cc, cx, Rt, lat, A in res[:4]:
                key = (int(lat // 60), int(A // 120))
                tot = c0 + cc
                if key not in cand or cand[key][0] > tot:
                    cand[key] = (tot, lat, A, (c0, lat0, A0, par, info), (rec, n, cx, Rt))
        if not cand:
            raise ValueError('racing line: section from segment %d (length %d) cannot be calculated' % (rec % N, n))
        states = sorted(cand.values(), key=lambda s: s[0])[:beam]
        # state = (cost, position, angle, parent, info) - parent is the whole parent tuple
        states = [(s[0], s[1], s[2], s[3], s[4]) for s in states]
        rec += n
    best = states[0]
    chain = []
    cur = best
    while cur is not None and cur[4] is not None:
        chain.append(cur[4])
        cur = cur[3]
    chain.reverse()
    secs, final = [], {}
    lat, A = 0, g['h'][0]
    for idx, (rec, n, cx, Rt) in enumerate(chain):
        stored, lat, A = chain_step(g, rec, n, lat, A, Rt, cx)
        for k, x in enumerate(stored):
            final[(rec + k) % N] = x
        s = {'len': n, 'flags': '5000', 'cx': cx, 'radius': Rt}
        if idx == 0:
            s['flags'] = 'D000'
            s['lateral'] = 0
            s['heading'] = s16(g['h'][0])
        secs.append(s)
    worst = max(abs(final[p]) / float(g['Wn'][p] if final[p] < 0 else g['Wp'][p]) for p in range(N))
    seam = abs(final[0] - final[N - 1])
    return secs, {'sections': len(secs), 'max_lateral_share': worst, 'max_jump': seam,
                  'straights_for_circles': 0}


def chain_fit_greedy(g, lin, N, extra_steps=40):
    """Racing line as a chain without intermediate start points (as in the original and as GP4 Builder shows it).
    For every section the shift/kink (and slightly the radius) is chosen so that the line
    stays on the track. The chain runs beyond segment 0 (as in the original) so that the
    start is overwritten by the continued line."""
    seq, tot = [], 0
    for item in lin:
        seq.append(item)
    extra, i = 0, 0
    while extra < extra_steps:
        seq.append(lin[i])
        extra += lin[i][1]
        i += 1
    pen_lat, pen_A = 0, g['h'][0]
    secs, final = [], {}
    rec = 0
    for idx, (a, n, R0, st) in enumerate(seq):
        R = piece_mid_radius(R0, n, st)
        best = None
        if R == 0:
            opts = [(0, 1.0)] if n == 1 else [(kk, 1.0) for kk in range(-1500, 1501, 150)]
        else:
            opts = [(cc, sc) for cc in range(-250, 251, 50) for sc in (0.85, 1.0, 1.15)] if n > 1 else [(0, 1.0)]
        scored = []
        for cx, sc in opts:
            Rt = int(R * sc)
            r = _chain_cost(g, rec, n, pen_lat, pen_A, Rt, cx)
            if r is not None:
                scored.append((r[0], cx, sc))
        if not scored:
            raise ValueError('racing line: section from segment %d (length %d) cannot be calculated' % (rec % N, n))
        scored.sort()
        for c0, cx0, sc0 in scored[:3]:
            cx, sc, c = cx0, sc0, c0
            step = 100.0 if R == 0 else 40.0
            for _ in range(6):
                improved = True
                while improved and n > 1:
                    improved = False
                    for (xc, xs) in ((cx + step, sc), (cx - step, sc)) + (((cx, sc * 1.05), (cx, sc / 1.05)) if R else ()):
                        r = _chain_cost(g, rec, n, pen_lat, pen_A, int(R * xs), int(round(xc)))
                        if r is not None and r[0] < c - 1e-9:
                            cx, sc, c = xc, xs, r[0]
                            improved = True
                step /= 2
            if best is None or c < best[0]:
                best = (c, int(round(cx)), sc)
        _, cx, sc = best
        Rt = int(R * sc)
        stored, pen_lat2, pen_A2 = chain_step(g, rec, n, pen_lat, pen_A, Rt, cx)
        for k, x in enumerate(stored):
            final[(rec + k) % N] = x
        fl = 0x5000
        s = {'len': n, 'flags': '%04X' % fl, 'cx': cx, 'radius': Rt}
        if idx == 0:
            s['flags'] = 'D000'
            s['lateral'] = 0
            s['heading'] = s16(g['h'][0])
        secs.append(s)
        pen_lat, pen_A = pen_lat2, pen_A2
        rec += n
    worst = max(abs(final[p]) / float(g['Wn'][p] if final[p] < 0 else g['Wp'][p]) for p in range(N))
    seam = abs(final[0] - final[N - 1])
    return secs, {'sections': len(secs), 'max_lateral_share': worst, 'max_jump': seam,
                  'straights_for_circles': 0}


def anchored_line(g, pieces, N, chain=True):
    """New racing line: every section gets its own start state (flags 0x8000+0x0800),
    chosen so that the line surely stays on the track. Nothing can build up that way.
    Spirals become circles with a mean radius."""
    lin = linearize(pieces, N)
    # Preparation: sections that cannot be kept on the track as ONE circle
    # (spirals, long arcs) are halved until every piece fits.
    todo, done = list(lin), []
    while todo:
        a, n, R0, st = todo.pop(0)
        fit = _fit_piece(g, a, n, piece_mid_radius(R0, n, st), None, None)
        ok = False
        if fit is not None:
            lats = sim_piece(g, a, n, fit[0], (g['A'][a % N] + fit[1]) & 0xFFFF, piece_mid_radius(R0, n, st))
            states = [fit[0]] + lats[:-1]
            worst = max(abs(x) / float(g['Wn'][(a + i) % N] if x < 0 else g['Wp'][(a + i) % N])
                        for i, x in enumerate(states))
            ok = worst <= 0.7
        if ok or n < 4:
            done.append((a, n, R0, st))
        else:
            n1 = n // 2
            todo.insert(0, (a + n1, n - n1, R0 + n1 * st, st))
            todo.insert(0, (a, n1, R0, st))
    lin = sorted(done)
    if chain:
        return chain_fit(g, lin, N)
    K = len(lin)
    radii = [piece_mid_radius(R0, n, st) for (a, n, R0, st) in lin]
    params = [None] * K
    ends = [None] * K
    for sweep in range(6):
        for k in range(K):
            a, n, _, _ = lin[k]
            prev_end = ends[(k - 1) % K] if ends[(k - 1) % K] is not None else None
            next_L = params[(k + 1) % K][0] if params[(k + 1) % K] is not None else None
            fit = _fit_piece(g, a, n, radii[k], prev_end, next_L)
            if fit is None and radii[k]:
                # Emergency: the circle does not fit - try a straight
                radii[k] = 0
                fit = _fit_piece(g, a, n, 0, prev_end, next_L)
            if fit is None:
                raise ValueError('racing line section from segment %d (length %d) cannot be kept on the track' % (a, n))
            params[k] = (fit[0], fit[1])
            ends[k] = fit[2]
    secs, worst, jump = [], 0.0, 0.0
    for k, (a, n, _, _) in enumerate(lin):
        L, d = params[k]
        psi = (g['A'][a % N] + d) & 0xFFFF
        secs.append({'len': n, 'flags': 'D800', 'lateral': L, 'heading': s16(psi), 'cx': 0, 'radius': radii[k]})
        lats = sim_piece(g, a, n, L, psi, radii[k])
        for i, lat in enumerate([L] + lats[:-1]):
            p = (a + i) % N
            worst = max(worst, abs(lat) / float(g['Wn'][p] if lat < 0 else g['Wp'][p]))
        jump = max(jump, abs(lats[-1] - params[(k + 1) % K][0]))
    return secs, {'sections': K, 'max_lateral_share': worst, 'max_jump': jump,
                  'straights_for_circles': sum(1 for k in range(K) if radii[k] == 0 and piece_mid_radius(lin[k][2], lin[k][1], lin[k][3]) != 0)}


def pieces_to_sections(pieces, N, first_lat, first_head):
    lin = []
    for (a, n, R0, step) in sorted(pieces):
        if a + n > N:                                   # across point 0: split
            na = N - a
            lin.append((a, na, R0, step))
            lin.append((0, n - na, R0 + na * step, step))
        else:
            lin.append((a, n, R0, step))
    lin.sort()
    pos = 0
    for a, n, _, _ in lin:
        if a != pos:
            raise ValueError('racing line has a gap')
        pos += n
    if pos != N:
        raise ValueError('racing line does not cover the ring')
    secs = []
    for idx, (a, n, R0, step) in enumerate(lin):
        fl = 0x5000 | (0x2000 if step else 0) | (0x8000 if idx == 0 else 0)
        s = {'len': n, 'flags': '%04X' % fl}
        if idx == 0:
            s['lateral'] = first_lat
            s['heading'] = first_head
        s['cx'] = 0
        s['radius'] = R0
        if step:
            s['end_radius'] = R0 + step * n
        secs.append(s)
    return secs


# ---------------------------------------------------------------------------
# Cameras: 19 words per record (see docs/formats/circuit-dat.md in the gp4-decomp project)

def reverse_cameras(cams, N):
    out = []
    for h in cams:
        w = list(struct.unpack('<19H', bytes.fromhex(h)))
        p = w[0] & 0x3FFF
        sw = w[5] & 0x3FFF
        L = p - sw                                       # distance camera - switch point stays
        w[0] = (w[0] & 0xC000) | ((N - 1 - p) % N)
        w[1] = (-s16(w[1])) & 0xFFFF
        w[3] = (w[3] & 0xC000) | ((N - 1 - (w[3] & 0x3FFF)) % N)
        w[5] = (w[5] & 0xC000) | ((N - 1 - p - L) % N)
        out.append(w)
    out.sort(key=lambda w: w[5] & 0x3FFF)
    return [struct.pack('<19H', *w).hex() for w in out]


# ---------------------------------------------------------------------------
# The whole reversal

PIT_SWAP = {'9B': '9E', '9E': '9B', '9F': 'A0', 'A0': '9F', '96': '97', '97': '96', '89': 'F1', 'F1': '89'}


def reverse_json(j):
    j = copy.deepcopy(j)
    mg = split_groups(j['main_stream'])
    pg = split_groups(j['pit_stream'])
    N, NP = len(mg), len(pg)
    TM = read_track(mg, True)
    TP = read_track(pg, False)
    RM = reverse_track_arrays(TM, True)
    RP = reverse_track_arrays(TP, False)
    # heading of the reversed main track at the new pit entry (= old pit exit, command 87), as the game sums it
    _joins = [i for i, g in enumerate(mg) for c in g['cmds'] if c['cmd'] == '87']
    if _joins:
        _hm = integrated_headings(RM, RM['H'][0])[(N - _joins[0]) % N]
        _align_pit_heading(RM, RP, _hm)
    if TM.get('F4'):
        src = TM.get('E_end') or TM['F4']
        RM['F4'] = (swap_side(src[1], True), swap_side(src[0], False))

    # Main track: special commands in group 0, pit lane joins
    g0 = mg[0]['cmds']
    first = {0: []}
    first[0] += [copy.deepcopy(c) for c in g0 if c['cmd'] in ('BD', 'CC')]
    for c in g0:
        if c['cmd'] in ('DE', 'DF'):
            a = c['args']
            first[0].append(mk('DF' if c['cmd'] == 'DE' else 'DE', [N - a[1], N - a[0], a[2]]))
    ef = [c for c in g0 if c['cmd'] == 'EF'][0]['args']
    first[0].append(mk('EF', [lo16(RM['H'][0]), lo16(RM['G'][0]), ef[3], ef[2]]))
    for gi, g in enumerate(mg):
        for c in g['cmds']:
            if c['cmd'] in ('86', '87'):
                first.setdefault((N - gi) % N, []).append(mk('87' if c['cmd'] == '86' else '86', c['args']))
    e8m = {}                                             # the starting grid stays behind the line
    for gi, g in enumerate(mg):
        items = [copy.deepcopy(c) for c in g['cmds'] if c['cmd'] == 'E8']
        if items:
            e8m[gi] = ('end' if g['cmds'][-1]['cmd'] == 'E8' else 'front', items)
    j['main_stream'] = assemble_stream(emit_groups(RM, extra_first=first, ring=True, e8_items=e8m), RM)

    # Pit lane
    pit_first = {}
    ae = [copy.deepcopy(c) for c in pg[0]['cmds'] if c['cmd'] == 'AE']
    if ae:
        pit_first[0] = ae
    marks = {}
    allmarks = set(c['cmd'] for g in pg for c in g['cmds'])
    box = '88' if '88' in allmarks and '89' not in allmarks else '89'      # first pit box command
    swap = dict(PIT_SWAP)
    swap.pop('89'); swap['F1'] = box; swap[box] = 'F1'
    for gi, g in enumerate(pg):
        for c in g['cmds']:
            if c['cmd'] in swap:
                marks[c['cmd']] = (gi + c['seg'], c['args'])
    for cmd, (tg, args) in marks.items():
        ncmd = swap[cmd]
        ng = NP - 2 - tg
        if ncmd == box:
            ng += 1      # box area start: mirrored segment range [first box, F1) starts at NP-1-F1, so box k keeps its own place
        a = list(marks[box][1]) if ncmd == box and box in marks else []
        pit_first.setdefault(ng, []).append(mk(ncmd, a))
    e8p = {}
    for gi, g in enumerate(pg):
        for c in g['cmds']:
            if c['cmd'] == 'E8':
                t = gi + c['seg']
                n_, st = c['args'][0], max(c['args'][1], 1)
                nt = NP - 2 - (t + (n_ - 1) * st)
                a = list(c['args'])
                a[3] = -a[3]
                e8p.setdefault(nt, ('front', []))[1].append(mk('E8', a))
    j['pit_stream'] = assemble_stream(emit_groups(RP, extra_first=pit_first, ring=False, e8_items=e8p), RP)

    # Header (change of the flags 0x2 / 0x8 and of the grid file: switches the side of pole position)
    th = j['track_header']
    th['start_heading'] = s16(th['start_heading'] + 0x8000)
    th['start_gradient'] = s16(-th['start_gradient'])
    th['flags'] = s16(th['flags'] ^ 0x000A)
    j['file_names'] = [n.replace('gridleft', 'gridline') if 'gridleft' in n else n.replace('gridline', 'gridleft')
                       for n in j['file_names']]

    # Racing line
    pieces = racing_pieces(j['racing_line'], N)
    rp = reverse_pieces(pieces, N)
    geo = line_geometry(read_track(split_groups(j['main_stream']), True))
    j['racing_line'], j['_line_report'] = anchored_line(geo, rp, N)

    # Cameras
    j['cameras_hex'] = reverse_cameras(j['cameras_hex'], N)
    return j


# ---------------------------------------------------------------------------
# Checks

def canon(stream, pit=False, relaxed=False):
    """Comparison form: commands of a group unordered; E8 with absolute target segment (group + offset);
    for the pit lane the width values of the dummy point behind the end do not count.
    relaxed=True ignores what a reversal changes on purpose and therefore cannot be undone by reversing twice:
      - the pit box marks (89 / F1) are moved by one segment (box alignment, 0.9.1),
      - the turn of the first and the last pit segment (pit heading alignment, 0.9.2),
      - the low bits of the start heading in the main stream (EF).
    The positions of the box marks are compared separately (at most one group apart)."""
    res, e8, marks = [], [], {}
    groups = split_groups(stream)
    for gi, x in enumerate(groups):
        items = []
        sec = x['sec']
        for c in x['cmds']:
            if c['cmd'] == 'E8':
                e8.append((gi + c['seg'], json.dumps(c['args'])))
                continue
            if pit and gi == len(groups) - 1 and c['cmd'] in ('B4', 'B5', 'AD'):
                continue
            if relaxed:
                if c['cmd'] in ('89', '88', 'F1'):
                    marks[c['cmd']] = gi
                    continue
                if c['cmd'] == 'EF' and not pit and gi == 0:
                    c = dict(c, args=[0] + list(c['args'][1:]))
                if pit and c['cmd'] == 'F0' and gi in (0, len(groups) - 2):
                    c = dict(c, args=[0] + list(c['args'][1:]))
                    sec = dict(sec, words=[0] + list(sec['words'][1:]))
            items.append(json.dumps({k: v for k, v in c.items() if k != 'note'}, sort_keys=True))
        res.append((sorted(items), sec))
    res.append((sorted(e8), None))
    if relaxed:
        res.append((marks, None))
    return res


def _marks_close(a, b):
    ma, mb = a[-1][0], b[-1][0]
    return set(ma) == set(mb) and all(abs(ma[k] - mb[k]) <= 1 for k in ma)


def selftest(j0, j1):
    """Reversing twice must give the original again."""
    j2 = reverse_json(j1)
    ok = True
    for name in ('main_stream', 'pit_stream'):
        a, b = canon(j0[name], name == 'pit_stream', True), canon(j2[name], name == 'pit_stream', True)
        diffs = [i for i in range(len(a) - 1) if a[i] != b[i]]
        if not _marks_close(a, b):
            diffs.append('box marks')
        print('  reversed twice, %-12s: %s' % (name, 'identical (without the deliberate changes)' if not diffs else 'DIFFERENCE in groups %s' % diffs[:10]))
        ok &= not diffs
    for k in ('track_header', 'cameras_hex', 'file_names'):
        same = j0[k] == j2[k]
        print('  reversed twice, %-12s: %s' % (k, 'identical' if same else 'DIFFERENCE'))
        ok &= same
    N = len(split_groups(j0['main_stream']))
    def cp(rl):                         # sign of the radius per segment (curve direction / straight)
        prof = [0] * N
        for (a, n, R0, st) in racing_pieces(rl, N):
            for i in range(n):
                r = R0 + i * st
                prof[(a + i) % N] = 0 if abs(r) > 200000 else (r > 0) - (r < 0)   # huge radii = straight
        return prof
    hc = heading_check(j1)
    print('  pit lane heading sum vs absolute heading: %.4f degrees (%s)' % (hc, 'ok' if hc < 0.01 else 'DEVIATION'))
    ok &= hc < 0.01
    p0, p2 = cp(j0['racing_line']), cp(j2['racing_line'])
    nd = sum(1 for x, y in zip(p0, p2) if x != y)     # almost straight places may turn straight <-> very wide arc
    flips = sum(1 for x, y in zip(p0, p2) if x * y < 0)   # a change of direction (left <-> right) would be an error
    print('  reversed twice, racing line    : %s' % ('curve directions identical' if nd == 0 else
                                                      ('curve directions equal, %d of %d segments almost straight (straight <-> wide arc)' % (nd, N)
                                                       if flips == 0 else 'DIFFERENCE: %d segments with swapped curve direction' % flips)))
    ok &= flips == 0
    return ok


def chord_error(j):
    """Mean deviation (in 1/65536 circle) between heading and direction to the next point."""
    T = read_track(split_groups(j['main_stream']), True)
    n = T['N']
    tot = 0
    for p in range(n):
        x0, z0 = d32(*T['F6'][p][0:2]), d32(*T['F6'][p][4:6])
        x1, z1 = d32(*T['F6'][(p + 1) % n][0:2]), d32(*T['F6'][(p + 1) % n][4:6])
        a = math.atan2(x1 - x0, z1 - z0) * 65536 / (2 * math.pi)
        d = (a - ((T['H'][p] >> 16) & 0xFFFF) + 32768) % 65536 - 32768
        tot += abs(d)
    return tot / n


def curvature_error(j):
    """Mean deviation between the heading change per segment and the section value."""
    T = read_track(split_groups(j['main_stream']), True)
    n = T['N']
    e = 0
    for p in range(n):
        e += abs(s32(T['H'][(p + 1) % n] - T['H'][p]) - T['hd'][p]) / 65536.0
    return e / n


def join_check(j):
    """Are the start / end of the pit lane at the main track point of the join commands 86 / 87?"""
    mg, pg = split_groups(j['main_stream']), split_groups(j['pit_stream'])
    TM, TP = read_track(mg, True), read_track(pg, False)
    pos = lambda T, i: (d32(*T['F6'][i][0:2]) / 256.0, d32(*T['F6'][i][4:6]) / 256.0)
    joins = {c['cmd']: gi for gi, g in enumerate(mg) for c in g['cmds'] if c['cmd'] in ('86', '87')}
    res = []
    for cmd, pi in (('86', 0), ('87', TP['N'] - 1)):
        x, z = pos(TP, pi)
        best = min(range(TM['N']), key=lambda m: math.hypot(pos(TM, m)[0] - x, pos(TM, m)[1] - z))
        res.append('%s at %d, nearest main point %d' % (cmd, joins[cmd], best))
    return '; '.join(res)


def heading_check(j):
    """Largest difference (degrees) between the pit lane headings the game will sum up and the absolute
    pit headings; ~0 for the originals, up to ~4 degrees for a naively mirrored file."""
    mg = split_groups(j['main_stream'])
    pg = split_groups(j['pit_stream'])
    TM = read_track(mg, True)
    TP = read_track(pg, False)
    h = _main_join_heading(TM, mg, '86')
    if h is None:
        return 0.0
    ip = integrated_headings(TP, h)
    return max(abs(_wrap32(ip[k] - TP['H'][k])) * 360.0 / 2 ** 32 for k in range(1, TP['N']))



def main(argv):
    if len(argv) < 3:
        print('usage: python reverse_core.py INPUT.DAT OUTPUT.DAT   (reverse_track.py is the normal entry point)')
        return 2
    src, dst = argv[1], argv[2]
    if os.path.basename(os.path.dirname(os.path.abspath(dst))).lower() == 'circuits':
        print('Aborted: writing into the "Circuits" folder is blocked on purpose.')
        return 2
    raw = open(src, 'rb').read()
    j0 = gt.dump(raw)
    if gt.build(json.loads(json.dumps(j0))) != raw:
        print('ERROR: the input file cannot be rebuilt byte for byte')
        return 1
    j1 = reverse_json(j0)
    print('Self test:')
    ok = selftest(j0, j1)
    print('Geometry: heading-to-chord deviation old %.1f / new %.1f (per point, 65536 = full circle)'
          % (chord_error(j0), chord_error(j1)))
    print('Geometry: curvature deviation old %.3f / new %.3f' % (curvature_error(j0), curvature_error(j1)))
    rep = j1.pop('_line_report')
    print('Racing line: %(sections)d sections, largest lateral offset %(max_lateral_share).2f of the half width, '
          'largest jump between sections %(max_jump).0f, circles replaced by straights: %(straights_for_circles)d' % rep)
    print('Pit lane heading sum vs absolute heading (degrees): original %.3f / reversed %.3f'
          % (heading_check(j0), heading_check(j1)))
    print('Pit lane joins old: ' + join_check(j0))
    print('Pit lane joins new: ' + join_check(j1))
    out = gt.build(j1)
    j3 = gt.dump(out)
    if gt.build(j3) != out:
        print('ERROR: the new file cannot be rebuilt stably')
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    open(dst, 'wb').write(out)
    print('written: %s (%d bytes, original %d)' % (dst, len(out), len(raw)))
    gt.info(j3)
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv))
