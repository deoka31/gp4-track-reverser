#!/usr/bin/env python3
"""GP4 track reverser: turns a Grand Prix 4 track so that it is driven in the other direction.

Examples (run inside the tool folder, which may sit anywhere below the GP4 folder):
    python umkehren.py 03            Interlagos (Circuits\\S1CT03o.DAT or S1CT03.DAT) -> Umgekehrt\\S1CT03.DAT
    python umkehren.py 01 05 12      several tracks
    python umkehren.py alle          all 17 original tracks ("alle" = all)
    python umkehren.py C:\\mod\\S1CT21.DAT     any track file (the racing line is then computed, needs unicorn)

Options:
    --gp4 FOLDER    GP4 folder containing Circuits\\ (default: searched above this folder)
    --out FOLDER    output folder (default: .\\Umgekehrt)

The output is never written to the Circuits folder. For the 17 original tracks the racing line comes ready-made from
the folder Rennlinien\\. For other tracks (mods) it is computed: this needs "pip install unicorn" and GP4.exe.
"""
import sys, os, json, glob, hashlib, argparse
sys.dont_write_bytecode = True
__version__ = '0.9.0-beta'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gp4track as gt
import GP4_InterlagosRueckwaerts_Quellcode as q

# The old approximate racing line of the source module is not used (it crashed the game); a placeholder is built and
# replaced by the exactly fitted line afterwards.
q.anchored_line = lambda g, p, N, chain=True: ([{'len': N - 1, 'flags': '5000', 'cx': 0, 'radius': 0}], {})


def find_gp4():
    d = HERE
    for _ in range(5):
        if os.path.isdir(os.path.join(d, 'Circuits')):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(HERE, '..'))


def find_source(gp4, key):
    """key: '03' or a file path -> path of the source file"""
    if os.path.isfile(key):
        return key
    nn = key.zfill(2)
    cdir = os.path.join(gp4, 'Circuits')
    # 'o' = untouched original variant (in case someone changed the normal file by hand)
    for nm in ('S1CT%so.DAT' % nn, 'S1CT%s.DAT' % nn):
        p = os.path.join(cdir, nm)
        if os.path.isfile(p):
            return p
    return None


def load_line(raw, key):
    p = os.path.join(HERE, 'Rennlinien', 'S1CT%s.json' % os.path.basename(key)[4:6])
    if not os.path.isfile(p):
        return None
    d = json.load(open(p))
    if d.get('source_sha1') == hashlib.sha1(raw).hexdigest():
        return d['racing_line']
    return None


def reverse_one(src, gp4, outdir):
    raw = open(src, 'rb').read()
    name = os.path.basename(src)
    j0 = gt.dump(raw)
    if gt.build(json.loads(json.dumps(j0))) != raw:
        print('  ERROR: the file cannot be rebuilt byte-identically - skipped')
        return False
    j1 = q.reverse_json(j0)
    j1.pop('_line_report', None)
    secs = load_line(raw, name)
    how = 'ready-made from Rennlinien\\'
    if secs is None:
        try:
            import umkehren_linie as U
            exe = os.path.join(gp4, 'GP4.exe')
            if not os.path.isfile(exe):
                raise FileNotFoundError(exe)
            print('  Computing the racing line (a few minutes) ...')
            _, secs, st = U.compute_line(j0, exe, q)
            how = 'computed (%d sections, mean deviation %.0f, outside the track: %d segments)' % (
                st['abschnitte'], st['fehler_mittel'], len(st['ausserhalb']))
        except ImportError:
            print('  No ready-made racing line for this file and "unicorn" is missing (pip install unicorn).')
            print('  Without a matching racing line the game would crash - file not written.')
            return False
        except FileNotFoundError as e:
            print('  GP4.exe not found: %s (use --gp4) - file not written.' % e)
            return False
    j1['racing_line'] = secs
    out = gt.build(j1)
    if gt.build(gt.dump(out)) != out:
        print('  ERROR: the result cannot be rebuilt stably')
        return False
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, 'S1CT%s.DAT' % name[4:6])
    if os.path.basename(os.path.dirname(os.path.abspath(dst))).lower() == 'circuits':
        print('  Aborted: writing into "Circuits" is blocked.')
        return False
    open(dst, 'wb').write(out)
    print('  -> %s (%d bytes), racing line: %s' % (dst, len(out), how))
    return True


def main(argv):
    ap = argparse.ArgumentParser(description='GP4 track reverser %s' % __version__)
    ap.add_argument('strecken', nargs='+', help='track numbers (03), "alle" (= all) or file paths')
    ap.add_argument('--gp4', default=find_gp4())
    ap.add_argument('--out', default=os.path.join(HERE, 'Umgekehrt'))
    ap.add_argument('--version', action='version', version=__version__)
    a = ap.parse_args(argv[1:])
    print('GP4 track reverser %s' % __version__)
    keys = []
    for s in a.strecken:
        keys += ['%02d' % i for i in range(1, 18)] if s.lower() == 'alle' else [s]
    ok = 0
    for k in keys:
        src = find_source(a.gp4, k)
        print('Track %s: %s' % (k, src))
        if src is None:
            print('  not found')
            continue
        ok += bool(reverse_one(src, a.gp4, a.out))
    print('%d of %d tracks written -> %s' % (ok, len(keys), a.out))
    return 0 if ok == len(keys) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
