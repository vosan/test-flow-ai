"""
SelectorResolver: Deterministically resolve human-friendly targets into CSS selectors.

Inputs:
- target: string (e.g., "login button", "username", "search", etc.)
- page_source: full HTML of the current page
- current_url: current page URL (not currently used in scoring, reserved for future hints)

Algorithm overview:
1) If the target already looks like a CSS selector (e.g., contains '#', '.', '[...]', '>' or ':'),
   return it as-is with confidence = 1.0.
2) Parse the DOM and extract candidate elements and their identifying signals from:
   - id, name, class tokens, aria-label, placeholder, text (stripped)
3) Score candidates by comparing the normalized target to each signal.
   - Exact match > prefix/suffix > substring > token overlap
   - Weighted by attribute importance: id > aria-label/placeholder > name > text > class
4) Return the best candidate as a CSS selector with a confidence in [0.0, 1.0].

Notes:
- CSS selectors are preferred. When possible, use #id. Otherwise, synthesize a robust attribute selector
  like input[name="q"], [aria-label="Search"], [placeholder="Email"], or tag with limited class tokens.
- Deterministic only; no AI fallback.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional
import re
from bs4 import BeautifulSoup


def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    # Remove surrounding quotes
    if len(s) >= 2 and ((s[0] == s[-1]) and s[0] in {'"', "'"}):
        s = s[1:-1].strip()
    return s


def _tokenize(s: str) -> List[str]:
    # Split on non-alphanum to get meaningful tokens
    return [t for t in re.split(r"[^a-z0-9]+", _normalize_text(s)) if t]


def _looks_like_selector(s: str) -> bool:
    if not isinstance(s, str):
        return False
    raw = s.strip()
    if not raw:
        return False
    if raw.lower() in {"page", "active_element"}:
        return False
    # Heuristic: presence of CSS-specific characters suggests a selector
    css_chars = {'#', '.', '[', ']', '>', '=', ':', ','}
    if any(c in raw for c in css_chars):
        return True
    # Common tag-prefixed selectors like "button.btn" or "input[name=...]"
    if re.search(r"^[a-zA-Z][a-zA-Z0-9]*\.", raw):
        return True
    if re.search(r"^[a-zA-Z][a-zA-Z0-9]*\[", raw):
        return True
    return False


def _css_escape_attr_value(v: str) -> str:
    # Minimal escaping for inclusion inside double quotes in attribute selectors
    return (v or "").replace("\\", "\\\\").replace('"', '\\"')


def _is_valid_simple_ident(s: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_\-\.]*$", s or ""))


def _build_selector(el) -> str:
    tag = el.name or "*"
    el_id = el.get("id")
    if el_id and _is_valid_simple_ident(el_id) and ' ' not in el_id:
        # Prefer simple #id when safe
        return f"#{el_id}"

    # Prefer specific tag when available
    def attr_sel(attr: str, val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        v = _css_escape_attr_value(val)
        # Use tag-qualified selectors when element is a common form/control
        tag_pref = tag if tag in {"input", "button", "a", "select", "textarea", "label", "div", "span"} else "*"
        return f"{tag_pref}[{attr}=\"{v}\"]"

    sel = (
        attr_sel("id", el.get("id"))
        or attr_sel("name", el.get("name"))
        or attr_sel("aria-label", el.get("aria-label"))
        or attr_sel("placeholder", el.get("placeholder"))
    )
    if sel:
        return sel

    # Try class tokens (limit to 2 for stability)
    classes = el.get("class") or []
    classes = [c for c in classes if _is_valid_simple_ident(c)]
    if classes:
        limited = classes[:2]
        return f"{tag}{''.join('.' + c for c in limited)}"

    # Fallback to tag
    return tag


def _attribute_signals(el, broaden: bool = False) -> List[Tuple[str, float]]:
    """Return (text, weight) pairs for this element's identifying signals.

    When broaden=True, include additional attributes that may hint at intent.
    """
    out: List[Tuple[str, float]] = []
    # Strong identifiers
    if el.get("id"):
        out.append((str(el.get("id")), 1.0))
    if el.get("aria-label"):
        out.append((str(el.get("aria-label")), 0.95))
    if el.get("placeholder"):
        out.append((str(el.get("placeholder")), 0.9))
    if el.get("name"):
        out.append((str(el.get("name")), 0.85))
    # Visible text (strip whitespace)
    text = el.get_text(strip=True)
    if text:
        out.append((text, 0.8))
    # Class tokens (joined for matching)
    classes = el.get("class") or []
    if classes:
        out.append((" ".join(map(str, classes)), 0.6))

    if broaden:
        # Include additional attributes that might describe the element
        if el.get("title"):
            out.append((str(el.get("title")), 0.8))
        if el.get("data-testid"):
            out.append((str(el.get("data-testid")), 0.9))
        if el.get("alt"):
            out.append((str(el.get("alt")), 0.75))
        if el.get("value"):
            out.append((str(el.get("value")), 0.8))
        if el.get("type"):
            out.append((str(el.get("type")), 0.5))
        if el.get("role"):
            out.append((str(el.get("role")), 0.5))
    return out


def _score_match(target: str, candidate: str) -> float:
    t = _normalize_text(target)
    c = _normalize_text(candidate)
    if not t or not c:
        return 0.0
    if t == c:
        return 1.0
    if c.startswith(t) or c.endswith(t) or t.startswith(c) or t.endswith(c):
        return 0.85
    if t in c:
        return 0.75
    # Token overlap (Jaccard)
    tt = set(_tokenize(t))
    cc = set(_tokenize(c))
    if not tt or not cc:
        return 0.0
    inter = len(tt & cc)
    union = len(tt | cc)
    if union == 0:
        return 0.0
    j = inter / union
    return 0.6 * j


class SelectorResolver:
    def resolve(self, target: str, page_source: str, current_url: str, broaden: bool = False) -> Dict[str, object]:
        """
        Resolve a target string to a CSS selector using deterministic DOM analysis.

        Parameters:
            target: Human-friendly description or a CSS selector.
            page_source: Current page HTML.
            current_url: Current URL (reserved for future use).
            broaden: If True, widen the candidate pool and include additional attributes.

        Returns: {"selector": string, "confidence": float}
        """
        # 1) Pass-through if target already looks like a selector
        if _looks_like_selector(target):
            return {"selector": target, "confidence": 1.0}

        # 2) Parse DOM
        soup = BeautifulSoup(page_source or "", "html.parser")

        # Short-circuit for special sentinel targets
        tnorm = _normalize_text(target)
        if tnorm in {"page", "active_element"}:
            return {"selector": tnorm, "confidence": 1.0}

        best = (None, 0.0)  # (element, score)

        # Consider common interactive/relevant tags first; broaden mode includes all elements too
        preferred_tags = [
            "input",
            "button",
            "a",
            "textarea",
            "select",
            "label",
            "div",
            "span",
        ]

        # Phase 1: preferred + common attribute-bearing elements
        candidates_phase1: List = []
        for tag in preferred_tags:
            candidates_phase1.extend(soup.find_all(tag))
        candidates_phase1.extend(soup.select('[aria-label], [placeholder]'))

        # Deduplicate while preserving order
        seen = set()
        uniq_candidates_phase1 = []
        for el in candidates_phase1:
            key = id(el)
            if key in seen:
                continue
            seen.add(key)
            uniq_candidates_phase1.append(el)

        target_norm = _normalize_text(target)

        def score_candidates(candidates_list: List) -> Tuple[Optional[object], float]:
            local_best = (None, 0.0)
            for el in candidates_list:
                signals = _attribute_signals(el, broaden=broaden)
                if not signals:
                    continue
                # Base score from best-matching signal with its weight
                sig_scores = [
                    _score_match(target_norm, text) * weight for (text, weight) in signals
                ]
                if not sig_scores:
                    continue
                score = max(sig_scores)
                # Bonuses for interactable elements
                if el.name in {"button", "a"}:
                    score += 0.1 if broaden else 0.05
                if el.name == "input" and (el.get("type") in {"submit", "button", "search"} or el.get("onclick")):
                    score += 0.1 if broaden else 0.05
                if el.get("role") == "button":
                    score += 0.1 if broaden else 0.05
                if score > local_best[1]:
                    local_best = (el, score)
            return local_best

        best = score_candidates(uniq_candidates_phase1)

        # Phase 2 (broaden): only if requested AND no strong candidate yet
        if broaden and (best[0] is None or best[1] < 0.5):
            # Include all elements as a last resort
            candidates_phase2 = []
            for el in soup.find_all(True):
                key = id(el)
                if key in seen:
                    continue
                seen.add(key)
                candidates_phase2.append(el)
            best2 = score_candidates(candidates_phase2)
            if best2[0] is not None and best2[1] > best[1]:
                best = best2

        if best[0] is None:
            # Nothing matched at all
            return {"selector": target, "confidence": 0.0}

        selector = _build_selector(best[0])
        # Clamp confidence to [0,1]
        confidence = max(0.0, min(1.0, best[1]))
        # Apply explicit damping in broaden mode to avoid overconfidence
        if broaden:
            confidence = max(0.0, min(1.0, confidence * 0.90))
        return {"selector": selector, "confidence": confidence}
