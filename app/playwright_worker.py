import threading
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .models import PageField

PICKER_JS = r"""
(() => {
  if (window.__ra_picker_installed) return;
  window.__ra_picker_installed = true;

  function cssEscapeIdent(ident) {
    return ident.replace(/([ #;?%&,.+*~\':"!^$[\]()=>|\/\@])/g,'\\$1');
  }

  function buildSelector(el) {
    if (!el || !el.tagName) return null;
    const tag = el.tagName.toLowerCase();
    const id = el.getAttribute('id');
    if (id) return `${tag}#${cssEscapeIdent(id)}`;

    const testId = el.getAttribute('data-testid');
    if (testId) return `${tag}[data-testid="${testId}"]`;

    const name = el.getAttribute('name');
    if (name) return `${tag}[name="${name}"]`;

    const aria = el.getAttribute('aria-label');
    if (aria) return `${tag}[aria-label="${aria.replace(/"/g,'\\\"')}"]`;

    let parts = [];
    let cur = el;
    let depth = 0;
    while (cur && cur.tagName && depth < 4) {
      const t = cur.tagName.toLowerCase();
      let nth = '';
      if (cur.parentElement) {
        const sibs = Array.from(cur.parentElement.children).filter(x => x.tagName === cur.tagName);
        if (sibs.length > 1) {
          const idx = sibs.indexOf(cur) + 1;
          nth = `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(t + nth);
      cur = cur.parentElement;
      depth++;
    }
    return parts.join(" > ");
  }

  function elementMeta(el) {
    const tag = el.tagName?.toLowerCase() || '';
    const type = el.getAttribute('type') || '';
    const name = el.getAttribute('name') || '';
    const id = el.getAttribute('id') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const aria = el.getAttribute('aria-label') || '';
    const role = el.getAttribute('role') || '';
    const text = (el.innerText || el.value || '').trim().slice(0, 120);
    return { tag, type, name, id, placeholder, aria, role, text };
  }

  function highlight(el) {
    const r = el.getBoundingClientRect();
    let box = document.getElementById('__ra_hl');
    if (!box) {
      box = document.createElement('div');
      box.id = '__ra_hl';
      box.style.position='fixed';
      box.style.zIndex='2147483647';
      box.style.pointerEvents='none';
      box.style.border='2px solid #00a3ff';
      box.style.background='rgba(0,163,255,0.08)';
      document.body.appendChild(box);
    }
    box.style.left = r.left + 'px';
    box.style.top = r.top + 'px';
    box.style.width = r.width + 'px';
    box.style.height = r.height + 'px';
  }

  function clearHighlight() {
    const box = document.getElementById('__ra_hl');
    if (box) box.remove();
  }

  window.__ra_picker = {
    active: false,
    last: null,
    start: () => { window.__ra_picker.active = true; },
    stop: () => { window.__ra_picker.active = false; clearHighlight(); },
  };

  document.addEventListener('mousemove', (e) => {
    if (!window.__ra_picker.active) return;
    const el = e.target;
    if (el) highlight(el);
  }, true);

  document.addEventListener('click', (e) => {
    if (!window.__ra_picker.active) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.target;
    const selector = buildSelector(el);
    const meta = elementMeta(el);
    window.__ra_picker.last = { selector, meta };
  }, true);
})();
"""

