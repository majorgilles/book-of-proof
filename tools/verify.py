"""Verbatim check: prose words (TeX Gyre Schola text fonts) from the PDF pages vs visible text of a content file.
  python tools/verify.py content/ch01.html      (file must start with <!-- pages: A-B -->, 0-based PDF indices)
Text inside figures and math crops is excluded (those are exact images); the report says how much that is.
Exit 1 if any prose word run is missing or any extra prose run was inserted."""
import pymupdf, re, sys, os, html, difflib
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout import analyse, page_spans, rejoin

LIG = {'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl', '’': "'", '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-'}


MATHWORDS = {'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'log', 'exp', 'max', 'min', 'lim', 'mod', 'gcd', 'lcm', 'det', 'arctan', 'arcsin'}


def norm(t):
    for a, b in LIG.items(): t = t.replace(a, b)
    t = re.sub(r'[-—–]', ' ', re.sub(r'\d', '', t))            # digits are math; dashes split words
    return [w for w in (re.sub(r"[^\w']", '', x).lower() for x in t.split()) if w and w not in MATHWORDS]


def pdf_words(a, b, skip=()):
    """Returns (body words in reading order, [word list per exercise block], prose chars inside crops)."""
    d = pymupdf.open('work/Main.pdf'); parts, cropped = [[]], 0   # parts[0] = body lines, parts[1:] = exercise blocks
    cur = parts[0]
    for i in (p for p in range(a, b + 1) if p not in skip):
        rows, figs = analyse(d[i])
        allp = sum(len(s.text.replace(' ', '')) for s in page_spans(d[i]) if s.prose)
        for r in rows:
            t = ''.join(v.text if k == 'span' and v.prose else ' ' for k, v in r.items).strip()
            first = next((v for k, v in r.items if k == 'span' and v.text.strip()), None)
            if first and first.bold and t.startswith('Exercises for'): parts.append([]); cur = parts[-1]
            elif first and (first.bold and re.match(r'\d+\.\d+\s', t) and r.size > 10.5 or r.size >= 13): cur = parts[0]
            if t and cur and len(cur[-1]) == 1 and cur[-1].isupper() and cur is parts[0]: cur[-1] += t   # drop cap
            elif t: cur.append(t)
        cropped += allp - sum(len(''.join(v.text for k, v in r.items if k == 'span' and v.prose).replace(' ', '')) for r in rows)
    def dehyph(ls):                                   # undo end-of-line hyphenation the same way the converter does
        out = []
        for l in ls:
            if out and out[-1].endswith('-'): out[-1] = rejoin(out[-1], l)
            else: out.append(l)
        return norm('\n'.join(out))
    return dehyph(parts[0]), [dehyph(p) for p in parts[1:]], cropped


def html_words(src):
    src = re.sub(r'<(script|style|svg)\b.*?</\1>', ' ', src, flags=re.S)
    src = re.sub(r'<i>.*?</i>', ' ', src, flags=re.S)   # math italic letters: math fonts are excluded on the PDF side too
    src = re.sub(r'\\\(.*?\\\)|\\\[.*?\\\]', ' ', src, flags=re.S)  # MathJax math is not prose
    blocks = re.findall(r'<div class="exercises".*?</ol>\s*</div>', src, flags=re.S)
    body = re.sub(r'<div class="exercises".*?</ol>\s*</div>', ' ', src, flags=re.S)
    words = lambda s: norm(html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'</?(strong|em|sup|sub)>', '', s))))  # inline tags are zero-width
    return words(body), [words(x) for x in blocks]


if __name__ == '__main__':
    f = sys.argv[1]; src = open(f, encoding='utf-8').read()
    a, b = map(int, re.search(r'<!-- pages: (\d+)-(\d+) -->', src).groups())
    m = re.search(r'<!-- skip: (\d+)-(\d+) -->', src)
    P, PX, cropped = pdf_words(a, b, range(int(m.group(1)), int(m.group(2)) + 1) if m else ())
    H, HX = html_words(src)
    bad = 0
    if len(PX) != len(HX):
        bad += 1; print(f'[blocks] PDF has {len(PX)} exercise blocks, HTML has {len(HX)}')
    for k, (p, h) in enumerate(zip(PX, HX)):          # exercise order legitimately differs (columns): compare as multisets
        cp, ch = Counter(w for w in p if re.search(r'[a-z]{3,}', w)), Counter(w for w in h if re.search(r'[a-z]{3,}', w))
        if cp != ch:
            bad += 1; print(f'[exercise block {k + 1}] missing: {dict(cp - ch)} extra: {dict(ch - cp)}')
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, P, H, autojunk=False).get_opcodes():
        if op == 'equal': continue
        miss, extra = ' '.join(P[i1:i2]), ' '.join(H[j1:j2])
        if not re.search(r'[a-z]{3,}', miss + ' ' + extra): continue   # math letters/numbers: noise
        bad += 1; ctx = ' '.join(P[max(0, i1 - 5):i1])
        print(f'[{op}] ...{ctx} | PDF: "{miss[:120]}" | HTML: "{extra[:120]}"')
    print(f'{f}: {len(P)} prose words in PDF, {len(H)} in HTML, {bad} discrepancies; {cropped} prose chars inside figure/math crops')
    sys.exit(1 if bad else 0)
