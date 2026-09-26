"""Deterministic PDF -> HTML converter. Prose comes verbatim from the PDF text layer (never retyped);
figures and hard math become exact SVG crops.
  python tools/convert.py ch01 14 44 [skip-first skip-last]"""
import os, sys, re, html, pathlib, pymupdf
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from layout import analyse, rejoin

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDF = pymupdf.open(os.environ.get('BOOK_PDF', ROOT / 'work/Main.pdf'))   # BOOK_PDF overrides (tests)
LABELS = ('Definition', 'Theorem', 'Proposition', 'Lemma', 'Corollary', 'Example', 'Fact')
NUM = re.compile(r'^(\d+)\.$')
CODE_LANG = 'python'   # language of code blocks in a coding book: python | javascript | sql | other (display only)


def crop(pno, r, path):
    """Exact vector crop of page region r, with everything outside removed so the SVG stays small."""
    tmp = pymupdf.open(); tmp.insert_pdf(PDF, from_page=pno, to_page=pno)
    p = tmp[0]; M = p.rect; r = r & M
    for a in [(0, 0, M.x1, r.y0), (0, r.y1, M.x1, M.y1), (0, r.y0, r.x0, r.y1), (r.x1, r.y0, M.x1, r.y1)]:
        p.add_redact_annot(pymupdf.Rect(a))
    p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_REMOVE, graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                       text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    p.set_cropbox(r)
    (ROOT / 'site' / path).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / 'site' / path).write_text(p.get_svg_image(text_as_path=True), encoding='utf-8')
    return r


class Conv:
    def __init__(self, slug):
        self.slug, self.n = slug, 0

    def math_img(self, pno, r, row, alt):
        self.n += 1
        path = f'figs/m/{self.slug}-{self.n:04d}.svg'
        r = crop(pno, r, path)
        drop = max(0.0, r.y1 - row.base)
        return (f'<img class="m" src="{path}" alt="{html.escape(alt, quote=True)}" data-crop="{pno}:{r.x0:.1f},{r.y0:.1f},{r.x1:.1f},{r.y1:.1f}" '
                f'style="height:{r.height:.1f}pt;vertical-align:-{drop:.1f}pt">')

    def figure(self, pno, r):
        self.n += 1
        path = f'figs/{self.slug}-{self.n:04d}.svg'
        r = crop(pno, r, path)
        return f'<figure><img src="{path}" alt="Figure" style="width:{r.width:.0f}pt"></figure>'

    def inline(self, pno, row, items=None):
        """Render row items to inline HTML, merging runs of the same style."""
        out, cur, buf = [], None, []
        def flush():
            if not buf: return
            t = html.escape(''.join(buf), quote=False)
            tags = {'b': 'strong', 'i': 'em', 'v': 'i', 'sup': 'sup', 'sub': 'sub'}
            for k in (cur or ()):
                t = f'<{tags[k]}>{t}</{tags[k]}>'
            out.append(t); buf.clear()
        for kind, v in (items if items is not None else row.items):
            if kind == 'space': style, text = cur, ' '
            elif kind == 'math':
                flush(); cur = None
                alt = ''.join(s.text for s in row.spans if (s.rect() & v).get_area() > 0.5 * max(s.rect().get_area(), .01))
                out.append(self.math_img(pno, v, row, alt.strip())); continue
            else:
                style = tuple(k for k, on in (('b', v.bold), ('i', v.italic), ('v', v.mathital), (v.role, bool(v.role))) if on)
                text = v.text
                if not text.strip(): style = cur              # spaces never change style
            if style != cur: flush(); cur = style
            buf.append(text)
        flush()
        return ''.join(out)


def add(pieces, piece):
    """Append a line's HTML, rejoining a word hyphenated across the line break."""
    m = re.search(r'(?<![\s>])-((?:</\w+>)*)$', pieces[-1]) if pieces else None   # hyphen, maybe before closing tags
    if not m:
        pieces.append(piece); return
    core, closers = pieces[-1][:m.start()], m.group(1)
    keep = rejoin(re.sub(r'<[^>]+>', '', core) + '-', re.sub(r'<[^>]+>', '', piece)).endswith('-' + re.sub(r'<[^>]+>', '', piece))
    pieces[-1] = core + ('-' if keep else '') + closers + piece


def first_text(row):
    return next((v for k, v in row.items if k == 'span' and v.text.strip()), None)


def flow(slug, a, b, skip=()):
    """Yield (kind, pno, obj) in reading order across the page range."""
    for pno in (p for p in range(a, b + 1) if p not in skip):
        rows, figs = analyse(PDF[pno])
        left = 54 if pno % 2 else 79                           # the book alternates margins by page parity
        els = [('row', r.y0, r) for r in rows] + [('fig', f.y0, f) for f in figs]
        for kind, _, obj in sorted(els, key=lambda e: e[1]):
            yield kind, pno, obj, left