class PlaywrightWorker(QObject):
    log = Signal(str)
    status = Signal(str)
    page_scanned = Signal(list)  # list[dict]
    picked = Signal(str, dict)   # selector, meta

    def __init__(self):
        super().__init__()
        self._thread: Optional[threading.Thread] = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = threading.Lock()
        self._stop = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self.status.emit("Starting Playwright...")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            self._ctx = browser.new_context()
            self._page = self._ctx.new_page()

            self._page.add_init_script(PICKER_JS)
            self.status.emit("Ready (browser launched).")

            while not self._stop:
                threading.Event().wait(0.1)

            try:
                self.status.emit("Closing browser...")
                self._ctx.close()
                browser.close()
            except Exception:
                pass
            self.status.emit("Stopped.")

    def stop(self):
        self._stop = True

    def goto(self, url: str):
        with self._lock:
            if not self._page:
                self.log.emit("Browser not ready yet.")
                return
            self.status.emit(f"Navigating: {url}")
            self._page.goto(url, wait_until="domcontentloaded")
            self._page.wait_for_timeout(300)

    def scan_page(self):
        with self._lock:
            if not self._page:
                self.log.emit("Browser not ready yet.")
                return
            self.status.emit("Scanning DOM for fields...")
            fields = self._scan_dom(self._page)
            self.page_scanned.emit([asdict(f) for f in fields])
            self.status.emit(f"Scan complete: {len(fields)} elements.")

    def start_picker(self):
        with self._lock:
            if not self._page:
                return
            self._page.evaluate("window.__ra_picker && window.__ra_picker.start()")
            self.status.emit("Picker ON: click an element in the browser…")

    def poll_picker_once(self):
        with self._lock:
            if not self._page:
                return
            data = self._page.evaluate("window.__ra_picker ? window.__ra_picker.last : null")
            if data and data.get("selector"):
                self._page.evaluate("window.__ra_picker.last = null")
                self.picked.emit(data["selector"], data.get("meta") or {})

    def stop_picker(self):
        with self._lock:
            if not self._page:
                return
            self._page.evaluate("window.__ra_picker && window.__ra_picker.stop()")
            self.status.emit("Picker OFF.")

    def fill_and_click_safe(self, field_values: Dict[str, Tuple[str, str]], continue_selector: Optional[str]):
        with self._lock:
            if not self._page:
                return
            self.status.emit("Filling mapped fields...")
            for app_key, (sel, val) in field_values.items():
                if not sel:
                    continue
                try:
                    self._page.locator(sel).first.fill(val)
                    self.log.emit(f"Filled {app_key} -> {sel}")
                except Exception as e:
                    self.log.emit(f"FAILED fill {app_key} -> {sel}: {e}")

            if continue_selector:
                try:
                    self.status.emit("Clicking Continue/Next...")
                    self._page.locator(continue_selector).first.click()
                    self._page.wait_for_timeout(600)
                    self.log.emit(f"Clicked continue -> {continue_selector}")
                except Exception as e:
                    self.log.emit(f"FAILED click continue {continue_selector}: {e}")

            self.status.emit("Stopped before payment step (manual from here).")

    def click_selectors(self, selectors: List[str]):
        with self._lock:
            if not self._page:
                return
            for sel in selectors:
                if not sel:
                    continue
                try:
                    self._page.locator(sel).first.click()
                    self._page.wait_for_timeout(200)
                    self.log.emit(f"Clicked -> {sel}")
                except Exception as e:
                    self.log.emit(f"FAILED click {sel}: {e}")

    def _scan_dom(self, page: Page) -> List[PageField]:
        js = r"""
(() => {
  function labelFor(el) {
    const id = el.getAttribute('id');
    if (id) {
      const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (lab) return lab.innerText.trim();
    }
    let p = el.parentElement;
    for (let i=0; i<3 && p; i++) {
      if (p.tagName && p.tagName.toLowerCase() === 'label') return p.innerText.trim();
      p = p.parentElement;
    }
    return '';
  }

  function bestSelector(el){
    const tag = el.tagName.toLowerCase();
    const id = el.getAttribute('id');
    if (id) return `${tag}#${CSS.escape(id)}`;
    const tid = el.getAttribute('data-testid');
    if (tid) return `${tag}[data-testid="${tid}"]`;
    const name = el.getAttribute('name');
    if (name) return `${tag}[name="${name}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `${tag}[aria-label="${aria.replace(/"/g,'\\\"')}"]`;
    const placeholder = el.getAttribute('placeholder');
    if (placeholder) return `${tag}[placeholder="${placeholder.replace(/"/g,'\\\"')}"]`;
    return '';
  }

  const nodes = Array.from(document.querySelectorAll('input, select, textarea, button, [role="button"]'));
  return nodes.slice(0, 700).map(el => {
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type') || '';
    const name = el.getAttribute('name') || '';
    const id = el.getAttribute('id') || '';
    const placeholder = el.getAttribute('placeholder') || '';
    const aria = el.getAttribute('aria-label') || '';
    const role = el.getAttribute('role') || '';
    const label = labelFor(el) || '';
    const text = (el.innerText || '').trim().slice(0, 120);
    const sel = bestSelector(el);
    return { tag, type, name, id, placeholder, aria, role, label, text, selector: sel };
  });
})();
"""
        raw = page.evaluate(js)
        out: List[PageField] = []
        for r in raw:
            label_hint = (r.get("label") or r.get("aria") or r.get("placeholder") or r.get("text") or "").strip()
            tag = r.get("tag") or ""
            input_type = r.get("type") or ""
            name = r.get("name") or ""
            _id = r.get("id") or ""
            placeholder = r.get("placeholder") or ""
            aria_label = r.get("aria") or ""
            role = r.get("role") or ""
            selector = r.get("selector") or ""
            conf = self._confidence(label_hint, name, _id, selector)
            out.append(PageField(
                label_hint=label_hint,
                tag=tag,
                input_type=input_type,
                name=name,
                id=_id,
                placeholder=placeholder,
                aria_label=aria_label,
                role=role,
                selector=selector,
                confidence=conf
            ))
        out.sort(key=lambda f: f.confidence, reverse=True)
        return out

    def _confidence(self, label_hint: str, name: str, _id: str, selector: str) -> float:
        score = 0.0
        if selector: score += 0.4
        if _id: score += 0.25
        if name: score += 0.2
        if label_hint: score += 0.15
        if not (selector or name or _id):
            score -= 0.3
        return max(0.0, min(1.0, score))
