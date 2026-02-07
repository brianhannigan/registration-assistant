# Registration Assistant (Stops Before Payment)

Desktop GUI (PySide6) + Playwright automation helper for **registration forms**.

✅ Fills mapped non-payment fields  
✅ Selects sessions/weeks by clicking mapped elements  
✅ Clicks Continue/Next (optional)  
🛑 **Stops before payment** (no card autofill, no payment submit)

## Why it stops before payment
This project is designed for legitimate form assistance and QA workflows and intentionally does **not** automate payment entry or submission.

---

## Features

- **Browser automation** via Playwright (Chromium)
- **DOM scanner** to list inputs/selects/textareas/buttons and show suggested selectors
- **Pick-from-page**: click any element in the browser to capture a stable CSS selector
- **Drag/drop mapping**: drag a detected element onto a mapping row
- **Sessions/Weeks**:
  - Checkbox list in the GUI
  - Per-session **Pick** button to bind to an element on the page
  - Clicks mapped session elements during run
- **HTML snippet helper**:
  - Paste HTML fragment
  - Generate selector suggestions based on `id`, `name`, `data-testid`, `aria-label`, `placeholder`
  - Apply a suggestion to the selected mapping row
- **Per-domain persistent mappings** stored in `mappings/<domain>.json`

---

## Install

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python main.py
```

---

## Basic Use

1. Enter a URL → **Go**
2. Click **Scan Page**
3. Map fields:
   - Use **Pick** on a mapping row and click the corresponding element in the browser
   - or drag an item from the detected element list onto a mapping row
4. Map sessions:
   - Check the session(s) you want
   - Click **Pick** next to each session and click its checkbox/row element in the browser
5. (Optional) Pick **Continue/Next**
6. Click **Run (Stop Before Payment)**

At that point, the assistant stops and you complete any payment manually.

---

## Notes & Tips

- Prefer stable selectors:
  - `#id`
  - `[data-testid="..."]`
  - `[name="..."]`
  - `[aria-label="..."]`
- If a field has no good selector, always use **Pick**.
- Some sites embed inputs inside iframes; you may need to pick elements carefully.

---

## License
MIT (add/change as you wish)
