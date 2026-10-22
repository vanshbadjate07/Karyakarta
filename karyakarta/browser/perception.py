"""Turns the live page into what the model sees: a screenshot with numbered
marks on every usable element, a compact text list of those same elements, and
the text currently visible on screen.

The list and the marks come from ONE pass over the page and each element is
tagged in the page itself (data-kk="<number>"), so the number the model picks
always resolves to the exact element that was shown, never to a different
one after the page re-renders.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from karyakarta.models import Element, Observation
from karyakarta.safety import injection, sensitive
from karyakarta.safety.policy import classify_form

MAX_ELEMENTS = 60
MAX_TEXT_CHARS = 1800

_SCAN_JS = r"""
(maxElements) => {
  const SELECTOR = [
    'input:not([type=hidden])', 'textarea', 'select', 'button', 'a[href]', 'summary',
    '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=switch]', '[role=tab]',
    '[role=menuitem]', '[role=option]', '[role=combobox]', '[role=textbox]', '[role=searchbox]',
    '[contenteditable=""]', '[contenteditable="true"]', '[onclick]'
  ].join(',');
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const roots = [document];
  const candidates = [];
  const seen = new Set();
  function collect(root) {
    root.querySelectorAll(SELECTOR).forEach((el) => { if (!seen.has(el)) { seen.add(el); candidates.push(el); } });
    let n = 0;
    root.querySelectorAll('*').forEach((el) => {
      if (++n > 20000) return;
      if (el.shadowRoot) { roots.push(el.shadowRoot); collect(el.shadowRoot); }
    });
  }
  collect(document);

  // Clickable-looking elements that are not real controls (div/span with a pointer cursor).
  let checked = 0;
  document.querySelectorAll('div,span,li,img,svg,td').forEach((el) => {
    if (checked > 1500 || seen.has(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 12 || r.height < 12 || r.width > 700 || r.height > 300) return;
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return;
    checked++;
    if (getComputedStyle(el).cursor !== 'pointer') return;
    if (el.closest('a,button,[role=button],[onclick],select,label')) return;
    if (el.querySelector('a,button,input,select,textarea')) return;
    if (!clean(el.innerText) && !el.getAttribute('aria-label') && !el.getAttribute('title')) return;
    seen.add(el); candidates.push(el);
  });

  roots.forEach((root) => root.querySelectorAll('[data-kk],[data-kk-label]').forEach((e) => {
    e.removeAttribute('data-kk'); e.removeAttribute('data-kk-label');
  }));

  function labelOf(el) {
    const aria = el.getAttribute('aria-label');
    if (aria && clean(aria)) return clean(aria);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = clean(by.split(/\s+/).map((id) => { const n = document.getElementById(id); return n ? n.innerText : ''; }).join(' '));
      if (t) return t;
    }
    if (el.labels && el.labels.length && clean(el.labels[0].innerText)) return clean(el.labels[0].innerText);
    const wrap = el.closest('label');
    if (wrap && clean(wrap.innerText)) return clean(wrap.innerText);
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' && ['submit', 'button', 'reset'].includes((el.type || '').toLowerCase()) && el.value) return clean(el.value);
    const own = clean(el.innerText || el.textContent);
    if (own && own.length <= 100) return own;
    if (own) return own.slice(0, 97) + '...';
    if (el.placeholder) return clean(el.placeholder);
    const img = el.querySelector('img[alt]');
    if (img && clean(img.alt)) return clean(img.alt);
    if (el.getAttribute('title')) return clean(el.getAttribute('title'));
    if (el.getAttribute('name')) return el.getAttribute('name');
    return '';
  }
  function kindOf(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (tag === 'a' || role === 'link') return 'link';
    if (tag === 'select' || role === 'combobox') return 'select';
    if (tag === 'textarea') return 'textarea';
    if (tag === 'input') {
      if (['submit', 'button', 'reset', 'image'].includes(type)) return 'button';
      if (['checkbox', 'radio', 'password', 'email', 'tel', 'number', 'search', 'file', 'date', 'url'].includes(type)) return type;
      return 'text';
    }
    if (role === 'checkbox' || role === 'switch') return 'checkbox';
    if (role === 'radio') return 'radio';
    if (role === 'searchbox') return 'search';
    if (role === 'textbox' || el.isContentEditable) return 'text';
    return 'button';
  }
  function visibleBox(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return null;
    return r;
  }
  function unobstructed(el, r) {
    const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 2);
    const cy = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 2);
    const root = el.getRootNode();
    const top = (root && root.elementFromPoint ? root : document).elementFromPoint(cx, cy);
    if (!top) return false;
    return top === el || el.contains(top) || top.contains(el);
  }

  const forms = new Map();
  const formSummaries = {};
  function formIdOf(el) {
    const f = el.form || el.closest('form');
    if (!f) return '';
    if (!forms.has(f)) {
      const id = 'f' + forms.size;
      forms.set(f, id);
      const fields = [];
      f.querySelectorAll('input,select,textarea').forEach((i) => {
        const t = (i.getAttribute('type') || (i.tagName === 'TEXTAREA' ? 'textarea' : i.tagName === 'SELECT' ? 'select' : 'text')).toLowerCase();
        if (['hidden', 'submit', 'button', 'reset', 'image', 'checkbox', 'radio'].includes(t)) return;
        fields.push({ kind: t, name: i.getAttribute('name') || '', id: i.id || '', label: labelOf(i), placeholder: i.getAttribute('placeholder') || '', autocomplete: i.getAttribute('autocomplete') || '' });
      });
      const role = (f.getAttribute('role') || (f.closest('[role=search]') ? 'search' : '')).toLowerCase();
      fields.forEach((x) => { x.role = role; });
      formSummaries[id] = fields;
    }
    return forms.get(f);
  }

  const result = [];
  let above = 0, below = 0;
  for (const el of candidates) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let box = visibleBox(el);
    let proxy = null;
    if (!box && tag === 'input' && ['checkbox', 'radio'].includes(type)) {
      const lab = (el.labels && el.labels[0]) || el.closest('label');
      if (lab) { box = visibleBox(lab); if (box) proxy = lab; }
    }
    if (!box) continue;
    const target = proxy || el;
    if (box.bottom <= 0) { above++; continue; }
    if (box.top >= innerHeight) { below++; continue; }
    if (box.right <= 0 || box.left >= innerWidth) continue;
    if (!unobstructed(target, box)) continue;
    result.push({ el, proxy, box });
  }

  const kept = result.slice(0, maxElements);
  const out = kept.map(({ el, proxy, box }, i) => {
    const ref = i + 1;
    el.setAttribute('data-kk', String(ref));
    if (proxy) proxy.setAttribute('data-kk-label', String(ref));
    const tag = el.tagName.toLowerCase();
    const kind = kindOf(el);
    const type = (el.getAttribute('type') || '').toLowerCase();
    let value = '';
    let options = [];
    if (tag === 'select') {
      const opts = Array.from(el.options || []);
      value = el.selectedIndex >= 0 && opts[el.selectedIndex] ? clean(opts[el.selectedIndex].text) : '';
      options = opts.slice(0, 12).map((o) => clean(o.text)).filter(Boolean);
    } else if (tag === 'input' || tag === 'textarea') {
      value = el.value || '';
    } else if (el.isContentEditable) {
      value = clean(el.innerText);
    }
    let checked = null;
    if (kind === 'checkbox' || kind === 'radio') {
      checked = tag === 'input' ? !!el.checked : el.getAttribute('aria-checked') === 'true';
    }
    let href = '';
    if (kind === 'link' && el.getAttribute('href')) {
      try { const u = new URL(el.href); href = (u.origin === location.origin ? u.pathname + u.search : u.hostname + u.pathname).slice(0, 80); } catch (e) { href = el.getAttribute('href').slice(0, 80); }
    }
    const inForm = !!(el.form || el.closest('form'));
    const submits = inForm && ((tag === 'button' && (type === '' || type === 'submit')) || (tag === 'input' && (type === 'submit' || type === 'image')));
    return {
      ref, tag, kind, type, label: labelOf(el), value, options, checked, href,
      name: el.getAttribute('name') || '', id: el.id || '', placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      readonly: !!el.readOnly || el.getAttribute('aria-readonly') === 'true',
      submits, formId: formIdOf(el),
      rect: [Math.round(box.left), Math.round(box.top), Math.round(box.width), Math.round(box.height)],
    };
  });

  // Text that is actually on screen right now.
  const parts = [];
  let total = 0;
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const p = n.parentElement;
      if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(p.tagName)) return NodeFilter.FILTER_REJECT;
      return clean(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const range = document.createRange();
  const BLOCK = 'p,div,li,h1,h2,h3,h4,h5,h6,td,th,tr,section,article,header,footer,nav,main,aside,form,ul,ol,dl,dt,dd,blockquote,pre,button,a,label,select,option,summary,figcaption';
  let lastBlock = null;
  while (walker.nextNode() && total < 1800) {
    const n = walker.currentNode;
    range.selectNodeContents(n);
    const r = range.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const st = getComputedStyle(n.parentElement);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    const t = clean(n.nodeValue);
    const block = n.parentElement.closest(BLOCK);
    if (parts.length && block !== lastBlock) parts.push('\n');
    lastBlock = block;
    parts.push(t); total += t.length + 1;
  }
  const scrollMax = Math.max(0, Math.round(document.documentElement.scrollHeight - innerHeight));
  return {
    title: document.title || '', url: location.href, elements: out, forms: formSummaries,
    text: parts.join(' ').replace(/ ?\n ?/g, '\n').slice(0, 1800),
    scrollY: Math.round(window.scrollY), scrollMax, above, below, extra: Math.max(0, result.length - kept.length),
  };
}
"""

_MARKS_JS = r"""
(items) => {
  const layer = document.createElement('div');
  layer.id = '__kk_marks__';
  layer.setAttribute('style', 'position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:2147483647;pointer-events:none;');
  const colors = { button: '#e5484d', link: '#1d9a6c', select: '#8e4ec6', checkbox: '#d9822b', radio: '#d9822b' };
  items.forEach((it) => {
    const color = colors[it.kind] || '#2f6fed';
    const box = document.createElement('div');
    box.setAttribute('style', `position:fixed;left:${it.x}px;top:${it.y}px;width:${it.w}px;height:${it.h}px;border:2px solid ${color};box-sizing:border-box;border-radius:3px;`);
    const tag = document.createElement('div');
    tag.textContent = String(it.ref);
    tag.setAttribute('style', `position:absolute;left:-2px;top:-17px;background:${color};color:#fff;font:bold 12px/15px monospace;padding:0 4px;border-radius:3px;`);
    if (it.y < 20) tag.style.top = '0px';
    box.appendChild(tag);
    layer.appendChild(box);
  });
  document.documentElement.appendChild(layer);
}
"""

_REMOVE_MARKS_JS = "() => { const l = document.getElementById('__kk_marks__'); if (l) l.remove(); }"


def _build_elements(raw_elements: list[dict[str, Any]], forms: dict[str, list[dict]]) -> list[Element]:
    form_kinds: dict[str, str] = {}
    for form_id, fields in forms.items():
        summary = [
            {
                "kind": f["kind"],
                "name": f.get("name", ""),
                "role": f.get("role", ""),
                "is_payment": sensitive.is_payment(
                    f.get("name", ""), f.get("id", ""), f.get("label", ""), f.get("placeholder", ""), f.get("autocomplete", "")
                ),
            }
            for f in fields
        ]
        form_kinds[form_id] = classify_form(summary)

    elements: list[Element] = []
    for raw in raw_elements:
        pw = sensitive.is_password(raw["type"], raw["name"], raw["id"], raw["label"], raw["autocomplete"])
        otp = sensitive.is_otp(raw["name"], raw["id"], raw["label"], raw["placeholder"], raw["autocomplete"])
        pay = sensitive.is_payment(raw["name"], raw["id"], raw["label"], raw["placeholder"], raw["autocomplete"])
        is_input = raw["kind"] not in ("button", "link", "checkbox", "radio", "select")
        elements.append(
            Element(
                ref=raw["ref"],
                tag=raw["tag"],
                kind="password" if pw else raw["kind"],
                label=raw["label"],
                value="" if (pw or otp or pay) else raw["value"],
                checked=raw["checked"],
                readonly=raw["readonly"],
                required=raw["required"],
                href=raw["href"],
                options=raw["options"],
                submits_form=raw["submits"],
                form_kind=form_kinds.get(raw["formId"], ""),
                form_id=raw["formId"],
                is_password=pw,
                is_otp=otp and is_input,
                is_payment=pay and is_input,
                rect=tuple(raw["rect"]),
            )
        )
    return elements


def _fingerprint(url: str, title: str, elements: list[Element], text: str, scroll_y: int) -> str:
    material = "|".join(
        [url, title, str(scroll_y // 40)]
        + [f"{e.kind}:{e.label}:{e.value}:{e.checked}" for e in elements]
        + [text[:400]]
    )
    return hashlib.sha1(material.encode("utf-8", "ignore")).hexdigest()[:16]


async def observe(page, *, with_marks: bool = True, retries: int = 3) -> Observation:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
                await page.wait_for_load_state("networkidle", timeout=1500)
            except Exception:
                pass  # busy pages (ads, polling) never go idle: observe what is there
            await asyncio.sleep(0.25)
            data = await page.evaluate(_SCAN_JS, MAX_ELEMENTS)
            elements = _build_elements(data["elements"], data["forms"])

            screenshot = b""
            if with_marks:
                marks = [
                    {"ref": e.ref, "kind": e.kind, "x": e.rect[0], "y": e.rect[1], "w": e.rect[2], "h": e.rect[3]}
                    for e in elements
                ]
                try:
                    await page.evaluate(_MARKS_JS, marks)
                    screenshot = await page.screenshot(type="jpeg", quality=72, animations="disabled", timeout=15000)
                finally:
                    try:
                        await page.evaluate(_REMOVE_MARKS_JS)
                    except Exception:
                        pass

            text, findings = injection.sanitize(data["text"])
            label_findings: list[str] = []
            for e in elements:
                label_findings += injection.find_injections(e.label)
            for e in elements:
                if injection.find_injections(e.label):
                    e.label = "[removed: instruction-like text from the page]"
            findings = findings + [f for f in label_findings if f not in findings]

            return Observation(
                url=data["url"],
                title=data["title"],
                elements=elements,
                text=text,
                scroll_y=data["scrollY"],
                scroll_max=data["scrollMax"],
                above=data["above"],
                below=data["below"],
                hidden_in_view=data["extra"],
                injection=findings,
                fingerprint=_fingerprint(data["url"], data["title"], elements, text, data["scrollY"]),
                screenshot=screenshot,
            )
        except Exception as exc:  # page navigated mid-scan, context destroyed, etc.
            last_error = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"Could not read the page: {last_error}")