def convert(slug, a, b, skip=(), solutions=False):
    C = Conv(slug)
    out = [f'<!-- pages: {a}-{b} -->'] + ([f'<!-- skip: {skip[0]}-{skip[-1]} -->'] if skip else [])
    para, para_cls = [], ''
    stack = []                     # open <section> tags
    ex = None                      # exercise-block state
    last_row_y = None

    code_buf = []

    def code_html(lines):
        x0 = min(x for x, _, _ in lines)
        body = '\n'.join(' ' * round((x - x0) / cw) + t.rstrip() for x, cw, t in lines)   # indentation from x offsets
        return f'<pre class="code" data-lang="{CODE_LANG}"><code>{html.escape(body)}</code></pre>'

    def flush_code():
        if code_buf: out.append(code_html(code_buf)); code_buf.clear()

    def close_para():
        nonlocal para, para_cls
        flush_code()
        if para:
            cls = f' class="{para_cls}"' if para_cls else ''
            out.append(f'<p{cls}>' + ' '.join(para).replace('  ', ' ') + '</p>')
        para, para_cls = [], ''

    def close_ex():
        nonlocal ex
        if not ex: return
        items = sorted(ex['items'], key=lambda it: (it['group'], it['num']))
        cur_group = None
        for it in items:
            if it['group'] != cur_group:
                if cur_group is not None: out.append('</ol>')
                if ex['groups'].get(it['group']): out.append(f'<p class="ex-group">{ex["groups"][it["group"]]}</p>')
                out.append('<ol class="ex-list">'); cur_group = it['group']
            body = ' '.join(it['html']).strip() + (code_html(it['code']) if it.get('code') else '')
            if solutions:
                out.append(f'<li><div class="sol" id="sol-{ex["key"]}-{it["num"]}" data-ex="ex-{ex["key"]}-{it["num"]}">'
                           f'<p><strong>{it["num"]}.</strong> {body}</p></div></li>')
            else:
                out.append(f'<li class="ex" id="ex-{ex["key"]}-{it["num"]}" value="{it["num"]}">{body}</li>')
        if cur_group is not None: out.append('</ol>')
        out.append('</div>'); ex = None

    def open_sec(level, tag):
        while stack and stack[-1][0] >= level:
            out.append('</section>'); stack.pop()
        out.append(tag); stack.append((level, tag))

    chapter_no, dropcap, wrap = None, '', 0
    for kind, pno, obj, left in flow(slug, a, b, skip):
        if kind == 'fig':
            fig = C.figure(pno, obj)
            if ex and ex['items']:
                col = min(ex['cols'], key=lambda c: abs(c - (obj.x0 - left))) if ex['cols'] else None   # columns are margin-relative
                target = [it for it in ex['items'] if it['col'] == col and it['y'] < obj.y1] or ex['items']
                max(target, key=lambda it: (it['pno'], it['y']))['html'].append(fig)
            else:
                close_para(); out.append(fig)
            continue
        row = obj
        ft = first_text(row)
        text = row.text().strip()
        if not ft: continue
        if row.size > 20 and len(text) == 1:                  # drop cap: glue to the first line of the paragraph
            dropcap, wrap = text, 2; continue
        # --- chapter / part titles (big bold) ---
        if row.size >= 13:
            close_para(); close_ex()
            m = re.match(r'CHAPTER\s*(\d+)', text)
            if m: chapter_no = m.group(1); continue
            if chapter_no:
                open_sec(1, f'<section class="chapter" id="ch{chapter_no}">')
                out.append(f'<h1><span class="num">Chapter {chapter_no}</span> {html.escape(text)}</h1>')
            else:
                open_sec(1, f'<section class="front" id="{slug}">'); out.append(f'<h1>{html.escape(text)}</h1>')
            continue
        # --- section heading ---
        m = re.match(r'^(\d+)\.(\d+)\s+(.*)', text)
        if ft.bold and m and row.size > 10.5 and abs(row.x0 - left) < 6:
            close_para(); close_ex()
            sid, title = f'{m.group(1)}.{m.group(2)}', m.group(3).strip()
            open_sec(2, f'<section class="sec" id="s{m.group(1)}-{m.group(2)}" data-title="{html.escape(title, quote=True)}">')
            out.append(f'<h2><span class="num">{sid}</span> {html.escape(title)}</h2>')
            continue
        # --- exercise block header (in the Solutions appendix: "Chapter N Exercises" / "Section X.Y") ---
        m = re.match(r'^Exercises for (Section|Chapter) ([\d.]+)', text) if not solutions else \
            re.match(r'^(Sections?) (\d+\.\d+)$|^(Chapter) (\d+)( Exercises)?$', text)   # the book once prints "Sections 3.4"
        if solutions and m: m = re.match(r'(\w+) ([\d.]+)', m.group(0))
        if ft.bold and m:
            close_para(); close_ex()
            key = m.group(2) if m.group(1).startswith('Section') else 'ch' + m.group(2)
            out.append(f'<div class="exercises" data-for="{key}"><h3>{html.escape(text)}</h3>')
            ex = {'key': key, 'items': [], 'groups': {}, 'group': 0, 'cols': [], 'intro': []}
            continue
        # --- code blocks (coding books): rows set entirely in a monospace font ---
        vis = [v for k, v in row.items if k == 'span' and v.text.strip()]
        if vis and all(v.mono for v in vis) and not any(k == 'math' for k, _ in row.items):
            cw = next(((v.x1 - v.x0) / len(v.text) for v in vis if len(v.text) > 3), 5.0)   # monospace char width
            line = ''.join(v.text for k, v in row.items if k == 'span')
            if ex is not None and ex['items']:                # code inside an exercise
                ex['items'][-1].setdefault('code', []).append((row.x0, cw, line)); continue
            if para: close_para()
            code_buf.append((row.x0, cw, line)); continue
        if ex is not None:
            # group heading "A. ..." (bold) or its bold continuation
            if ft.bold and re.match(r'^[A-Z]\.\s', text) and not NUM.match(ft.text.strip()):
                ex['group'] += 1; ex['groups'][ex['group']] = C.inline(pno, row); ex['last'] = 'group'; continue
            # split row at bold item numbers (two-column layouts put two items on one row)
            def prev_word(i):
                return next((v.text.strip() for k, v in reversed(row.items[:i]) if k == 'span' and v.text.strip()), '')
            cuts = [i for i, (k, v) in enumerate(row.items) if k == 'span' and v.bold and NUM.match(v.text.strip())
                    and not re.search(r'(Case|Step|Part)$', prev_word(i))]      # "Case 1." inside a proof is not an item
            if not cuts:
                if ex.get('last') == 'group' and all(v.bold for k, v in row.items if k == 'span' and v.text.strip()):
                    ex['groups'][ex['group']] += ' ' + C.inline(pno, row); continue
                if not ex['items']:                           # untitled intro paragraph before the first item
                    ex['groups'][ex['group']] = (ex['groups'].get(ex['group'], '') + ' ' + C.inline(pno, row)).strip(); continue
                col = min(ex['cols'], key=lambda c: abs(c - (row.x0 - left)))
                tgt = max((it for it in ex['items'] if it['col'] == col), key=lambda it: (it['pno'], it['y']))
                add(tgt['html'], C.inline(pno, row)); continue
            if cuts[0] > 0:                                   # text before the first number continues the left column item
                pre = row.items[:cuts[0]]
                if ex['items']: add(ex['items'][-1]['html'], C.inline(pno, row, pre))
            for j, c in enumerate(cuts):
                seg = row.items[c + 1:(cuts[j + 1] if j + 1 < len(cuts) else None)]
                x0 = row.items[c][1].x0 - left              # odd/even pages have different margins
                col = next((cc for cc in ex['cols'] if abs(cc - x0) < 25), None)
                if col is None: ex['cols'].append(x0); col = x0
                ex['items'].append({'num': int(row.items[c][1].text.strip()[:-1]), 'group': ex['group'], 'col': col,
                                    'y': row.y0, 'pno': pno, 'html': [C.inline(pno, row, seg)]})
            ex['last'] = 'item'
            continue
        flush_code()
        # --- body text ---
        indent = row.x0 - left
        if wrap: wrap -= 1; indent = 0                         # lines wrapped around a drop cap are indented
        gap = (row.y0 - last_row_y) if last_row_y is not None and last_row_y < row.y0 else 0
        last_row_y = row.y1
        starts_label = ft.bold and ft.text.strip().split(' ')[0] in LABELS
        starts_proof = ft.italic and ft.text.strip().startswith('Proof')
        bullet = text.startswith('•')
        caption = ft.bold and re.match(r'^Figure \d+\.\d+\.', text)
        item = indent > 3 and re.match(r'^\d+\.(?!\d)', text) is not None   # numbered list inside the body
        display = indent > 28 and not bullet and not caption and not item
        new = not para or indent > 8 or gap > 9 or starts_label or starts_proof or bullet or caption or display or item or para_cls == 'display'
        if para and re.search(r'\w-(</\w+>)*$', para[-1]): new = False     # a word broken across lines never ends a paragraph
        if new:
            close_para()
            para_cls = ('display' if display else 'caption' if caption else 'bullet' if bullet else 'item' if item else
                        f'lbl {ft.text.strip().split(" ")[0].lower()}' if starts_label else 'proof' if starts_proof else '')
        piece = C.inline(pno, row)
        if dropcap: piece, dropcap = dropcap + piece, ''
        add(para, piece)
    close_para(); close_ex()
    while stack: out.append('</section>'); stack.pop()
    return '\n'.join(out) + '\n', C.n


if __name__ == '__main__':
    slug, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    skip = range(int(sys.argv[4]), int(sys.argv[5]) + 1) if len(sys.argv) > 5 else ()
    src, n = convert(slug, a, b, skip, solutions=slug == 'solutions')
    (ROOT / 'content' / f'{slug}.html').write_text(src, encoding='utf-8')
    print(f'content/{slug}.html written, {n} crops')
