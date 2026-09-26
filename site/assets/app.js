// Book of Proof reader: progress tracking (localStorage) + exercise grading with the reader's own LLM key.
(() => {
  // progress is per book (all books on one GitHub Pages user share an origin); settings and theme are shared on purpose
  const BOOK_ID = document.body.dataset.book || 'bop';
  const PKEY = `${BOOK_ID}-progress-v1`, SKEY = 'bop-settings-v1';
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) || d; } catch { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: progress not kept */ } };
  const P = load(PKEY, { ex: {}, manual: {} });
  const S = load(SKEY, { provider: 'anthropic', model: '', key: '', baseUrl: '' });
  const persist = () => save(PKEY, P);

  // Khan-style levels. Auto level comes from the share of a section's exercises graded correct.
  const LEVELS = [['none', 'Not started', 0], ['attempted', 'Attempted', 0], ['familiar', 'Familiar', 50],
                  ['proficient', 'Proficient', 80], ['mastered', 'Mastered', 100]];
  const lvl = name => LEVELS.find(l => l[0] === name);
  function sectionLevel(sec) {
    if (P.manual[sec.id]) return P.manual[sec.id];
    if (!sec.ex.length) return 'none';
    const st = sec.ex.map(id => P.ex[id]?.s);
    const frac = st.filter(s => s === 'correct').length / sec.ex.length;
    if (frac === 1) return 'mastered';
    if (frac >= 0.7) return 'proficient';
    if (frac >= 0.3) return 'familiar';
    return st.some(Boolean) ? 'attempted' : 'none';
  }
  const pts = secs => secs.length ? secs.reduce((a, s) => a + lvl(sectionLevel(s))[2], 0) / secs.length : 0;

  // ---------- LLM providers (browser -> provider directly; key never leaves the reader's browser otherwise) ----------
  const PROVIDERS = {
    anthropic: { label: 'Anthropic', model: 'claude-sonnet-5' },
    openai: { label: 'OpenAI', model: 'gpt-5', base: 'https://api.openai.com/v1' },
    gemini: { label: 'Google Gemini', model: 'gemini-2.5-flash' },
    openrouter: { label: 'OpenRouter (any model)', model: 'anthropic/claude-sonnet-5', base: 'https://openrouter.ai/api/v1' },
    custom: { label: 'OpenAI-compatible (Mistral, Groq, DeepSeek, Ollama…)', model: '', base: 'http://localhost:11434/v1' },
  };
  async function ask(system, user) {
    const pr = PROVIDERS[S.provider], model = S.model || pr.model;
    if (!S.key && S.provider !== 'custom') throw new Error('Add your API key in Settings first.');
    let r, j;
    if (S.provider === 'anthropic') {
      r = await fetch('https://api.anthropic.com/v1/messages', { method: 'POST', headers: {
        'content-type': 'application/json', 'x-api-key': S.key, 'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model, max_tokens: 1500, system, messages: [{ role: 'user', content: user }] }) });
      j = await r.json(); if (!r.ok) throw new Error(j.error?.message || r.status);
      return j.content.map(c => c.text || '').join('');
    }
    if (S.provider === 'gemini') {
      r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(S.key)}`,
        { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({
          systemInstruction: { parts: [{ text: system }] }, contents: [{ role: 'user', parts: [{ text: user }] }] }) });
      j = await r.json(); if (!r.ok) throw new Error(j.error?.message || r.status);
      return j.candidates[0].content.parts.map(p => p.text || '').join('');
    }
    const base = (S.baseUrl || pr.base).replace(/\/$/, '');
    r = await fetch(base + '/chat/completions', { method: 'POST', headers: {
      'content-type': 'application/json', ...(S.key ? { authorization: 'Bearer ' + S.key } : {}) },
      body: JSON.stringify({ model, messages: [{ role: 'system', content: system }, { role: 'user', content: user }] }) });
    j = await r.json(); if (!r.ok) throw new Error(j.error?.message || r.status);
    return j.choices[0].message.content;
  }

  const BOOK = () => document.querySelector('.top .home')?.textContent.trim() || 'this textbook';
  const GRADER = () => `You grade answers to exercises from the textbook "${BOOK()}". Math is written in LaTeX.
Judge correctness and, for proofs, rigor and completeness at the level of the book. Accept any correct answer
or valid proof, not only the one in the official solution. For code, the student's program was really executed and its
output is included: a crash, wrong output or missing requirement is not correct; judge style only if the exercise asks.
Be concise and kind; point to the first real error.
Reply with ONLY a JSON object: {"verdict":"correct"|"partial"|"incorrect","feedback":"<= 120 words, may use LaTeX"}`;
  async function grade(ex, answer, run) {
    const user = [ex.group && `Instructions for this group of exercises: ${ex.group}`, `Exercise ${ex.num}: ${ex.src}`,
      ex.sol && `Official solution from the book (reference only): ${ex.sol}`,
      `Student answer${run ? ` (${run.lang} code)` : ''}:\n${answer}`,
      run && `Actual execution result:\n${(run.out || '(no output)').slice(0, 4000)}${run.error ? `\nERROR: ${run.error.slice(0, 2000)}` : ''}`,
    ].filter(Boolean).join('\n\n');
    const out = await ask(GRADER(), user);
    const m = out.match(/\{[\s\S]*\}/);
    if (!m) throw new Error('Unexpected grader reply: ' + out.slice(0, 200));
    const g = JSON.parse(m[0]);
    return { s: ['correct', 'partial', 'incorrect'].includes(g.verdict) ? g.verdict : 'incorrect', fb: String(g.feedback || '') };
  }

  // ---------- helpers ----------
  const el = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); Object.assign(e, attrs); e.append(...kids); return e; };
  // remaining math crops carry the PDF text layer in alt, so the grader still sees them
  const plain = h => h.replace(/<img[^>]*?alt="([^"]*)"[^>]*>/g, ' $1 ')
    .replace(/<[^>]+>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
  const typeset = nodes => window.MathJax?.typesetPromise ? MathJax.typesetPromise(nodes).catch(() => {}) : Promise.resolve();
  const whenMathJax = () => new Promise(res => { const t = setInterval(() => { if (window.MathJax?.typesetPromise) { clearInterval(t); res(); } }, 50); });

  // ---------- chapter pages ----------
  function setupChapter(outline) {
    const page = outline.find(c => c.slug === document.body.dataset.page);
    if (!page) return;
    const sols = fetch('solutions.json').then(r => r.json()).catch(() => ({}));
    const secBadges = [];
    for (const sec of page.sections) {
      const h = document.getElementById(sec.id)?.querySelector('h2') ||
                document.querySelector(`.exercises[data-for="${sec.id.replace(/^x-/, '')}"] h3`);
      if (!h) continue;
      const badge = el('span', { className: 'lvl-badge' });
      const sel = el('select', { title: 'Set level manually' },
        el('option', { value: '', textContent: 'Auto' }), ...LEVELS.filter(l => l[0] !== 'attempted').map(l => el('option', { value: l[0], textContent: l[1] })));
      sel.value = P.manual[sec.id] || '';
      sel.onchange = () => { sel.value ? P.manual[sec.id] = sel.value : delete P.manual[sec.id]; persist(); refresh(); };
      h.after(el('div', { className: 'sec-status' }, badge, sel, el('span', { className: 'hint', textContent:
        sec.ex.length ? `${sec.ex.length} exercises` : 'No exercises: set the level when you are done' })));
      secBadges.push([sec, badge]);
    }
    const refresh = () => secBadges.forEach(([s, b]) => { const l = lvl(sectionLevel(s)); b.textContent = l[1]; b.dataset.l = l[0]; });
    refresh();

    document.querySelectorAll('li.ex').forEach(li => {
      const ol = li.closest('ol'); let g = ol.previousElementSibling;
      while (g && !g.classList.contains('ex-group') && g.tagName !== 'H3') g = g.previousElementSibling;
      const ex = { id: li.id, num: li.value || '', src: plain(li.innerHTML), group: g?.classList.contains('ex-group') ? plain(g.innerHTML) : '' };
      const st = P.ex[li.id] || {};
      // coding exercise: runnable language on this page and the exercise shows code or asks for a program
      const lang = li.querySelector('pre.code')?.dataset.lang || document.body.dataset.codeLang;
      const isCode = !!WORKERS[lang] && !!(li.querySelector('pre.code') ||
        /\b(write|implement|program|function|code|script|class|method|print|output)\b/i.test(ex.src + ' ' + ex.group));
      const ta = el('textarea', { rows: isCode ? 8 : 3, className: isCode ? 'code-input' : '', spellcheck: !isCode, value: st.a || '',
        placeholder: isCode ? `Your ${lang} code (Run to try it; Check answer runs it and grades the result)` :
          'Your answer. Write math in LaTeX, e.g. \\(\\{1,2,3\\}\\) or \\(x \\in \\mathbb{Z}\\)' });
      const runBox = el('pre', { className: 'run-out', hidden: true });
      const runBtn = el('button', { type: 'button', className: 'ghost run', textContent: '▶ Run', hidden: !isCode });
      runBtn.onclick = async () => { runBtn.disabled = true; showRun(runBox, { out: 'Running…' });
        try { showRun(runBox, await runCode(lang, ta.value)); } catch (e) { showRun(runBox, { error: e.message }); }
        runBtn.disabled = false; };
      const prev = el('div', { className: 'preview' }), res = el('div', { className: 'result' });
      const check = el('button', { type: 'button', textContent: 'Check answer' });
      const solBtn = el('button', { type: 'button', className: 'ghost', textContent: 'Show book solution', hidden: true });
      const solBox = el('div', { className: 'solution', hidden: true });
      const mark = (s, fb) => { P.ex[li.id] = { ...P.ex[li.id], s, fb, a: ta.value, t: Date.now() }; persist(); show(); refresh(); };
      const show = () => { const e = P.ex[li.id]; li.dataset.s = e?.s || ''; res.innerHTML = e?.s ? `<strong>${e.s[0].toUpperCase() + e.s.slice(1)}.</strong> ${e.fb || ''}` : ''; typeset([res]); };
      let tm; ta.oninput = () => { if (isCode) return; clearTimeout(tm); tm = setTimeout(() => { prev.textContent = ta.value; typeset([prev]); }, 400); };
      if (isCode) ta.onkeydown = e => { if (e.key === 'Tab') { e.preventDefault(); ta.setRangeText('    ', ta.selectionStart, ta.selectionEnd, 'end'); } };
      check.onclick = async () => {
        if (!ta.value.trim()) return;
        check.disabled = true; res.textContent = isCode ? 'Running your code…' : 'Checking…';
        try {
          let run = null;
          if (isCode) { run = { lang, ...(await runCode(lang, ta.value)) }; showRun(runBox, run); res.textContent = 'Checking…'; }
          const g = await grade({ ...ex, sol: (await sols)[li.id] && plain((await sols)[li.id]) }, ta.value, run); mark(g.s, g.fb);
        }
        catch (e) { res.textContent = 'Could not check: ' + e.message; }
        check.disabled = false;
      };
      sols.then(all => { if (all[li.id]) { solBtn.hidden = false; solBox.innerHTML = all[li.id]; } });
      solBtn.onclick = () => { solBox.hidden = !solBox.hidden; if (!solBox.hidden) typeset([solBox]); };
      const self = el('span', { className: 'self' }, 'Mark: ',
        el('button', { type: 'button', className: 'ghost', textContent: '✓', title: 'Mark correct', onclick: () => mark('correct', 'Marked correct by you.') }),
        el('button', { type: 'button', className: 'ghost', textContent: '✗', title: 'Mark incorrect', onclick: () => mark('incorrect', 'Marked incorrect by you.') }));
      li.append(el('details', { className: 'answer', open: !!st.a }, el('summary', { textContent: st.s ? 'Your answer' : 'Answer this' }),
        ta, prev, el('div', { className: 'row' }, runBtn, check, solBtn, self), runBox, res, solBox));
      show();
    });
  }

  // ---------- contents page ----------
  function setupIndex(outline) {
    const all = outline.flatMap(c => c.sections);
    const setBar = (root, pct) => { root.querySelector('.bar span').style.width = pct + '%'; root.querySelector('.pct').textContent = Math.round(pct) + '%'; };
    setBar(document.querySelector('.overall'), pts(all));
    for (const c of outline) {
      const li = document.querySelector(`.toc-ch[data-slug="${c.slug}"]`);
      if (!li) continue;
      c.sections.length ? setBar(li, pts(c.sections)) : li.querySelector('.bar').remove();
      for (const s of c.sections) {
        const l = lvl(sectionLevel(s)), t = li.querySelector(`[data-sec="${s.id}"] .lvl`);
        if (t) { t.textContent = l[1]; t.dataset.l = l[0]; }
      }
    }
    document.getElementById('export-btn').onclick = () => {
      const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(P)], { type: 'application/json' })), download: `${BOOK_ID}-progress.json` });
      a.click(); URL.revokeObjectURL(a.href);
    };
    document.getElementById('import-file').onchange = async e => {
      try { const d = JSON.parse(await e.target.files[0].text()); if (!d.ex || !d.manual) throw 0;
        if (confirm('Replace your current progress with the imported file?')) { save(PKEY, d); location.reload(); } }
      catch { alert('That file is not a Book of Proof progress export.'); }
    };
  }

  // ---------- settings ----------
  function setupSettings(reading) {
    const prov = el('select', {}, ...Object.entries(PROVIDERS).map(([k, v]) => el('option', { value: k, textContent: v.label })));
    const model = el('input', { placeholder: 'model' }), key = el('input', { type: 'password', placeholder: 'API key', autocomplete: 'off' });
    const base = el('input', { placeholder: 'Base URL' });
    const sync = () => { const p = PROVIDERS[prov.value]; model.placeholder = p.model || 'model name'; base.parentElement.hidden = prov.value !== 'custom'; };
    prov.value = S.provider; model.value = S.model; key.value = S.key; base.value = S.baseUrl;
    const status = el('p', { className: 'hint' });
    const dlg = el('dialog', { className: 'settings' }, reading, el('h2', { textContent: 'Answer checking' }),
      el('p', { className: 'hint', textContent: 'Answers are checked by an AI model using your own API key. The key is stored only in this browser and sent only to the provider you choose.' }),
      el('label', {}, 'Provider', prov), el('label', {}, 'Model', model), el('label', {}, 'Base URL', base), el('label', {}, 'API key', key), status,
      el('div', { className: 'row' },
        el('button', { type: 'button', textContent: 'Test', onclick: async () => { apply(); status.textContent = 'Testing…';
          try { await ask('Reply with the single word OK.', 'Ping'); status.textContent = 'Works.'; } catch (e) { status.textContent = 'Failed: ' + e.message; } } }),
        el('button', { type: 'button', textContent: 'Save', onclick: () => { apply(); dlg.close(); } }),
        el('button', { type: 'button', className: 'ghost', textContent: 'Close', onclick: () => dlg.close() })));
    const apply = () => { Object.assign(S, { provider: prov.value, model: model.value.trim(), key: key.value.trim(), baseUrl: base.value.trim() }); save(SKEY, S); };
    prov.onchange = sync; document.body.append(dlg); sync();
    document.getElementById('settings-btn').onclick = () => dlg.showModal();
  }

  // ---------- code execution for coding books (Python via Pyodide, JavaScript natively), each in a Web Worker ----------
  const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
  const WORKERS = {
    python: `importScripts('${PYODIDE}pyodide.js');
      let py; const ready = loadPyodide({ indexURL: '${PYODIDE}' }).then(p => { py = p; postMessage({ ready: true }); });
      onmessage = async e => { await ready; let out = '';
        py.setStdout({ batched: s => out += s + '\\n' }); py.setStderr({ batched: s => out += s + '\\n' });
        try { await py.loadPackagesFromImports(e.data); await py.runPythonAsync(e.data); postMessage({ out }); }
        catch (err) { postMessage({ out, error: String(err.message || err) }); } };`,
    javascript: `postMessage({ ready: true });
      onmessage = async e => { let out = ''; const log = (...a) => out += a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' ') + '\\n';
        self.console = { log, info: log, warn: log, error: log };
        try { await (0, eval)('(async () => {' + e.data + '\\n})()'); postMessage({ out }); }
        catch (err) { postMessage({ out, error: String(err && err.stack || err) }); } };`,
  };
  const pool = {};
  function worker(lang) {                       // one warm worker per language; recreated after a timeout
    if (!pool[lang]) {
      const w = new Worker(URL.createObjectURL(new Blob([WORKERS[lang]], { type: 'text/javascript' })));
      pool[lang] = { w, ready: new Promise((res, rej) => { w.onmessage = e => e.data.ready && res(); w.onerror = rej; }) };
    }
    return pool[lang];
  }
  async function runCode(lang, code, timeout = 10000) {
    if (!WORKERS[lang]) throw new Error(`Running ${lang} code is not supported in the browser.`);
    const p = worker(lang);
    await Promise.race([p.ready, new Promise((_, rej) => setTimeout(() => rej(new Error('The interpreter took too long to load.')), 90000))]);
    return new Promise(res => {
      const t = setTimeout(() => { p.w.terminate(); delete pool[lang]; res({ out: '', error: `Stopped after ${timeout / 1000} s (infinite loop?)` }); }, timeout);
      p.w.onmessage = e => { if (e.data.ready) return; clearTimeout(t); res(e.data); };
      p.w.postMessage(code);
    });
  }
  const showRun = (box, r) => { box.hidden = false; box.textContent = (r.out || '') + (r.error ? (r.out ? '\n' : '') + r.error : '') || '(no output)'; box.classList.toggle('err', !!r.error); };

  function setupCode() {
    document.querySelectorAll('pre.code').forEach(pre => {
      const lang = pre.dataset.lang;
      if (!WORKERS[lang] || pre.closest('li.ex details')) return;
      const code = pre.querySelector('code');
      code.contentEditable = 'plaintext-only'; code.spellcheck = false;       // readers can tweak and re-run examples
      const box = el('pre', { className: 'run-out', hidden: true });
      const btn = el('button', { type: 'button', className: 'ghost run', textContent: '▶ Run' });
      btn.onclick = async () => { btn.disabled = true; box.hidden = false; box.textContent = 'Running… (first run loads the interpreter)';
        try { showRun(box, await runCode(lang, code.innerText)); } catch (e) { showRun(box, { error: e.message }); }
        btn.disabled = false; };
      pre.after(el('div', { className: 'run-bar' }, btn), box);
    });
  }

  // ---------- reading preferences: theme + text size (applied early by an inline <head> script) ----------
  function setupReading() {
    const RKEY = 'bop-reader-v1', R = load(RKEY, {}), root = document.documentElement;
    const THEMES = [['', 'Auto', 'linear-gradient(90deg,#fbfaf7 50%,#171716 50%)'], ['light', 'Light', '#fbfaf7'],
                    ['sepia', 'Sepia', '#f4ecd8'], ['dark', 'Dark', '#171716'], ['contrast', 'High contrast', '#000']];
    const apply = () => {
      R.theme ? root.dataset.theme = R.theme : delete root.dataset.theme;
      R.fs ? root.style.setProperty('--fs', R.fs + 'px') : root.style.removeProperty('--fs');
      save(RKEY, R); sync();
    };
    const themeBtns = THEMES.map(([k, label, sw]) => el('button', { type: 'button', className: 'ghost',
      onclick: () => { R.theme = k; apply(); } }, el('span', { className: 'theme-swatch', style: `background:${sw}` }), label));
    const size = el('input', { type: 'range', min: 14, max: 26, step: 1 });
    const out = el('span', { className: 'hint' });
    size.oninput = () => { R.fs = +size.value; apply(); };
    const step = d => { R.fs = Math.min(26, Math.max(14, (R.fs || 18) + d)); apply(); };
    const sync = () => {
      themeBtns.forEach((b, i) => b.setAttribute('aria-pressed', String((R.theme || '') === THEMES[i][0])));
      size.value = R.fs || 18; out.textContent = (R.fs || 18) + ' px';
    };
    size.setAttribute('aria-label', 'Text size');
    sync();
    return el('section', { className: 'reading' }, el('h2', { textContent: 'Reading' }),   // first section of Settings
      el('p', { className: 'hint', textContent: 'Theme' }), el('div', { className: 'themes' }, ...themeBtns),
      el('p', { className: 'hint', textContent: 'Text size' }),
      el('div', { className: 'sizes' }, el('button', { type: 'button', className: 'ghost', textContent: 'A−', title: 'Smaller', onclick: () => step(-1) }),
        size, el('button', { type: 'button', className: 'ghost', textContent: 'A+', title: 'Larger', onclick: () => step(1) }), out,
        el('button', { type: 'button', className: 'ghost', textContent: 'Reset', onclick: () => { delete R.theme; delete R.fs; apply(); } })));
  }

  document.addEventListener('DOMContentLoaded', async () => {
    setupSettings(setupReading());
    setupCode();
    const outline = await fetch('outline.json').then(r => r.json()).catch(() => []);
    document.body.dataset.page === 'index' ? setupIndex(outline) : setupChapter(outline);  // captures exercise TeX before typesetting
    await whenMathJax(); typeset([document.querySelector('main')]);
  });
})();
