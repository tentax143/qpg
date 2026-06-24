"""
Intelligent material ingestion helpers.

Two capabilities, both used ONLY from the async ingest tasks (never in a web request):

  * detect_unit_name()    — read a PDF's first pages and name the chapter/unit it belongs to,
                            snapping to the official CBSE chapter list when one matches, so a
                            file with a random name (e.g. "scan_final_v2.pdf") still gets a clean,
                            consistent unit.
  * detect_book_chapters() — split a whole-textbook PDF into per-chapter page ranges using the
                            PDF's embedded bookmarks/outline, falling back to scanning pages for
                            "Chapter N" / "Unit N" style headings.

Everything here is best-effort and defensive: any failure returns a sensible fallback (the
filename-based name, or a single whole-file chapter) so an ordinary upload never breaks.
"""
import os
import re
import json
from difflib import SequenceMatcher

from PyPDF2 import PdfReader

from . import mantle_client


# ── PDF text extraction (page-range aware) ────────────────────────────────────
def extract_pages_text(pdf_path, start=0, end=None, max_chars=None) -> str:
    """Extract text from pages [start, end). Robust: PyPDF2 first, pdfplumber per-page fallback.
    Returns "" on total failure (never raises)."""
    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"[MaterialIntel] cannot open '{os.path.basename(pdf_path)}': {e}")
        return ""
    n = len(reader.pages)
    end = n if end is None else min(end, n)
    parts = []
    for i in range(max(0, start), end):
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception:
            try:
                import pdfplumber
                with pdfplumber.open(pdf_path) as pdf:
                    if i < len(pdf.pages):
                        parts.append(pdf.pages[i].extract_text() or "")
            except Exception:
                pass
        if max_chars and sum(len(p) for p in parts) >= max_chars:
            break
    text = "\n".join(parts)
    return text[:max_chars] if max_chars else text


def page_count(pdf_path) -> int:
    try:
        return len(PdfReader(pdf_path).pages)
    except Exception:
        return 0


# ── Canonical CBSE chapter catalog (for consistent naming) ────────────────────
def _canonical_chapters(subject) -> list:
    """Official chapter names for this subject from UNIT_MARKS_WEIGHTS, or [] if unknown."""
    try:
        from .data.cbse_patterns import UNIT_MARKS_WEIGHTS
    except Exception:
        return []
    s = (subject or "").strip().lower()
    for key, weights in UNIT_MARKS_WEIGHTS.items():
        if key.lower() == s or key.lower() in s or s in key.lower():
            return list(weights.keys())
    return []


def _snap_to_catalog(name, subject) -> str:
    """Snap a detected chapter name to the closest official catalog name (so units stay
    consistent with what patterns/generation expect). Returns the original if no good match."""
    name = (name or "").strip()
    catalog = _canonical_chapters(subject)
    if not name or not catalog:
        return name
    nl = name.lower()
    best, best_score = name, 0.0
    for canon in catalog:
        cl = canon.lower()
        if cl == nl or cl in nl or nl in cl:
            return canon
        score = SequenceMatcher(None, nl, cl).ratio()
        if score > best_score:
            best, best_score = canon, score
    return best if best_score >= 0.72 else name


# Chapter/lesson markers in English, Hindi (अध्याय/पाठ) and Tamil (அத்தியாயம்/பாடம்/பகுதி).
_CH_WORDS = r'chapter|unit|lesson|ch|अध्याय|पाठ|அத்தியாயம்|பாடம்|பகுதி'
_CLEAN_NAME_RE = re.compile(rf'^({_CH_WORDS})\s*[-.:]?\s*[\d०-९௦-௯]+\s*[-.:]?\s*', re.IGNORECASE)


def _clean_name(raw) -> str:
    """Tidy a raw chapter title: strip zero-width chars, drop a leading 'Chapter 4 -' style
    prefix, collapse spaces."""
    s = re.sub(r'[​-‍﻿]', '', str(raw or ''))   # ZWSP/ZWNJ/ZWJ/BOM
    s = re.sub(r'\s+', ' ', s).strip().strip('.-: ')
    s = _CLEAN_NAME_RE.sub('', s).strip()
    return s


