"""Page layout analysis: turns a PDF page into rows of styled spans, figure boxes and hard-math boxes.
Text is taken verbatim from the PDF text layer; only glyph encodings of the Fourier math fonts are remapped."""
import re, pymupdf

FIX = {'Fourier-Math-Symbols': {';': '∅', 'p': '√'},
       'Fourier-Math-Extension': {'©': '{', 'ª': '}', '¡': '(', '¢': ')', '£': '[', '¤': ']', '³': '(', '´': ')', 'µ': '(', '¶': ')'},
       'Fourier-Math-BlackBoard': dict(zip('CNQRZ', 'ℂℕℚℝℤ')), 'rsfs10': {'F': 'ℱ', 'P': '𝒫'}}
NEG = {'=': '≠', '∈': '∉', '⊆': '⊈', '⊂': '⊄', '⊇': '⊉', '⊃': '⊅', '≡': '≢', '|': '∤', '∃': '∄', '<': '≮', '>': '≯',
       '≤': '≰', '≥': '≱', '∼': '≁', '≈': '≉', '∣': '∤'}
TOP, BOTTOM = 75, 675          # running head above, footer below (PDF points)
MONO = re.compile(r'Mono|Courier|Consol|Code|Inconsolata|Menlo|Typewriter|CMTT|LMTT', re.I)   # code fonts; adapt per book


