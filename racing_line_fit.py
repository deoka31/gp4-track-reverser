"""Racing line fit for reversed GP4 tracks.
Runs the REAL routine RacingLine_BuildIntoSegments (GP4.exe, 0x40abc1) in an x86 emulator (unicorn)
and fits a chain of sections to the mirrored original line.
Needs: pip install unicorn and GP4.exe. Results for the 17 original tracks are delivered in racing_lines/."""
import sys, os, struct, json, math, time, copy
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = None
Q = None        # module with read_track/split_groups/reverse_json (reverse_core)
N = 884
LASTP = 883


def configure(exe, core, n):
    global EXE, Q, N, LASTP
    EXE, Q, N, LASTP = exe, core, n, n - 1


def _unicorn():
    global Uc, UC_ARCH_X86, UC_MODE_32, UC_X86_REG_ESP, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP, \
        UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EAX
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import (UC_X86_REG_ESP, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP,
                                   UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EAX)

"""(Exact racing line builder: runs the real RacingLine_BuildIntoSegments (GP4.exe 0x40abc1) in Unicorn.
Segment records are filled from the track JSON the way TrackBuild_InitNewSegment does it."""

BASE = 0x400000
SEGSZ = 0x160
SEG = 0x30000000
STREAM = 0x40000000
STACK = 0x50000000

A_FIRST, A_LAST, A_LASTOFF, A_PITFIRST, A_PITLAST = 0x891504, 0x866ecc, 0x866ec4, 0x891500, 0x866ef8
FUNC = 0x40abc1


def s16(v):
    v &= 0xFFFF
    return v - 65536 if v >= 32768 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


class Sim:
    def __init__(self):
        _unicorn()
        d = open(EXE, 'rb').read()
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        nsec = struct.unpack_from('<H', d, pe + 6)[0]
        opt = struct.unpack_from('<H', d, pe + 20)[0]
        so = pe + 24 + opt
        self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu = self.mu
        mu.mem_map(BASE, 0x780000 + 0x400000 - 0x400000)   # up to 0xB80000
        for i in range(nsec):
            nm, vs, va0, rs, ro = struct.unpack_from('<8sIIII', d, so + i * 40)
            mu.mem_write(BASE + va0, d[ro:ro + min(rs, vs)])
        mu.mem_map(SEG, 0x200000)
        mu.mem_map(STREAM, 0x10000)
        mu.mem_map(STACK, 0x10000)
        self.snap = None

    def setup_track(self, T):
        """T: dict with N, O (F6 centre X,Z in 1/256 units as ints: x256, z256), Hm (seg+0 words), c14, """
        mu = self.mu
        N = T['N']
        self.N = N
        mu.mem_write(SEG, b'\0' * (0x160 * (N + 16)))
        for p in range(N):
            b = SEG + p * SEGSZ
            x, z = T['X'][p], T['Z'][p]
            mu.mem_write(b + 0, struct.pack('<H', T['H0'][p] & 0xFFFF))
            mu.mem_write(b + 4, struct.pack('<h', s16(x >> 11)))
            mu.mem_write(b + 8, struct.pack('<h', s16(z >> 11)))
            mu.mem_write(b + 0x14, struct.pack('<h', s16(T['c14'][p])))
            mu.mem_write(b + 0x21, bytes([(((x >> 8) & 7) | (((z >> 8) & 7) << 4)) & 0xFF]))
        w = lambda a, v: mu.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))
        w(A_FIRST, SEG)
        w(A_LAST, SEG + (N - 1) * SEGSZ)
        w(A_LASTOFF, (N - 1) * SEGSZ)
        w(A_PITFIRST, SEG + (N - 1) * SEGSZ + 0x420)
        w(A_PITLAST, SEG + (N - 1) * SEGSZ + 0x420 + 260 * SEGSZ)

    @staticmethod
    def encode(secs):
        out = []
        for s in secs:
            fl = int(s['flags'], 16)
            out.append((fl & 0xF800) | s['len'])
            if fl & 0x8000:
                out += [s['lateral'] & 0xFFFF, s['heading'] & 0xFFFF]
            out.append(s['cx'] & 0xFFFF)

            def rad(v):
                if not (fl & 0x1000):
                    v = v // 8
                if fl & 0x4000:
                    return [(v >> 16) & 0xFFFF, v & 0xFFFF]
                return [v & 0xFFFF]
            out += rad(s['radius'])
            if fl & 0x2000:
                out += rad(s['end_radius'])
        out.append(0)
        return struct.pack('<%dH' % len(out), *out)

    def run(self, secs, trace=None):
        mu = self.mu
        data = self.encode(secs)
        mu.mem_write(STREAM, data)
        # clear racing line fields
        for p in range(self.N + 1):
            mu.mem_write(SEG + p * SEGSZ + 0x16, b'\0\0\0\0')
        sp = STACK + 0x8000
        ret = 0x41000000
        mu.mem_map(ret, 0x1000) if not hasattr(self, '_ret') else None
        self._ret = ret
        sp -= 4
        mu.mem_write(sp, struct.pack('<I', ret))
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ESI, STREAM)
        mu.reg_write(UC_X86_REG_EDI, 0)
        mu.reg_write(UC_X86_REG_EBX, 0)
        mu.reg_write(UC_X86_REG_EBP, 0)
        mu.reg_write(UC_X86_REG_ECX, 0)
        mu.reg_write(UC_X86_REG_EDX, 0)
        mu.reg_write(UC_X86_REG_EAX, 0)
        mu.emu_start(FUNC, ret, count=50_000_000)
        lat, hd = [], []
        for p in range(self.N):
            b = SEG + p * SEGSZ
            lat.append(struct.unpack('<h', mu.mem_read(b + 0x16, 2))[0])
            hd.append(struct.unpack('<h', mu.mem_read(b + 0x18, 2))[0])
        end = mu.mem_read(STREAM, len(data))
        return lat, hd, bytes(end) == data, bytes(end)