# ── Unit-name detection (single chapter / single PDF) ─────────────────────────
def detect_unit_name(pdf_path, class_name, subject, sample_text=None) -> str | None:
    """Identify the chapter/unit a PDF (or text sample) belongs to. Returns a clean unit name,
    snapped to the CBSE catalog when it matches, or None if nothing usable could be extracted."""
    sample = sample_text if sample_text is not None else extract_pages_text(pdf_path, 0, 3, max_chars=2500)
    if not (sample or "").strip():
        return None

    catalog = _canonical_chapters(subject)
    if catalog:
        cat_block = (
            "Pick the SINGLE best match from this official chapter list and return its EXACT name. "
            "If none fits, return a short, clean chapter name of your own:\n"
            + "\n".join(f"- {c}" for c in catalog) + "\n\n"
        )
    else:
        cat_block = "Return a short, clean chapter/unit name (no 'Chapter N' prefix).\n\n"

    prompt = (
        f"You are cataloguing a CBSE Class {class_name} {subject} textbook PDF.\n"
        f"Identify which chapter/unit the following text is from.\n\n"
        f"{cat_block}"
        f"TEXT (first pages):\n---\n{sample[:2500]}\n---\n\n"
        'Return ONLY JSON: {"chapter": "the chapter name"}'
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.VAL_MODEL, prompt=prompt, max_tokens=120, temperature=0.1,
        )
        m = re.search(r'\{.*\}', raw, re.S)
        name = (json.loads(m.group()).get("chapter") if m else "") or ""
    except Exception as e:
        print(f"[MaterialIntel] name detection failed: {e}")
        return None

    name = _clean_name(name)
    if not name:
        return None
    return _snap_to_catalog(name, subject)


# ── Whole-book chapter splitting ──────────────────────────────────────────────
_CHAPTER_HEADING_RE = re.compile(
    rf'^\s*({_CH_WORDS})\s*[-.:]?\s*([\d०-९௦-௯]+)', re.IGNORECASE | re.MULTILINE
)


def _flatten_outline(reader):
    """Yield (title, page_index) for every entry in the PDF outline, depth-first. Empty if none."""
    out = []

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
                continue
            try:
                title = (getattr(it, "title", None) or "").strip()
                page = reader.get_destination_page_number(it)
                if title and page is not None:
                    out.append((title, int(page)))
            except Exception:
                continue

    try:
        walk(reader.outline)
    except Exception:
        return []
    return out


def _ranges_from_starts(starts_titles, total_pages):
    """Turn [(title, start_page), ...] (sorted, deduped) into [{unit,start_page,end_page}]."""
    seen, cleaned = set(), []
    for title, pg in sorted(starts_titles, key=lambda x: x[1]):
        if pg in seen:
            continue
        seen.add(pg)
        cleaned.append((title, pg))
    chapters = []
    for idx, (title, pg) in enumerate(cleaned):
        end = cleaned[idx + 1][1] if idx + 1 < len(cleaned) else total_pages
        if end <= pg:
            continue
        chapters.append({"unit": _clean_name(title) or title.strip(),
                         "start_page": pg, "end_page": end})
    return chapters


