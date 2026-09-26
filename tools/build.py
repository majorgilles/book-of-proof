"""Assemble the static site from content/*.html into site/.
  python tools/build.py
Each content file becomes one page; site/index.html is the table of contents with progress bars.
Solutions (content/solutions.html) are split out to site/solutions.json keyed by exercise id."""
import re, json, html, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT, SITE = ROOT / 'content', ROOT / 'site'
BOOK = 'Book of Proof'
BOOK_ID = 'bop'          # short unique id per book: namespaces saved progress (books on one github.io share storage)
LICENSE = ('<footer class="license"><p><em>Book of Proof</em>, Third Edition, by Richard Hammack. '
           '© 2018 Richard Hammack. Licensed under '
           '<a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a>. '
           'The original PDF is freely available at '
           '<a href="https://richardhammack.github.io/BookOfProof/">richardhammack.github.io/BookOfProof</a>. '
           'This site is an unmodified format conversion with added progress tracking and exercise checking; '
           'it is not affiliated with or endorsed by the author.</p></footer>')

HOME = '<a href="index.html" class="toc-link">☰ Contents</a>'

PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — {book}</title>
<link rel="stylesheet" href="assets/style.css">
<script>try{{var r=JSON.parse(localStorage.getItem('bop-reader-v1'))||{{}};if(r.theme)document.documentElement.dataset.theme=r.theme;if(r.fs)document.documentElement.style.setProperty('--fs',r.fs+'px')}}catch(e){{}}</script>
<script>window.MathJax={{tex:{{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']]}},startup:{{typeset:false}}}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<script defer src="assets/app.js"></script>
</head><body data-book="{book_id}" data-page="{slug}"{code}>
<header class="top"><a href="index.html" class="home">{book}</a>
<nav>{home}{prev}{next}<button id="settings-btn" type="button">Settings</button></nav></header>
<main class="book">{body}</main>
<nav class="pager">{prev}{home}{next}</nav>
{license}
</body></html>'''


def code_attr(src):
    """Coding books: the language of the page's code blocks, so exercises there get a runnable editor."""
    m = re.search(r'<pre class="code" data-lang="([^"]+)"', src)
    return f' data-code-lang="{m.group(1)}"' if m else ''


def title_of(src):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', src, re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', m.group(1)))).strip() if m else 'Untitled'


def outline(slug, src):
    """Sections with their exercise ids, used by the TOC and the progress model."""
    secs = []
    for m in re.finditer(r'<section class="sec" id="([^"]+)" data-title="([^"]*)"', src):
        secs.append({'id': m.group(1), 'title': html.unescape(m.group(2)), 'ex': []})
    for chunk in src.split('<div class="exercises" data-for="')[1:]:
        key = chunk[:chunk.index('"')]
        ids = re.findall(r'<li class="ex" id="([^"]+)"', chunk)  # exercise <li>s only occur inside exercise blocks
        target = next((s for s in secs if s['id'] == 's' + key.replace('.', '-')), None)
        if target is None:  # chapter-level exercises become their own unit
            target = {'id': 'x-' + key, 'title': 'Exercises for Chapter ' + key.lstrip('ch'), 'ex': []}
            secs.append(target)
        target['ex'] += ids
    return {'slug': slug, 'title': title_of(src), 'sections': secs}


def main():
    order = ['front'] + [f'ch{i:02d}' for i in range(1, 15)] + ['conclusion', 'solutions']   # the book's reading order
    files = [CONTENT / f'{s}.html' for s in order if (CONTENT / f'{s}.html').exists()]
    pages = [(p.stem, p.read_text(encoding='utf-8')) for p in files]
    book = []
    for i, (slug, src) in enumerate(pages):
        prev = f'<a href="{pages[i-1][0]}.html" rel="prev">← Previous</a>' if i else ''
        nxt = f'<a href="{pages[i+1][0]}.html" rel="next">Next →</a>' if i + 1 < len(pages) else ''
        body = re.sub(r'^<!-- pages: .*? -->\s*', '', src)
        (SITE / f'{slug}.html').write_text(PAGE.format(title=title_of(src), book=BOOK, book_id=BOOK_ID, slug=slug, prev=prev, next=nxt, home=HOME, code=code_attr(src),
                                                       body=body, license=LICENSE), encoding='utf-8')
        book.append(outline(slug, src) if slug != 'solutions' else {'slug': slug, 'title': title_of(src), 'sections': []})
    (SITE / 'outline.json').write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding='utf-8')

    sol = CONTENT / 'solutions.html'
    sols = {}
    if sol.exists():
        for m in re.finditer(r'<div class="sol" id="[^"]+" data-ex="([^"]+)">(.*?)</div>', sol.read_text(encoding='utf-8'), re.S):
            sols[m.group(1)] = m.group(2).strip()
    (SITE / 'solutions.json').write_text(json.dumps(sols, ensure_ascii=False), encoding='utf-8')

    def toc_entry(c):
        secs = ''.join(f'<li class="toc-sec" data-sec="{s["id"]}"><a href="{c["slug"]}.html#{s["id"]}">'
                       f'{html.escape(s["title"])}</a><span class="lvl"></span></li>' for s in c['sections'])
        return (f'<li class="toc-ch" data-slug="{c["slug"]}"><a href="{c["slug"]}.html">{html.escape(c["title"])}</a>'
                f'<span class="bar"><span></span></span><span class="pct"></span>'
                + (f'<ul>{secs}</ul>' if secs else '') + '</li>')
    toc = ''.join(toc_entry(c) for c in book)
    index = (f'<section class="front"><h1>{BOOK}</h1><p class="sub">Third Edition — Richard Hammack</p>'
             '<div class="overall"><span class="bar big"><span></span></span><span class="pct"></span> of the book mastered</div>'
             '<p class="io"><button id="export-btn" type="button">Export progress</button> '
             '<label class="btn">Import progress<input id="import-file" type="file" accept="application/json" hidden></label></p>'
             f'<ol class="toc">{toc}</ol></section>')
    (SITE / 'index.html').write_text(PAGE.format(title='Contents', book=BOOK, book_id=BOOK_ID, slug='index', prev='', next='', home='', code='', body=index,
                                                 license=LICENSE), encoding='utf-8')
    print(f'built {len(pages)} pages, {sum(len(s["ex"]) for c in book for s in c["sections"])} exercises, {len(sols)} solutions')


if __name__ == '__main__':
    main()