def track_from_json(j, q):
    """Build the segment field table from the track JSON."""
    mg = q.split_groups(j['main_stream'])
    TT = q.read_track(mg, True)
    N = TT['N']
    ef = [c for c in mg[0]['cmds'] if c['cmd'] == 'EF'][0]['args']
    X = [q.d32(*TT['F6'][p][0:2]) for p in range(N)]
    Z = [q.d32(*TT['F6'][p][4:6]) for p in range(N)]
    hd = TT['hd']
    H = TT['H']
    HA = s32((j['track_header']['start_heading'] << 16) | (ef[0] & 0xFFFF))
    H0 = []
    for p in range(N):
        half = hd[p] >> 1
        HA = s32(HA + half)
        H0.append((HA >> 16) & 0xFFFF)
        HA = s32(HA + half)
    k = struct.unpack('<I', open(EXE, 'rb').read()[0:0] or b'\0\0\0\0')[0]
    c14 = []
    for p in range(N):
        d = s32(H[(p + 1) % N] - H[p]) >> 16
        c14.append((d * 0x6488) >> 14)
    return {'N': N, 'X': X, 'Z': Z, 'H0': H0, 'c14': c14, 'Wn': TT['Wn'], 'Wp': TT['Wp'], 'H': H, 'hd': hd}


"""Fit a racing line chain (exact game routine as oracle) to a target line on the reversed Interlagos."""