def detect_book_chapters(pdf_path, class_name, subject, refine_names=True) -> list:
    """Split a whole-textbook PDF into per-chapter page ranges.

    Strategy: PDF bookmarks/outline first (most reliable — titles + start pages), else scan
    each page for a 'Chapter N' / 'Unit N' heading. Returns
    [{"unit", "start_page", "end_page"}, ...] (page indices, end exclusive). Returns [] if it
    can't find at least 2 chapters (caller then treats the file as a single unit)."""
    total = page_count(pdf_path)
    if total < 2:
        return []

    chapters = []
    # 1) Embedded outline / bookmarks.
    try:
        reader = PdfReader(pdf_path)
        outline = _flatten_outline(reader)
        # Keep entries that look like real chapters (named, and ideally chapter-like titles).
        starts = [(t, p) for t, p in outline if t and len(t) > 2]
        if len(starts) >= 2:
            chapters = _ranges_from_starts(starts, total)
    except Exception as e:
        print(f"[MaterialIntel] outline read failed: {e}")

    # 2) Heading-regex fallback (per page).
    if len(chapters) < 2:
        starts = []
        for i in range(total):
            head = extract_pages_text(pdf_path, i, i + 1, max_chars=400)
            m = _CHAPTER_HEADING_RE.search(head or "")
            if m:
                # Use the line after the "Chapter N" marker as the title when available.
                after = (head[m.end():].strip().splitlines() or [""])[0].strip()
                starts.append((after or f"Chapter {m.group(2)}", i))
        if len(starts) >= 2:
            chapters = _ranges_from_starts(starts, total)

    if len(chapters) < 2:
        return []

    # 3) Optionally refine each chapter's name from its own first page (snaps to catalog).
    if refine_names:
        for ch in chapters:
            sample = extract_pages_text(pdf_path, ch["start_page"], ch["start_page"] + 2, max_chars=2000)
            better = detect_unit_name(pdf_path, class_name, subject, sample_text=sample)
            if better:
                ch["unit"] = better
            else:
                ch["unit"] = _snap_to_catalog(ch["unit"], subject)

    # Drop any with an empty/blank unit after cleaning.
    return [c for c in chapters if c.get("unit")]


# ── HTML book ingestion (e.g. the TN-schools textbooks served as one HTML page) ──
_HTML_CH_MARKER = re.compile(
    r'(இயல்|பாடம்|அத்தியாயம்|பகுதி|पाठ|अध्याय|chapter|unit|lesson)', re.IGNORECASE
)


def fetch_url(url, timeout=30, max_bytes=25_000_000) -> str:
    """Download an HTML page as text (browser UA, size-capped). Raises on HTTP error."""
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (compatible; QPG-MaterialImporter/1.0)"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    raw = r.content[:max_bytes]
    enc = r.encoding or "utf-8"
    return raw.decode(enc, errors="replace")


def _choose_heading_level(body):
    """Pick the heading level (h1/h2/h3) that best segments the book into chapters: the level
    with the most headings that contain a chapter marker (இயல்/Chapter/…); else the shallowest
    level with a sane chapter count. None if nothing usable."""
    best_lvl, best_marked = None, 0
    for lvl in ("h1", "h2", "h3"):
        hs = body.find_all(lvl)
        if len(hs) < 2:
            continue
        marked = sum(1 for h in hs if _HTML_CH_MARKER.search(h.get_text(" ", strip=True)))
        if marked > best_marked:
            best_lvl, best_marked = lvl, marked
    if best_lvl and best_marked >= 1:
        return best_lvl
    for lvl in ("h1", "h2", "h3"):
        hs = body.find_all(lvl)
        if 2 <= len(hs) <= 80:
            return lvl
    return None


def extract_html_chapters(html, subject=None) -> list:
    """Split a whole-book HTML page into per-chapter {unit, text} using heading tags as
    boundaries. Returns [] only if there's no usable text. A single-chapter result (unit=None)
    means the page couldn't be segmented and should be ingested as one unit."""
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    body = soup.body or soup
    level = _choose_heading_level(body)

    if not level:
        text = re.sub(r'\n{3,}', '\n\n', body.get_text("\n")).strip()
        return [{"unit": None, "text": text}] if len(text) > 50 else []

    chapters, current, buf = [], None, []
    heading_tags = {"h1", "h2", "h3", "h4"}

    def flush():
        if current and buf:
            txt = re.sub(r'[ \t]+', ' ', "".join(buf))
            txt = re.sub(r'\n{3,}', '\n\n', txt).strip()
            if len(txt) > 50:
                chapters.append({"unit": _clean_name(current) or current.strip(), "text": txt})

    for node in body.descendants:
        if isinstance(node, Tag) and node.name == level:
            flush()
            buf = []
            current = node.get_text(" ", strip=True)
        elif isinstance(node, NavigableString):
            parent = node.parent
            if parent is not None and isinstance(parent, Tag) and parent.name in heading_tags:
                continue  # heading text is captured as the unit name, not body text
            s = str(node).strip()
            if s:
                buf.append(s + "\n")
    flush()
    return chapters
