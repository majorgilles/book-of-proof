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


def signature(s):
    """Digits and latin letters, the part of a formula a transcription must preserve."""
    s = re.sub(r'\\(?:mathbb|mathscr|mathcal|mathrm|text|operatorname)\{', '{', s)
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)                        # other commands (\frac, \sqrt, \pi ...) carry no digits/letters
    return collections.Counter(c for c in s if c.isdigit() or c.isascii() and c.isalpha())


def load_latex():
    out = {}
    for f in sorted(LATEX.glob('*.json')):
        out.update(json.loads(f.read_text(encoding='utf-8')))
    return out


def check():
    items = {i['id']: i for f in CROPS.glob('batch_*.json') for i in json.loads(f.read_text(encoding='utf-8'))}
    tex = load_latex()
    missing = [i for i in items if i not in tex]
    bad = []
    for i, t in tex.items():
        tl = re.sub(r'[ℕℤℚℝℂ]', lambda c: {'ℕ': 'N', 'ℤ': 'Z', 'ℚ': 'Q', 'ℝ': 'R', 'ℂ': 'C'}[c.group()], items.get(i, {}).get('text_layer', ''))
        if signature(tl) - signature(t):                        # text layer has digits/letters the LaTeX lacks
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
            if h in tex and h not in failed and tex[h].strip():
                n += 1
                return '\\(' + html.escape(tex[h].strip(), quote=False) + '\\)'
            kept += 1
            return m.group(0)
        f.write_text(IMG.sub(sub, src), encoding='utf-8')
    print(f'replaced {n} crops with LaTeX, kept {kept} as exact images')


if __name__ == '__main__':
    cmd = sys.argv[1]
    export(int(sys.argv[2]) if len(sys.argv) > 2 else 100) if cmd == 'export' else check() if cmd == 'check' else apply()