class Span:
    def __init__(self, s, slashes=()):
        self.font, self.size = s['font'], s['size']
        ch = [c for c in s['chars'] if c['c'].strip()] or s['chars']   # char boxes: span boxes can take the whole line's height
        self.x0, self.x1 = s['bbox'][0], s['bbox'][2]
        self.y0 = min(c['bbox'][1] for c in ch); self.y1 = max(c['bbox'][3] for c in ch)
        self.base = sorted(c['origin'][1] for c in ch)[len(ch) // 2]
        fix = FIX.get(self.font, {})
        def glyph(c):   # a zero-width U+0338 drawn at the same spot negates the symbol (≠, ∉, ...)
            g = fix.get(c['c'], c['c'])
            if g in NEG and any(abs(c['origin'][0] - x) < 0.6 and abs(c['origin'][1] - y) < 0.6 for x, y in slashes): return NEG[g]
            return g
        self.text = ''.join(glyph(c) for c in s['chars'] if c['c'] != '̸')
        self.hard = self.font == 'Fourier-Math-Extension' and any(c['c'] not in fix for c in s['chars'] if c['c'].strip())
        self.hard |= self.font == 'Fourier-Math-Symbols' and 'p' in ''.join(c['c'] for c in s['chars'])  # radical sign
        self.role = ''            # '', 'sup' or 'sub' (set per row)

    @property
    def prose(self): return self.font.startswith('TeXGyreSchola')
    @property
    def mono(self): return bool(MONO.search(self.font))   # code font (coding books)
    @property
    def bold(self): return 'Bold' in self.font
    @property
    def italic(self): return self.font.endswith('Italic')
    @property
    def mathital(self): return self.font in ('CenturySchL-Ital', 'Fourier-Math-Letters-Ita')
    def rect(self): return pymupdf.Rect(self.x0, self.y0, self.x1, self.y1)


class Row:
    def __init__(self, spans):
        self.spans = sorted(spans, key=lambda s: s.x0)
        normal = [s for s in self.spans if s.size >= 9] or self.spans
        self.base = max(set(round(s.base) for s in normal), key=lambda b: sum(1 for s in normal if round(s.base) == b))
        self.size = max(s.size for s in normal)
        self.x0 = min(s.x0 for s in self.spans); self.x1 = max(s.x1 for s in self.spans)
        self.y0 = min(s.y0 for s in normal); self.y1 = max(s.y1 for s in normal)
        for s in self.spans:
            if s.size < 0.85 * self.size and not s.hard:
                s.role = 'sup' if s.base < self.base - 1.5 else 'sub' if s.base > self.base + 1.5 else ''
        self.items = []           # filled by page analysis: ('span', Span) | ('math', Rect)

    def text(self): return ''.join(s.text for s in self.spans)


def page_spans(page):
    slashes = [(ch[2][0], ch[2][1]) for sp in page.get_texttrace() for ch in sp['chars'] if ch[0] == 0x338]
    out = []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                if s['chars'] and TOP <= s['bbox'][1] <= BOTTOM:   # keep space-only spans: they are the word gaps
                    out.append(Span(s, slashes))
    return out


def figure_boxes(page, spans):
    """Clusters of vector drawings (and raster images) that are real figures, grown to include their text labels."""
    rects = []
    for d in page.get_drawings():
        r = pymupdf.Rect(d['rect'])
        if r.x0 < -2 or r.y0 < -2 or r.x1 > page.rect.x1 + 2 or r.y1 > page.rect.y1 + 2 or (r.width < 0.5 and r.height < 0.5): continue
        if r.y0 < TOP or r.y1 > BOTTOM + 5: continue
        if r.height < 1.2 and (r.width > 250 or r.width < 30): continue   # full-width rules; fraction bars are math
        rects.append(r + (-0.5 * (r.width < 1), -0.5 * (r.height < 1), 0.5 * (r.width < 1), 0.5 * (r.height < 1)))  # strokes have no area
    rects += [pymupdf.Rect(b['bbox']) for b in page.get_text('dict')['blocks'] if b['type'] == 1 and TOP < b['bbox'][1] < BOTTOM]
    clusters = []                                              # [unpadded box, item count]
    for r in rects:
        hit = [c for c in clusters if (c[0] + (-8, -8, 8, 8)).intersects(r + (-8, -8, 8, 8))]
        box, n = pymupdf.Rect(r), 1
        for c in hit: clusters.remove(c); box |= c[0]; n += c[1]
        clusters.append([box, n])
    figs = []
    for box, n in clusters:
        if box.height < 2 or box.width < 2: continue          # bars / underlines: handled as math
        for _ in range(2):                                     # absorb labels touching the drawing
            for s in spans:
                r = s.rect()
                near = (r & (box + (-6, -6, 6, 6))).get_area() > 0.5 * r.get_area() and r.width < 120
                if near or (r.width < 40 and s.text.strip() and (box + (-10, -10, 10, 10)).contains(r)):
                    box |= r
        prose = sum(len(s.text.strip()) for s in spans if s.prose and box.contains(s.rect()))
        if prose > 40: continue                                # a frame drawn around text (boxed outline/fact), not a figure
        figs.append(box + (-2, -2, 2, 2))
    return figs


def build_rows(spans):
    """Rows are defined by normal-size text baselines; small spans (scripts, fraction parts, matrix entries)
    join the nearest baseline; big delimiters join the row they overlap most."""
    ext = [s for s in spans if s.font == 'Fourier-Math-Extension' or (s.hard and '√' in s.text)]  # glyph boxes lie; place by position
    small = [s for s in spans if s not in ext and (s.size < 8.5 or not s.text.strip())]
    giant = [s for s in spans if s.size > 20]                 # drop caps
    normal = [s for s in spans if s not in ext and s not in small and s not in giant]
    rows = []                                                  # [base, y0, y1, spans]
    for s in sorted(normal, key=lambda s: s.base):
        if rows and abs(s.base - rows[-1][0]) < 3:
            r = rows[-1]; r[3].append(s); r[1] = min(r[1], s.y0); r[2] = max(r[2], s.y1)
        else:
            rows.append([s.base, s.y0, s.y1, [s]])
    for s in small:
        best = min(rows, key=lambda r: abs(r[0] - s.base), default=None)
        if best is not None and abs(best[0] - s.base) < 8: best[3].append(s)
        elif s.text.strip(): rows.append([s.base, s.y0, s.y1, [s]])
    for s in ext:
        best = max(rows, key=lambda r: min(s.y1, r[2]) - max(s.y0, r[1]), default=None)
        if rows and '√' in s.text:                            # radical glyph box sits above its ink: take the row below
            min(rows, key=lambda r: abs(r[1] - s.y1))[3].append(s)
        elif best is not None and min(s.y1, best[2]) - max(s.y0, best[1]) > 0: best[3].append(s)
        else: rows.append([s.base, s.y0, s.y1, [s]])
    rows += [[s.base, s.y0, s.y1, [s]] for s in giant]
    return [Row(r[3]) for r in sorted(rows, key=lambda r: r[1]) if ''.join(x.text for x in r[3]).strip()]


def hard_math(row, bars):
    """Find regions of a row that plain text can't express: stacked spans (fractions, matrices, binomials),
    unmapped big delimiters, radicals, and anything touching a fraction bar. Returns merged rects."""
    ms = [s for s in row.spans if not s.prose]
    seeds = [s.rect() for s in ms if s.hard]
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            if min(a.x1, b.x1) - max(a.x0, b.x0) > 1.5 and abs(a.base - b.base) > 3 and (a.size < 9 or b.size < 9) \
                    and a.text.strip() and b.text.strip():
                seeds.append(a.rect() | b.rect())
    for bar in bars:
        if row.y0 - 6 < bar.y0 < row.y1 + 4:
            box = bar + (0, -0.6, 0, 0.6)                      # bars are zero-height; give them area
            for s in ms:                                       # what sits directly on or under the bar belongs to it
                ov = min(s.x1, bar.x1) - max(s.x0, bar.x0)
                if s.text.strip() and ov > 0.5 * (s.x1 - s.x0) and (abs(s.y0 - bar.y1) < 3 or abs(bar.y0 - s.y1) < 3):
                    box |= s.rect()
            seeds.append(box)
    boxes = []
    for r in seeds:                                            # grow over touching math spans (not prose)
        r = pymupdf.Rect(r)
        for _ in range(3):
            for s in ms:
                if (s.rect() + (-1.5, -2, 1.5, 2)).intersects(r) and (s.size < 9 or s.hard or s.font == 'Fourier-Math-Extension'):
                    r |= s.rect()
        for i, b in enumerate(boxes):
            if (b + (-1, -1, 1, 1)).intersects(r): boxes[i] = b | r; break
        else: boxes.append(r)
    return boxes


def analyse(page):
    spans = page_spans(page)
    figs = figure_boxes(page, spans)
    in_fig = lambda s: any((s.rect() & f).get_area() > 0.5 * s.rect().get_area() for f in figs)
    text_spans = [s for s in spans if not in_fig(s)]
    bars = [pymupdf.Rect(d['rect']) for d in page.get_drawings()
            if d['rect'].height < 1.2 and d['rect'].width < 250 and not any(pymupdf.Rect(d['rect']).intersects(f) for f in figs)]
    rows = build_rows(text_spans)
    # small drawings sitting inside a text line (e.g. dice faces in a sentence) are inline math, not block figures
    inline = [f for f in figs if f.height < 28 and any(r.y0 - 4 < (f.y0 + f.y1) / 2 < r.y1 + 4 and r.x0 - 5 < f.x0 < r.x1 + 5 for r in rows)]
    figs = [f for f in figs if f not in inline and f.width > 10 and f.height > 10]   # drop stray frame lines
    owner = {i: min(rows, key=lambda r: abs((r.y0 + r.y1) / 2 - b.y0)) for i, b in enumerate(bars)} if rows else {}
    for row in rows:
        boxes = hard_math(row, [b for i, b in enumerate(bars) if owner[i] is row]) + [f for f in inline if row.y0 - 4 < (f.y0 + f.y1) / 2 < row.y1 + 4]
        placed, used, last = [], set(), None
        for s in row.spans:
            box = next((b for b in boxes if (s.rect() & b).get_area() > 0.5 * max(s.rect().get_area(), 0.01)), None)
            if box is None: placed.append((s.x0, 'span', s))
            elif id(box) not in used: used.add(id(box)); placed.append((box.x0, 'math', box + (-0.8, -0.8, 0.8, 0.8)))
        placed += [(b.x0, 'math', b) for b in boxes if id(b) not in used and b in inline]
        for x0, kind, v in sorted(placed, key=lambda t: t[0]):
            if last is not None and x0 - last[0] > 1.2 and not last[1].endswith(' ') and not (kind == 'span' and v.text.startswith(' ')):
                row.items.append(('space', None))                # word gap encoded as positioning, not a space glyph
            row.items.append((kind, v))
            last = (v.x1, v.text if kind == 'span' else 'm')
    return rows, figs


_VOCAB = None


def vocab():
    """Words (and hyphenated compounds) the book uses mid-line; decides how to rejoin a word broken at a line end."""
    global _VOCAB
    if _VOCAB is None:
        import re, json, pathlib
        cache = pathlib.Path(__file__).resolve().parent.parent / 'work' / 'vocab.json'
        if cache.exists():
            _VOCAB = set(json.loads(cache.read_text(encoding='utf-8')))
        else:
            doc = pymupdf.open(cache.parent / 'Main.pdf'); words = set()
            for p in doc:
                for line in p.get_text().splitlines():
                    toks = line.split()
                    for t in toks[:-1] if line.rstrip().endswith('-') else toks:
                        words.add(re.sub(r"[^\w\-']", '', t).lower())
            _VOCAB = words
            cache.write_text(json.dumps(sorted(words)), encoding='utf-8')
    return _VOCAB


def rejoin(left, right):
    """left ends with '-' at a line break. Keep the hyphen for real compounds, drop it for TeX hyphenation."""
    import re
    a = re.findall(r"[\w']+-$", left); b = re.findall(r"^[\w']+", right)
    if not a or not b: return left[:-1] + right if left.endswith('-') else left + right
    v = vocab(); joined, compound = (a[0][:-1] + b[0]).lower(), (a[0] + b[0]).lower()
    left_w, right_w = a[0][:-1].lower(), b[0].lower()
    keep = joined not in v and (compound in v or (left_w in v and right_w in v and len(right_w) > 2))  # e.g. "or-equal" 
    return (left if keep else left[:-1]) + right