class Oracle:
    def __init__(self, T):
        self.T = T
        self.N = T['N']
        self.sim = Sim()
        self.sim.setup_track(T)
        self.mu = self.sim.mu
        self.calls = 0
        self.cache = {}

    def step(self, k, lat, A, n, R, cx=0, end_R=None):
        key = (k, lat, A, n, R, cx, end_R)
        if key in self.cache:
            return self.cache[key]
        T = self.T
        N = self.N
        fl = 0xD800 | (0x2000 if end_R is not None else 0)
        s1 = {'len': n, 'flags': '%04X' % fl, 'lateral': lat, 'heading': A & 0xFFFF, 'cx': cx, 'radius': R}
        if end_R is not None:
            s1['end_radius'] = end_R
        s2 = {'len': 1, 'flags': '5000', 'cx': 0, 'radius': 0}
        self.mu.mem_write(A_FIRST, struct.pack('<I', SEG + k * SEGSZ))
        try:
            lats, hds, same, end = self.sim.run_at(k, [s1, s2], n + 2)
        except Exception as e:
            self.cache[key] = None
            return None
        self.calls += 1
        stored = lats[:n]
        endlat = lats[n]
        endA = (T['H0'][k + n] + hds[n]) & 0xFFFF if k + n < N else None
        res = (stored, endlat, endA)
        self.cache[key] = res
        return res


def patch_sim():
    def run_at(self, k, secs, count):
        mu = self.mu
        import struct as st
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP, \
            UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EAX
        data = self.encode(secs)
        mu.mem_write(STREAM, data)
        for p in range(k, k + count + 1):
            mu.mem_write(SEG + p * SEGSZ + 0x16, b'\0\0\0\0')
        sp = STACK + 0x8000
        ret = 0x41000000
        if not hasattr(self, '_ret'):
            mu.mem_map(ret, 0x1000)
            self._ret = ret
        sp -= 4
        mu.mem_write(sp, st.pack('<I', ret))
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ESI, STREAM)
        for r in (UC_X86_REG_EDI, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EAX):
            mu.reg_write(r, 0)
        mu.emu_start(FUNC, ret, count=2_000_000)
        lat, hd = [], []
        for p in range(k, k + count):
            b = SEG + p * SEGSZ
            lat.append(st.unpack('<h', mu.mem_read(b + 0x16, 2))[0])
            hd.append(st.unpack('<h', mu.mem_read(b + 0x18, 2))[0])
        return lat, hd, True, b''
    Sim.run_at = run_at


patch_sim()





def reversed_json(j0):
    Q.anchored_line = lambda g, p, n, chain=True: ([{'len': LASTP, 'flags': '5000', 'cx': 0, 'radius': 0}], {})
    j1 = Q.reverse_json(j0)
    j1.pop('_line_report', None)
    return j1


