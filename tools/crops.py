"""Math-crop -> LaTeX pipeline.
  python tools/crops.py export [batch_size]   render every inline math crop to work/crops/*.png, dedupe, write work/crops/batch_NN.json
  python tools/crops.py check                 sanity-check work/latex/*.json against the PDF text layer of each crop
  python tools/crops.py apply                 replace crops in content/*.html with \\( latex \\) where a checked transcription exists
Only short formula snippets go through transcription; prose is never touched."""
import sys, re, json, hashlib, html, pathlib, collections, pymupdf

ROOT = pathlib.Path(__file__).resolve().parent.parent
CROPS, LATEX = ROOT / 'work/crops', ROOT / 'work/latex'
IMG = re.compile(r'<img class="m" src="[^"]+" alt="([^"]*)" data-crop="(\d+):([\d.]+),([\d.]+),([\d.]+),([\d.]+)"[^>]*>')


def all_crops():
    for f in sorted((ROOT / 'content').glob('*.html')):
        for m in IMG.finditer(f.read_text(encoding='utf-8')):
            yield f, m


def key(m):
    return f'{m.group(2)}:{m.group(3)},{m.group(4)},{m.group(5)},{m.group(6)}'


def export(size):
    CROPS.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(ROOT / 'work/Main.pdf')
    by_hash, keys = {}, {}
    for f, m in all_crops():
        k = key(m)
        if k in keys: continue
        pno, r = int(m.group(2)), pymupdf.Rect(*map(float, m.groups()[2:6]))
        png = doc[pno].get_pixmap(dpi=300, clip=r).tobytes('png')
        h = hashlib.sha1(png).hexdigest()[:16]
        keys[k] = h
        if h not in by_hash:
            (CROPS / f'{h}.png').write_bytes(png)
            by_hash[h] = {'id': h, 'png': str(CROPS / f'{h}.png'), 'text_layer': html.unescape(m.group(1))}
    (CROPS / 'keys.json').write_text(json.dumps(keys), encoding='utf-8')
    items = list(by_hash.values())
    for i in range(0, len(items), size):
        (CROPS / f'batch_{i // size:02d}.json').write_text(json.dumps(items[i:i + size], ensure_ascii=False, indent=0), encoding='utf-8')
    print(f'{len(keys)} crops, {len(items)} unique images, {(len(items) + size - 1) // size} batches of {size}')


NAMED = r'\\(lim|log|ln|sin|cos|tan|cot|sec|csc|exp|max|min|gcd|lcm|mod|bmod|pmod|det|inf|sup|arctan|arcsin)(?![a-zA-Z])'


def signature(s):
    """Digits, latin letters and blackboard letters: the part of a formula a transcription must preserve."""
    bb = collections.Counter('bb' + c for c in re.findall(r'\\mathbb\{([A-Z])\}', s))
    bb += collections.Counter('bb' + {'ℕ': 'N', 'ℤ': 'Z', 'ℚ': 'Q', 'ℝ': 'R', 'ℂ': 'C'}[c] for c in re.findall('[ℕℤℚℝℂ]', s))
    s = re.sub(r'\\mathbb\{[A-Z]\}', ' ', s)
    s = re.sub(r'\\(?:mathscr|mathcal|mathrm|text|operatorname)\{', '{', s)
    s = re.sub(NAMED, lambda m: ' ' + m.group(1).replace('bmod', 'mod').replace('pmod', 'mod') + ' ', s)
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)                        # other commands (\frac, \sqrt, \pi ...) carry no digits/letters
    return bb + collections.Counter(c for c in s if c.isdigit() or c.isascii() and c.isalpha())


def load_latex():
    out = {}
    for f in sorted(LATEX.glob('batch_*.json')):             # agents' outputs (whole batches or parts)
        d = json.loads(f.read_text(encoding='utf-8'))
        if isinstance(d, dict): out.update(d)
    return out


def check():
    items = {i['id']: i for f in CROPS.glob('batch_*.json') for i in json.loads(f.read_text(encoding='utf-8'))}
    # re-read each crop's characters with fonts: Fourier big operators/radicals are encoded as Latin letters (P X R Y p ...)
    sys.path.insert(0, str(ROOT / 'tools')); from layout import page_spans
    doc, spans_by_page = pymupdf.open(ROOT / 'work/Main.pdf'), {}
    for k, h in json.loads((CROPS / 'keys.json').read_text(encoding='utf-8')).items():
        if h not in items or 'clean' in items[h]: continue
        pno, box = int(k.split(':')[0]), pymupdf.Rect(*map(float, k.split(':')[1].split(',')))
        sp = spans_by_page.setdefault(pno, page_spans(doc[pno]))
        items[h]['clean'] = ''.join(s.text for s in sp if not s.hard and s.font != 'Fourier-Math-Extension'
                                    and (s.rect() & box).get_area() > 0.5 * max(s.rect().get_area(), .01))
    for i in items.values(): i['text_layer'] = i.get('clean', i['text_layer'])
    tex = load_latex()
    missing = [i for i in items if i not in tex]
    bad = []
    for i, t in tex.items():
        if not t: continue                                      # null = fragment, stays an exact image
        tl = items.get(i, {}).get('text_layer', '')
        if signature(tl) - signature(t) or signature(t) - signature(tl):   # omitted or invented digits/letters
            bad.append((i, tl, t))
    print(f'{len(tex)} transcribed, {len(missing)} missing, {len(bad)} failing the digit/letter check')
    for b in bad[:40]: print('  ', b)
    (LATEX / 'failed.json').write_text(json.dumps([b[0] for b in bad]), encoding='utf-8')


def apply():
    keys = json.loads((CROPS / 'keys.json').read_text(encoding='utf-8'))
    tex = load_latex()
    failed = set(json.loads((LATEX / 'failed.json').read_text(encoding='utf-8'))) if (LATEX / 'failed.json').exists() else set()
    n = kept = 0
    for f in sorted((ROOT / 'content').glob('*.html')):
        src = f.read_text(encoding='utf-8')
        def sub(m):
            nonlocal n, kept
            h = keys.get(key(m))
            if h in tex and h not in failed and (tex[h] or "").strip():
                n += 1
                return '\\(' + html.escape(tex[h].strip(), quote=False) + '\\)'
            kept += 1
            return m.group(0)
        f.write_text(IMG.sub(sub, src), encoding='utf-8')
    used = {m for f in (ROOT / 'content').glob('*.html') for m in re.findall(r'src="(figs/m/[^"]+)"', f.read_text(encoding='utf-8'))}
    stale = [p for p in (ROOT / 'site/figs/m').glob('*.svg') if f'figs/m/{p.name}' not in used]
    for p in stale: p.unlink()                                 # crops replaced by LaTeX are not published
    print(f'replaced {n} crops with LaTeX, kept {kept} as exact images, removed {len(stale)} unused crop files')


if __name__ == '__main__':
    cmd = sys.argv[1]
    export(int(sys.argv[2]) if len(sys.argv) > 2 else 100) if cmd == 'export' else check() if cmd == 'check' else apply()
