import re
from urllib.parse import urlparse
from typing import List, Dict

def domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"

def normalize_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()

_HTML_ATTR_PATTERNS = {
    "id": re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "name": re.compile(r'\bname\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "data-testid": re.compile(r'\bdata-testid\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "aria-label": re.compile(r'\baria-label\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "placeholder": re.compile(r'\bplaceholder\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "for": re.compile(r'\bfor\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    "type": re.compile(r'\btype\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
}

_TAG_PATTERN = re.compile(r'<\s*(input|select|textarea|button)\b([^>]*)>', re.IGNORECASE)
_LABEL_PATTERN = re.compile(r'<\s*label\b([^>]*)>(.*?)<\s*/\s*label\s*>', re.IGNORECASE | re.DOTALL)

def extract_selector_suggestions(html: str) -> List[Dict[str, str]]:
    """Lightweight HTML snippet helper.
    Parses input/select/textarea/button tags and label[for] to suggest stable selectors.
    No external deps.
    """
    html = html or ""
    suggestions: List[Dict[str, str]] = []

    # label for mapping
    label_map = {}
    for m in _LABEL_PATTERN.finditer(html):
        attrs = m.group(1) or ""
        inner = re.sub(r'<[^>]+>', ' ', m.group(2) or "")
        inner = " ".join(inner.split()).strip()
        fm = _HTML_ATTR_PATTERNS["for"].search(attrs)
        if fm:
            label_map[fm.group(1)] = inner

    for m in _TAG_PATTERN.finditer(html):
        tag = (m.group(1) or "").lower()
        attrs = m.group(2) or ""
        attr_vals = {k: (pat.search(attrs).group(1) if pat.search(attrs) else "") for k, pat in _HTML_ATTR_PATTERNS.items()}
        _id = attr_vals.get("id","")
        name = attr_vals.get("name","")
        tid = attr_vals.get("data-testid","")
        aria = attr_vals.get("aria-label","")
        placeholder = attr_vals.get("placeholder","")
        typ = attr_vals.get("type","")

        label = label_map.get(_id,"")
        hint = label or aria or placeholder or name or _id or tid

        # prioritize stable selectors
        sel = ""
        if _id:
            sel = f"{tag}#{css_escape(_id)}"
        elif tid:
            sel = f'{tag}[data-testid="{tid}"]'
        elif name:
            sel = f'{tag}[name="{name}"]'
        elif aria:
            sel = f'{tag}[aria-label="{aria}"]'
        elif placeholder:
            sel = f'{tag}[placeholder="{placeholder}"]'

        if sel:
            suggestions.append({
                "tag": tag,
                "type": typ,
                "hint": hint,
                "selector": sel
            })

    # de-dupe by selector
    seen = set()
    out = []
    for s in suggestions:
        if s["selector"] in seen:
            continue
        seen.add(s["selector"])
        out.append(s)
    return out

def css_escape(s: str) -> str:
    # simple escape for ids; good enough for most real-world ids
    return re.sub(r'([ #;?%&,.+*~\':"!^$\[\]()`=>|/@])', r'\\\1', s)