def old_line(j0):
    T0 = track_from_json(j0, Q)
    sim = Sim()
    sim.setup_track(T0)
    lat, hd, _, _ = sim.run(j0['racing_line'])
    habs = [(T0['H0'][p] + hd[p]) & 0xFFFF for p in range(N)]
    # seg 883 is never written: interpolate
    lat[LASTP] = (lat[LASTP - 1] + lat[0]) / 2.0
    habs[LASTP] = (habs[LASTP - 1] + s16(habs[0] - habs[LASTP - 1]) // 2) & 0xFFFF
    return T0, lat, habs


def old_boundaries(j0):
    """Section starts of the original per position (mod 883, last writer wins)."""
    gov = [None] * LASTP
    k = 0
    for si, s in enumerate(j0['racing_line']):
        for jj in range(s['len']):
            gov[k % LASTP] = si
            k += 1
    starts = [p for p in range(LASTP) if gov[p] != gov[p - 1]]
    return starts, gov


def old_radius(j0):
    """Old radius at each position 0..882 (last writer wins, positions mod 883)."""
    R = [0] * LASTP
    k = 0
    for si, sc in enumerate(j0['racing_line']):
        r0 = sc['radius']
        st = 0
        if int(sc['flags'], 16) & 0x2000:
            st = int((sc['end_radius'] - r0) / sc['len'])
        for jj in range(sc['len']):
            R[k % LASTP] = r0 + jj * st if r0 else 0
            k += 1
    return R


def target_kappa(Rold):
    """New position j <-> old position N-j, radius sign flips."""
    K = [0.0] * N
    for j in range(N):
        p = (N - j) % N
        if p >= LASTP:
            p = LASTP - 1
        r = Rold[p]
        K[j] = (-1.0 / r) if r else 0.0
    return K


def targets(lat, habs):
    Lt, Ht = [], []
    for j in range(N):
        p = (N - j) % N
        Lt.append(-lat[p])
        Ht.append((habs[p] + 0x8000) & 0xFFFF)
    return Lt, Ht


def new_bounds(starts):
    b = set([0])
    for s in starts:
        e = (N - s + 1) % N
        if 0 <= e < LASTP:
            b.add(e)
    return sorted(b)


RGRID = [0] + [sg * v for v in (500, 700, 900, 1100, 1500, 2000, 2600, 3300, 4200, 5300, 6700, 8500, 10800, 13700, 17400, 22000, 28000, 35500,
                                45000, 57000, 72000, 91000, 115000, 145000, 185000, 235000, 300000, 400000, 600000, 1000000)
               for sg in (1, -1)]


def fit(O, T, Lt, Ht, bounds, Kt=None, mu=0.6, beam=6, lam=0.7, S=380.0, verbose=True):
    W = [min(T['Wn'][p], T['Wp'][p]) for p in range(N)]

    def cost_of(k, n, res, final, R=0):
        stored, endlat, endA = res
        c = 0.0
        for i, v in enumerate(stored):
            e = (v - Lt[k + i]) / S
            c += min(e * e, 25.0)
            lim = 0.85 * (T['Wn'][k + i] if v < 0 else T['Wp'][k + i])
            if abs(v) > lim:
                c += ((abs(v) - lim) / 100.0) ** 2
        if Kt is not None:
            kap = (1.0 / R) if R else 0.0
            ks = 1.0 / 20000.0
            pr = sum(((kap - Kt[k + i]) / ks) ** 2 for i in range(n)) / n
            c += mu * min(pr, 25.0) * (1.0 if n >= 3 else 0.3)
        if not final and endA is not None:
            e = (endlat - Lt[k + n]) / S
            c += 2.0 * min(e * e, 25.0)
            d = s16(endA - Ht[k + n]) / 450.0
            c += 2.0 * min(d * d, 25.0)
        return c + lam

    states = {0: [(0.0, [], Lt[0], Ht[0])]}
    keys = sorted(set([0]))
    pos = 0
    t0 = time.time()
    while True:
        ks = [k for k in states if k >= pos and k < LASTP and states[k]]
        if not ks:
            break
        k = min(ks)
        pos = k
        sts = sorted(states[k], key=lambda s: s[0])[:beam]
        states[k] = []
        variants = []
        for (c0, chain, lat, A) in sts:
            variants.append((c0, chain, lat, A, False))
            if k > 0 and (abs(lat - Lt[k]) > 500 or abs(s16(A - Ht[k])) > 1500):
                # Restart: section with start values (flags D800) directly on the target line
                variants.append((c0 + 6.0, chain, Lt[k], Ht[k], True))
        for (c0, chain, lat, A, reset) in variants:
            nb = [b for b in bounds if b > k]
            ends = set()
            if nb:
                e1 = nb[0]
                ends.add(min(e1, LASTP))
                if e1 - k >= 8:
                    ends.add((k + e1) // 2)
                if len(nb) > 1 and nb[1] - k <= 36:
                    ends.add(min(nb[1], LASTP))
            else:
                ends.add(LASTP)
            if min(ends) - k > 45:
                ends.add(k + 30)
            ends = sorted(e for e in ends if e > k and e <= LASTP)
            for e in ends:
                n = e - k
                final = (e >= LASTP)
                opts = []
                for R in RGRID:
                    res = O.step(k, lat, A, n, R)
                    if res is None:
                        continue
                    opts.append((cost_of(k, n, res, final, R), R, res))
                opts.sort(key=lambda t: t[0])
                top = opts[:3]
                # refine the best radii
                refined = []
                for (c, R, res) in top:
                    bestc, bestR, bestres = c, R, res
                    if R != 0:
                        for f in (0.7, 0.8, 0.88, 0.94, 0.97, 1.03, 1.06, 1.12, 1.25, 1.4):
                            R2 = int(R * f)
                            res2 = O.step(k, lat, A, n, R2)
                            if res2 is None:
                                continue
                            c2 = cost_of(k, n, res2, final, R2)
                            if c2 < bestc:
                                bestc, bestR, bestres = c2, R2, res2
                    refined.append((bestc, bestR, bestres))
                for (c, R, res) in refined:
                    stored, endlat, endA = res
                    nstate = (c0 + c, chain + [(k, n, R, reset)], endlat, endA if endA is not None else 0)
                    lst = states.setdefault(e, [])
                    lst.append(nstate)
                    # dedupe by rough state
                    seen = {}
                    for s in sorted(lst, key=lambda s: s[0]):
                        key = (int(s[2] // 70), int(s[3] // 160))
                        if key not in seen:
                            seen[key] = s
                    states[e] = list(seen.values())[:beam * 2]
        if verbose and k % 100 < 12:
            print('pos', k, 'states', len(sts), 'calls', O.calls, 'time', round(time.time() - t0))
    fin = sorted(states.get(LASTP, []), key=lambda s: s[0])
    return fin


def to_sections(chain, Lt0, Ht0, Lt_all=None, Ht_all=None):
    Lt0_at = lambda k: Lt_all[k]
    Ht0_at = lambda k: Ht_all[k]
    secs = []
    for idx, (k, n, R, reset) in enumerate(chain):
        s = {'len': n, 'flags': '5000', 'cx': 0, 'radius': R}
        if idx == 0:
            s = {'len': n, 'flags': 'D800', 'lateral': Lt0, 'heading': s16(Ht0), 'cx': 0, 'radius': R}
        elif reset:
            s = {'len': n, 'flags': 'D800', 'lateral': Lt0_at(k), 'heading': s16(Ht0_at(k)), 'cx': 0, 'radius': R}
        secs.append(s)
    return secs



def compute_line(j0, exe, core, mu=0.6, lam=1.5, beam=5, log=print):
    """j0: JSON of the ORIGINAL track (gp4track.dump). Returns (j1, sections, statistics) for the reversed track."""
    configure(exe, core, len(core.read_track(core.split_groups(j0['main_stream']), True)['hd']))
    j1 = reversed_json(j0)
    T1 = track_from_json(j1, Q)
    T0, lat0, habs0 = old_line(j0)
    Lt, Ht = targets(lat0, habs0)
    starts, gov = old_boundaries(j0)
    bounds = new_bounds(starts)
    Kt = target_kappa(old_radius(j0))
    O = Oracle(T1)
    t = time.time()
    fin = fit(O, T1, Lt, Ht, bounds, Kt=Kt, mu=mu, lam=lam, beam=beam, verbose=False)
    if not fin:
        raise RuntimeError('fit found no solution')
    best = fin[0]
    secs = to_sections(best[1], Lt[0], Ht[0], Lt, Ht)
    sim = Sim()
    sim.setup_track(T1)
    lat, hd, same, _ = sim.run(secs)
    err = [abs(lat[p] - Lt[p]) for p in range(LASTP)]
    bad = [p for p in range(LASTP) if abs(lat[p]) > (T1['Wn'][p] if lat[p] < 0 else T1['Wp'][p])]
    stats = {'sections': len(secs), 'segments': sum(s['len'] for s in secs), 'mean_error': sum(err) / len(err),
             'max_error': max(err), 'outside': bad, 'seconds': round(time.time() - t), 'stream_unchanged': same}
    return j1, secs, stats
