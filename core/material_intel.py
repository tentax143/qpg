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
    # Legacy non-Unicode font (Walkman-Chanakya905 / Kruti Dev / DevLys) → extracted bytes are ASCII
    # gibberish; transcode to real Unicode Devanagari so naming/heading detection works. No-op for
    # ordinary Unicode/Latin PDFs (their embedded fonts don't match the legacy-font list).
    from . import legacy_font
    text = legacy_font.decode_if_legacy(pdf_path, text)
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


# Chapter/lesson markers in English, Hindi (अध्याय/पाठ) and Tamil. Tamil textbooks (Samacheer
# Kalvi) organise mostly by இயல் (iyal), also பாடம்/அத்தியாயம்/பகுதி/அலகு/பருவம் — keep this in
# sync with _HTML_CH_MARKER below (the HTML-import path uses the same marker set).
_CH_WORDS = r'chapter|unit|lesson|ch|अध्याय|पाठ|அத்தியாயம்|பாடம்|பகுதி|இயல்|அலகு|பருவம்'
_CLEAN_NAME_RE = re.compile(rf'^({_CH_WORDS})\s*[-.:]?\s*[\d०-९௦-௯]+\s*[-.:]?\s*', re.IGNORECASE)


_TITLE_SMALL_WORDS = {"a", "an", "and", "the", "of", "to", "in", "on", "at", "for",
                      "by", "with", "from", "as", "or", "nor", "but"}


def _smart_titlecase(s) -> str:
    """Normalise a lesson title. Small-caps display fonts extract with random inner caps
    ('The fifTh Word', 'MagneTiC hills'), so lowercase every word then capitalise it — keeping
    common small words lower unless first. Fixes the mangled casing into a clean title."""
    s = (s or "").strip()
    if not s:
        return s
    words = s.split()
    out = []
    for k, w in enumerate(words):
        lw = w.lower()
        out.append(lw if (k != 0 and lw in _TITLE_SMALL_WORDS) else lw[:1].upper() + lw[1:])
    return " ".join(out)


def _clean_name(raw) -> str:
    """Tidy a raw chapter title: strip zero-width chars, drop a leading 'Chapter 4 -' style
    prefix, collapse spaces."""
    s = re.sub(r'[​-‍﻿]', '', str(raw or ''))   # ZWSP/ZWNJ/ZWJ/BOM
    s = re.sub(r'\s+', ' ', s).strip().strip('.-: ')
    s = _CLEAN_NAME_RE.sub('', s).strip()
    return s


# ── Legacy / unreadable-font detection ────────────────────────────────────────
# Expected Unicode block per Indic-script subject. Used to spot PDFs typeset in a legacy
# NON-Unicode font (e.g. Walkman-Chanakya905, Kruti Dev, DevLys): PyPDF2 extracts the raw
# keystrokes, so a Hindi chapter comes out as ASCII gibberish ("euq';rk") with ZERO characters
# in the real script block. Naming/embedding that text is worthless, so we bail to the filename.
_SCRIPT_RANGES = {
    "devanagari": (0x0900, 0x097F),   # Hindi, Sanskrit, Marathi
    "tamil":      (0x0B80, 0x0BFF),
    "telugu":     (0x0C00, 0x0C7F),
    "kannada":    (0x0C80, 0x0CFF),
    "malayalam":  (0x0D00, 0x0D7F),
    "bengali":    (0x0980, 0x09FF),
    "gujarati":   (0x0A80, 0x0AFF),
    "gurmukhi":   (0x0A00, 0x0A7F),   # Punjabi
    "odia":       (0x0B00, 0x0B7F),
}
_SUBJECT_SCRIPT = {
    "hindi": "devanagari", "sanskrit": "devanagari", "marathi": "devanagari",
    "tamil": "tamil", "telugu": "telugu", "kannada": "kannada", "malayalam": "malayalam",
    "bengali": "bengali", "bangla": "bengali", "gujarati": "gujarati",
    "punjabi": "gurmukhi", "odia": "odia", "oriya": "odia",
}


def _expected_script_range(subject):
    s = (subject or "").strip().lower()
    for key, script in _SUBJECT_SCRIPT.items():
        if key in s:
            return _SCRIPT_RANGES[script]
    return None


def text_is_unreadable_for_subject(sample, subject) -> bool:
    """True when `subject` is an Indic-script language but `sample` has almost no characters in
    that script — the PDF uses a legacy non-Unicode font (or is scanned), so its extracted text
    is unusable. Latin-script subjects (English, etc.) never trip this."""
    rng = _expected_script_range(subject)
    if not rng:
        return False
    lo, hi = rng
    in_script = sum(1 for c in (sample or "") if lo <= ord(c) <= hi)
    return in_script < 5


# ── Unit-name detection (single chapter / single PDF) ─────────────────────────
def detect_unit_name(pdf_path, class_name, subject, sample_text=None) -> str | None:
    """Identify the chapter/unit a PDF (or text sample) belongs to. Returns a clean unit name,
    snapped to the CBSE catalog when it matches, or None if nothing usable could be extracted."""
    sample = sample_text if sample_text is not None else extract_pages_text(pdf_path, 0, 3, max_chars=2500)
    if not (sample or "").strip():
        return None
    # Legacy non-Unicode font / scanned page → extracted text is gibberish; don't name from it.
    if text_is_unreadable_for_subject(sample, subject):
        print(f"[MaterialIntel] '{os.path.basename(pdf_path or '')}' ({subject}): text has no "
              f"{subject} script — legacy non-Unicode font or scanned; skipping auto-name")
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


def _detect_chapters_by_titlefont(pdf_path, total) -> list:
    """Split by the book's TITLE FONT — for professionally-typeset books that have NO bookmarks and
    NO 'Chapter N' markers (e.g. NCERT 'Poorvi' English: a unit contains prose + poems + a play,
    each headed only by a styled title). Lesson titles are short, CENTERED lines set in the same
    display font as the big unit/chapter header, positioned near the TOP of a page. Returns
    [{"unit", "start_page", "end_page"}] or [] if the signal isn't clear. Best-effort; never raises.

    Position (top-of-page) is essential: it excludes title-font words that appear mid/bottom of a
    page (a play's ending 'Curtain', a pull-quote). Titles are de-duped to their FIRST occurrence,
    which drops copies re-listed in an end-of-unit transcripts/answers appendix."""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer, LTTextLine, LTChar
        from collections import Counter
    except Exception:
        return []

    rows = []           # (page_idx, text, dominant_size, font, centered, top_frac)
    charcount = Counter()
    try:
        for i, page in enumerate(extract_pages(pdf_path)):
            pw, ph = (page.width or 1), (page.height or 1)
            for el in page:
                if not isinstance(el, LTTextContainer):
                    continue
                for line in el:
                    if not isinstance(line, LTTextLine):
                        continue
                    chars = [c for c in line if isinstance(c, LTChar)]
                    if not chars:
                        continue
                    txt = line.get_text().strip()
                    if not txt:
                        continue
                    size = Counter(round(c.size, 1) for c in chars).most_common(1)[0][0]
                    font = Counter(c.fontname for c in chars).most_common(1)[0][0].split('+')[-1]
                    cx = (line.x0 + line.x1) / 2
                    centered = abs(cx - pw / 2) < pw * 0.15
                    top_frac = (ph - line.y1) / ph
                    rows.append((i, txt, size, font, centered, top_frac))
                    charcount[(font, size)] += len(txt)
    except Exception as e:
        print(f"[MaterialIntel] title-font scan failed: {e}")
        return []

    if not charcount:
        return []
    body_font, _ = charcount.most_common(1)[0][0]
    head = [r for r in rows if r[0] <= 2]
    if not head:
        return []
    header = max(head, key=lambda r: r[2])          # biggest text on the first pages = unit header
    title_font, header_size = header[3], header[2]
    if title_font == body_font:                     # no distinct display font → not this kind of book
        return []

    hits = []
    for i, txt, size, font, centered, top_frac in rows:
        if font != title_font or size >= header_size * 0.9:   # skip the big unit header itself
            continue
        if not centered or top_frac > 0.40:                    # titles head a page (near the top)
            continue
        words = txt.split()
        if not (1 <= len(words) <= 12) or len(txt) > 80:
            continue
        if re.match(r'^\s*\d+\s*[.)]', txt):   # "1. …" / "4) …" is a numbered list item WITHIN a
            continue                            # lesson (e.g. items in an article), not a lesson title
        name = _smart_titlecase(_clean_name(txt) or txt.strip())
        hits.append((i, name))

    seen, first = set(), []
    for pg, txt in hits:
        key = txt.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        first.append((txt, pg))
    if len({pg for _, pg in first}) < 2:            # need ≥2 lessons on ≥2 pages
        return []
    return _ranges_from_starts(first, total)


def _clean_snippet(t) -> str:
    """Strip production/DTP noise that PyPDF2 often puts at the START of a page's extracted text
    (InDesign running footers like 'Unit 2.indd 55 13-05-2025 12:07:18', export dates/times, reprint
    stamps). This junk otherwise (a) trips the 'Unit N' heading regex on every page and (b) confuses
    the LLM into treating it as a heading."""
    t = t or ''
    # Whole InDesign footer chunk: an optional word, '.indd', then the trailing page-no/date/time run.
    t = re.sub(r'(?:[\w\-]+\s*)?\.indd\b[\s\d:.\-–]*', ' ', t, flags=re.IGNORECASE)
    t = re.sub(r'\d{1,2}-\d{1,2}-\d{2,4}', ' ', t)                    # 13-05-2025
    t = re.sub(r'\d{1,2}:\d{2}(:\d{2})?', ' ', t)                     # 12:07:18
    t = re.sub(r'Reprint\s*\d{4}[-–]\d{2,4}', ' ', t, flags=re.IGNORECASE)
    return t


def _detect_lessons_by_llm(pdf_path, class_name, subject, total) -> list:
    """Identify the real reading lessons/poems in a no-bookmark, un-numbered textbook unit PDF.

    HYBRID: the title-font heuristic supplies ACCURATE styled titles + positions (but includes
    activity headers and can miss a lesson); the LLM then reads each page's (cleaned) top text and
    returns the REAL lessons — filtering out 'Let us read/listen/…' activity headers, 'Column 1/2',
    phonetics and 'Transcripts', preferring a styled title where one matches, and adding any lesson
    the heuristic missed. Returns [{unit, start_page, end_page}] in page order, or [] on failure."""
    if total < 2 or total > 400:
        return []

    # Styled-title candidates (accurate wording + page) as hints — best-effort.
    styled = []
    try:
        for c in (_detect_chapters_by_titlefont(pdf_path, total) or []):
            styled.append((c["start_page"], c["unit"]))
    except Exception:
        pass

    # Cleaned top-text of every page (context so the LLM can catch a missed lesson / reject junk).
    lines = []
    for i in range(total):
        t = _clean_snippet(extract_pages_text(pdf_path, i, i + 1, max_chars=300) or "")
        t = re.sub(r'\s+', ' ', t).strip()[:180]
        if t:
            lines.append(f"p{i}: {t}")
    if len(lines) < 2:
        return []

    styled_block = ""
    if styled:
        styled_block = (
            "Lines VISUALLY STYLED AS TITLES in the PDF (page → styled text). Most real lesson/poem "
            "titles are among these — prefer their exact wording — but some are activity headers you "
            "must still exclude, and a real lesson may be missing from this list:\n"
            + "\n".join(f"  p{p}: {t}" for p, t in styled) + "\n\n"
        )

    prompt = (
        f"You are cataloguing a CBSE Class {class_name} {subject} textbook UNIT (one PDF) that contains "
        f"several READING LESSONS — prose texts and poems — each starting on its own page.\n\n"
        f"{styled_block}"
        f"Top text of every page (page index → text):\n" + "\n".join(lines) + "\n\n"
        f"Identify the page where each MAIN reading lesson or poem BEGINS, and its title. Prefer a "
        f"styled title above when it matches a lesson; otherwise use the page's own heading.\n"
        f"INCLUDE: prose lessons and poems (the actual reading texts).\n"
        f"EXCLUDE (never list): the unit's theme header (usually an all-caps unit name); the activity "
        f"headings 'Let us read', 'Let us listen', 'Let us learn', 'Let us think and reflect', "
        f"'Let us write', 'Let us speak', 'Let us explore'; layout labels 'Column 1'/'Column 2'; "
        f"grammar/phonetics headings; numbered list items; production/date stamps; and any "
        f"'Transcripts', 'Answers', 'Glossary' or reference section.\n\n"
        f'Return ONLY JSON: {{"lessons": [{{"page": <page index int>, "title": "<clean Title Case title>"}}]}} '
        f"in page order."
    )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL, prompt=prompt, max_tokens=800, temperature=0.1,
        )
    except Exception as e:
        print(f"[MaterialIntel] LLM split converse failed: {e}")
        return []
    m = re.search(r'\{.*\}', raw, re.S)
    if not m:
        return []
    try:
        lessons = json.loads(m.group()).get("lessons") or []
    except Exception:
        return []
    starts, seen = [], set()
    for it in lessons:
        if not isinstance(it, dict):
            continue
        try:
            pg = int(it.get("page"))
        except (TypeError, ValueError):
            continue
        title = _clean_name(str(it.get("title") or "")).strip()
        if title and 0 <= pg < total and pg not in seen:
            seen.add(pg)
            starts.append((title, pg))
    if len(starts) < 2:
        return []
    return _ranges_from_starts(starts, total)


def _toc_table_rows(pdf_path, page_idx) -> list:
    """Extract a contents page's rows via pdfplumber's TEXT-based table detection — for GRID-style,
    multi-column TOC layouts (e.g. Tamil Samacheer Kalvi's [unit no | theme | lesson title |
    evaluation | page | month] table) where a linear text dump (PyPDF2) interleaves columns and
    scrambles which page number belongs to which lesson. Returns
    [{"unit": "<str|None>", "text": "<row's non-numeric columns, concatenated>", "page": "<str|None>"}]
    in reading order, or [] if no usable grid is found (caller falls back to the raw-text method)."""
    try:
        import pdfplumber
    except Exception:
        return []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return []
            tables = pdf.pages[page_idx].extract_tables(
                {"vertical_strategy": "text", "horizontal_strategy": "text",
                 "snap_tolerance": 4, "join_tolerance": 4})
    except Exception:
        return []
    tables = [t for t in tables if t and len(t) >= 5 and max(len(r) for r in t) >= 3]
    if not tables:
        return []
    table = max(tables, key=lambda t: len(t) * max(len(r) for r in t))
    ncols = max(len(r) for r in table)
    rows = [list(r) + [""] * (ncols - len(r)) for r in table]

    def is_num(s):
        return bool(re.fullmatch(r"\s*\d{1,3}\s*", s or ""))

    # Page-number column: the rightmost column that's mostly short numbers.
    page_col = None
    for c in range(ncols - 1, -1, -1):
        vals = [rows[i][c] for i in range(len(rows)) if (rows[i][c] or "").strip()]
        if vals and sum(is_num(v) for v in vals) / len(vals) > 0.6:
            page_col = c
            break
    if page_col is None:
        return []
    # Drop leading HEADER rows (column-label text like "Page No.") before the first row with a
    # genuine page number — they pollute the is_num()-based unit-column detection below.
    header_end = next((i for i in range(len(rows)) if is_num(rows[i][page_col])), 0)
    rows = rows[header_end:]

    # Unit-number column: another column, ALL-numeric, small ints, one entry per unit (sparse).
    unit_col = None
    for c in range(ncols):
        if c == page_col:
            continue
        vals = [rows[i][c] for i in range(len(rows)) if (rows[i][c] or "").strip()]
        if len(vals) >= 2 and all(is_num(v) and int(v) <= 30 for v in vals):
            unit_col = c
            break

    text_cols = [c for c in range(ncols) if c not in (page_col, unit_col)]
    out = []
    for r in rows:
        u = (r[unit_col] if unit_col is not None else "").strip()
        text = " ".join(x for x in (r[c].strip() for c in text_cols) if x)
        pg = (r[page_col] or "").strip()
        pg = pg if is_num(pg) else ""
        if not text and not pg:
            continue
        out.append({"unit": u or None, "text": text, "page": pg or None})

    # Merge a text-only continuation row (line-wrap of the previous title) into the previous entry.
    merged = []
    for row in out:
        if row["text"] and not row["page"] and not row["unit"] and merged:
            merged[-1]["text"] = (merged[-1]["text"] + " " + row["text"]).strip()
        else:
            merged.append(row)
    return [r for r in merged if r["text"] or r["page"]]


def parse_book_contents(pdf_path) -> dict:
    """Parse a textbook's prelims/contents PDF into {title, units:[{unit,theme,lessons:[{title,page}]}]}.
    Finds the contents page(s); prefers a GRID-TABLE extraction (_toc_table_rows, handles multi-column
    layouts like Tamil Samacheer Kalvi where a linear text dump scrambles which page belongs to which
    lesson), falling back to the raw-text method for simple non-tabular contents lists (e.g. NCERT
    'Poorvi' English). Then LLM-parses the result. Returns {"title":"", "units":[]} on failure."""
    total = page_count(pdf_path)
    if total < 1:
        return {"title": "", "units": []}
    # Pick the REAL contents page(s): those with several "Title …… <page number>" lines. This avoids
    # the Foreword / 'About the Book' pages, which describe every unit in PROSE (mentioning lesson
    # titles in sentences, no page numbers) — mixing those in confuses the parse and can push the
    # real TOC past the prompt's length cap.
    toc_line = re.compile(r'\S.*?\s+[\d௦-௯]{1,3}\s*$', re.M)   # a TOC entry: "…title…   123"
    scored = []
    for i in range(min(total, 40)):
        t = _clean_snippet(extract_pages_text(pdf_path, i, i + 1, max_chars=3500) or "")
        score = len(toc_line.findall(t))
        if score >= 3:
            scored.append((i, t, score))
    if not scored:
        return {"title": "", "units": []}
    best_i = max(scored, key=lambda x: x[2])[0]

    table_rows = _toc_table_rows(pdf_path, best_i)
    if len(table_rows) >= 4:
        lines = []
        for r in table_rows:
            bits = []
            if r["unit"]:
                bits.append(f'unit={r["unit"]}')
            bits.append(f'text="{r["text"]}"')
            if r["page"]:
                bits.append(f'page={r["page"]}')
            lines.append("  " + " ".join(bits))
        toc_text = "\n".join(lines)
        prompt = (
            "Below are ROWS extracted from a school textbook's CONTENTS page, in reading order. Each "
            "row's page number is reliably paired with that row's text.\n\n"
            "A row carrying a 'unit=' number STARTS a new unit. Its 'text' glues the unit's THEME "
            "together with its FIRST lesson's title — split them apart, do NOT drop the first lesson. "
            "In many Indian-language textbooks (e.g. Tamil Samacheer Kalvi) the THEME is a single "
            "short category word right after the unit number (like மொழி='Language', "
            "இயற்கை='Nature', கல்வி='Education') and everything after it on that row is the first "
            "lesson's (longer) title.\n\n"
            "Some row text is visually mangled/reordered by PDF extraction (e.g. 'இயற்றக' should "
            "read 'இயற்கை', 'ேமிழ்' should read 'தமிழ்') — use your knowledge of the subject to "
            "recover the correct spelling of both themes and titles.\n\n"
            "Ignore front-matter rows (Foreword, Preface, About the Book, evaluation/assessment "
            "column headers, month names) and trailing footnote-key text unrelated to a lesson title "
            "(e.g. text after a '(*)' marker explaining what '*' means) — drop it, don't append it "
            "to a lesson title.\n\n"
            f"ROWS:\n{toc_text[:6000]}\n\n"
            'Return ONLY JSON: {"title": "<book name if shown else empty>", "units": [{"unit": <int>, '
            '"theme": "<unit theme>", "lessons": [{"title": "<full lesson title>", "page": <printed page int>}]}]}'
        )
    else:
        # Simple non-tabular contents list (no usable grid found) — raw-text method.
        toc_pages = [t for i, t, s in sorted(scored) if abs(i - best_i) <= 2]
        toc_text = re.sub(r'\n{2,}', '\n', "\n".join(toc_pages)).strip()
        if len(toc_text) < 30:
            return {"title": "", "units": []}
        prompt = (
            "Below is the CONTENTS page text of a school textbook. Parse it into units and their "
            "lessons/poems, with the printed page number of each lesson. A lesson title may wrap "
            "across lines — join it. Ignore front-matter entries like 'Foreword', 'About the Book', "
            "'Preface'.\n\n"
            f"CONTENTS:\n{toc_text[:6000]}\n\n"
            'Return ONLY JSON: {"title": "<book name if shown else empty>", "units": [{"unit": <int>, '
            '"theme": "<unit theme>", "lessons": [{"title": "<full lesson title>", "page": <printed page int>}]}]}'
        )
    try:
        raw, _, _ = mantle_client.converse(
            model_id=mantle_client.GEN_MODEL, prompt=prompt, max_tokens=1500, temperature=0.0,
        )
    except Exception as e:
        print(f"[MaterialIntel] TOC parse converse failed: {e}")
        return {"title": "", "units": []}
    m = re.search(r'\{.*\}', raw, re.S)
    if not m:
        return {"title": "", "units": []}
    try:
        data = json.loads(m.group())
    except Exception:
        return {"title": "", "units": []}

    units = []
    for u in (data.get("units") or []):
        if not isinstance(u, dict):
            continue
        lessons = []
        for l in (u.get("lessons") or []):
            if not isinstance(l, dict):
                continue
            title = _clean_name(str(l.get("title") or "")).strip()
            try:
                pg = int(l.get("page"))
            except (TypeError, ValueError):
                pg = None
            if title:
                lessons.append({"title": title, "page": pg})
        if lessons:
            try:
                un = int(u.get("unit"))
            except (TypeError, ValueError):
                un = len(units) + 1
            units.append({"unit": un, "theme": _clean_name(str(u.get("theme") or "")).strip(),
                          "lessons": lessons})
    return {"title": str(data.get("title") or "").strip()[:200], "units": units}


def _norm_probe(s) -> str:
    """Lowercased alnum-only version of a title's first words — for locating a title in page text
    robustly (ignores punctuation, small-caps mangling, line wraps)."""
    k = re.sub(r'[^a-z0-9 ]', '', (s or '').lower())
    k = re.sub(r'\s+', ' ', k).strip()
    return ' '.join(k.split()[:5])


def _anchor_offset(pdf_path, all_lessons, total):
    """Find the printed-page → PDF-index offset for a whole-book PDF by VOTING. Scans pages once;
    on each page checks which lesson titles appear near the TOP (a lesson-start), and votes for the
    implied offset  index - (printed_page - first_printed_page). The true offset is shared by every
    real lesson-start page, so it wins even if a prelims page merely mentions a title (a stray vote)
    or the numbering has small gaps. Skips contents/TOC pages (many titles at once). None if unsure."""
    from collections import Counter
    first_printed = all_lessons[0][1]
    probes = [(_norm_probe(t), p) for t, p in all_lessons]
    probes = [(pr, p) for pr, p in probes if len(pr) >= 6]   # distinctive probes only
    if len(probes) < 2:
        return None
    votes = Counter()
    for i in range(min(total, 500)):
        t = _clean_snippet(extract_pages_text(pdf_path, i, i + 1, max_chars=300) or "")
        top = re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', t.lower()))[:220]  # heading region
        if not top:
            continue
        hits = [p for pr, p in probes if pr in top]
        if len(hits) >= 3:                # a table-of-contents page — ignore
            continue
        for p in hits:
            votes[i - (p - first_printed)] += 1
    if not votes:
        return None
    off, n = votes.most_common(1)[0]
    return off if n >= 2 else None        # need ≥2 agreeing lesson-starts to trust it


def _anchor_offset_by_page_number(pdf_path, all_lessons, total):
    """Find the printed-page → PDF-index offset by matching each page's own LEADING PRINTED FOLIO
    NUMBER (the page number a reader sees printed on the page) against the TOC's known lesson page
    numbers. Far more robust than `_anchor_offset` for heavily-corrupted scripts (Tamil, etc.):
    ASCII/Tamil DIGITS extract cleanly even when the surrounding script is glyph-mangled, because the
    LLM's title CORRECTION never has to touch them — so this needs no text/spelling match at all.
    Since a book's pagination is continuous, ANY page (not just a lesson-start) whose own folio
    happens to be one of the lesson page numbers votes for the SAME true offset, so real matches
    heavily outweigh coincidental ones. Returns None if fewer than 2 pages agree.

    Same convention as `_anchor_offset`: offset is relative to the FIRST lesson's printed page (not
    the raw index-minus-page-number), so callers can reuse it as `fp = off + (p - first_printed)`."""
    from collections import Counter
    first_printed = min(p for _, p in all_lessons)
    known_pages = {p for _, p in all_lessons}
    lead_re = re.compile(r'^\s*(\d{1,3})\b')
    votes = Counter()
    for i in range(min(total, 500)):
        t = extract_pages_text(pdf_path, i, i + 1, max_chars=60) or ""
        m = lead_re.match(t)
        if not m:
            continue
        pg = int(m.group(1))
        if pg in known_pages:
            votes[i - (pg - first_printed)] += 1
    if not votes:
        return None
    off, n = votes.most_common(1)[0]
    return off if n >= 2 else None


def _split_by_count_matched_breaks(pdf_path, all_lessons, total, class_name, subject) -> list:
    """Fallback whole-book anchor for scripts where the LLM's CORRECTED title never literally
    reappears in the still-garbled raw PDF text (so _anchor_offset's substring-vote can't find it —
    e.g. Tamil, where the TOC parse fixes glyph-reordering damage the raw page text still has).
    Detects lesson BREAK POINTS independently via the existing per-page LLM lesson-detector (which
    reads each page's own raw text — no matching against the TOC needed), and if it finds exactly as
    many breaks as the TOC has lessons, zips the TOC's ordered titles onto them 1:1 (both are in page
    order). Returns [] if the counts don't match (too unreliable to guess further)."""
    try:
        breaks = _detect_lessons_by_llm(pdf_path, class_name or "", subject or "", total)
    except Exception:
        return []
    if len(breaks) != len(all_lessons):
        return []
    ordered_titles = [t for t, _ in sorted(all_lessons, key=lambda x: x[1])]
    ordered_pages = sorted(c["start_page"] for c in breaks)
    print(f"[MaterialIntel] TOC-guided WHOLE-BOOK split via count-matched breaks → {len(ordered_titles)} lesson(s)")
    return _ranges_from_starts(list(zip(ordered_titles, ordered_pages)), total)


def _split_with_contents(pdf_path, units, total, class_name=None, subject=None) -> list:
    """Split `pdf_path` using an ALREADY-PARSED contents structure (`units`, the same shape as
    BookContents.units: [{unit,theme,lessons:[{title,page}]}]), with the OFFICIAL lesson titles.

    Handles BOTH shapes:
      * WHOLE-BOOK PDF (all units in one file): the TOC's book-global page numbers map to PDF pages
        via a single front-matter offset (found by locating the first lesson's start page — literal
        substring anchor first, falling back to count-matched independent break detection for
        heavily-garbled scripts). Splits into every lesson across all units.
      * PER-UNIT PDF: detects which unit the file is ('Unit N' header / theme) and offsets within it.
    Deterministic-preferred. Returns [] if it can't anchor either shape."""
    if not units:
        return []

    # ── Whole-book case: the file spans most of the book's content page range. ──
    all_lessons = [(l["title"], int(l["page"])) for u in units for l in u.get("lessons", [])
                   if l.get("title") and l.get("page") is not None]
    all_lessons.sort(key=lambda x: x[1])
    looks_like_whole_book = False
    if len(all_lessons) >= 2:
        span = all_lessons[-1][1] - all_lessons[0][1]
        # Guard against a garbage TOC (e.g. every lesson parsed with page == its unit number): a real
        # book spans at least ~1 page per lesson. Without this, a tiny fake span makes a per-unit file
        # look like a whole book and produces nonsense.
        if span >= len(all_lessons) and total >= span * 0.75:
            looks_like_whole_book = True
            first_page = all_lessons[0][1]
            # Printed-folio-number anchor first: robust even for heavily-corrupted scripts, since
            # plain digits extract cleanly where the surrounding text doesn't. Falls back to the
            # literal-title-text anchor (works well for Latin-script books like NCERT 'Poorvi').
            off = _anchor_offset_by_page_number(pdf_path, all_lessons, total)
            if off is None:
                off = _anchor_offset(pdf_path, all_lessons, total)
            if off is not None:
                starts = []
                for title, p in all_lessons:
                    fp = off + (p - first_page)
                    if 0 <= fp < total:
                        starts.append((title, fp))
                if len({p for _, p in starts}) >= 2:
                    print(f"[MaterialIntel] TOC-guided WHOLE-BOOK split → {len(starts)} lesson(s) (offset {off})")
                    return _ranges_from_starts(starts, total)
            # Both anchors found no agreement — try count-matched breaks.
            cm = _split_by_count_matched_breaks(pdf_path, all_lessons, total, class_name, subject)
            if cm:
                return cm

    # A file shaped like a whole book that neither anchor strategy could split MUST NOT fall through
    # to per-unit matching below — that would (mis)treat it as a single unit and produce a bogus
    # partial split (as if only one unit's lessons existed). Let the caller try its next strategy.
    if looks_like_whole_book:
        return []

    # ── Per-unit case: detect which unit this file is, offset within it. ──
    head = extract_pages_text(pdf_path, 0, 2, max_chars=800) or ""
    unit = None
    m = re.search(r'\bunit\s*[-:]?\s*(\d+)', head, re.I)
    if m:
        unit = next((u for u in units if str(u.get("unit")) == m.group(1)), None)
    if unit is None:                                   # fall back to matching the unit theme
        hl = head.lower()
        for u in units:
            th = (u.get("theme") or "").lower().strip()
            if th and th in hl:
                unit = u
                break
    if unit is None:                                   # last resort: match the file's opening lesson
        htop = re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', head.lower()))
        for u in units:
            for l in u.get("lessons", []):
                pr = _norm_probe(l.get("title", ""))
                if pr and len(pr) >= 6 and pr in htop:
                    unit = u
                    break
            if unit:
                break
    if unit is None:
        return []

    lessons = [l for l in unit.get("lessons", []) if l.get("title") and l.get("page") is not None]
    if len(lessons) < 2:
        return []
    offset = min(int(l["page"]) for l in lessons)
    starts = []
    for l in sorted(lessons, key=lambda x: int(x["page"])):
        fp = int(l["page"]) - offset
        if 0 <= fp < total:
            starts.append((l["title"], fp))
    if len({p for _, p in starts}) < 2:
        return []
    print(f"[MaterialIntel] TOC-guided split → unit {unit.get('unit')} ({len(starts)} lesson(s))")
    return _ranges_from_starts(starts, total)


def _detect_chapters_by_toc(pdf_path, class_name, subject, school_id, total) -> list:
    """Split using a previously-parsed, SEPARATELY-UPLOADED BookContents row (a superadmin/school
    uploaded the book's contents/prelims PDF once via the 'Upload contents PDF' UI). See
    _split_with_contents for the two page-range shapes handled. Returns [] if none is stored."""
    try:
        from .models import BookContents
    except Exception:
        return []
    qs = BookContents.objects.filter(class_name=str(class_name or ""), subject__iexact=str(subject or ""))
    tc = None
    if school_id:
        tc = qs.filter(school_id=school_id).first()
    tc = tc or qs.filter(school__isnull=True).first() or qs.first()
    if not tc or not tc.units:
        return []
    return _split_with_contents(pdf_path, tc.units, total, class_name=class_name, subject=subject)


def _detect_chapters_by_embedded_toc(pdf_path, total, persist=False, class_name=None,
                                     subject=None, school_id=None) -> list:
    """WHOLE-BOOK PDF that carries its OWN contents page — no separately-uploaded BookContents
    needed. Parses the contents page from THIS SAME pdf (parse_book_contents) and splits by it
    (_split_with_contents), so a bulk upload of the full book (with all units) self-splits with no
    extra step. Cheap to try for files without a contents page: parse_book_contents only makes an
    LLM call once it has found a contents-shaped page.

    When `persist` is True and nothing is already stored for this class+subject+school, saves the
    parsed TOC as a BookContents row so future per-unit uploads of the same book benefit too (the
    caller sets persist=False for read-only preview requests, so those never write to the DB)."""
    if total < 5:
        return []
    parsed = parse_book_contents(pdf_path)
    units = parsed.get("units") or []
    if len(units) < 2:
        return []
    chapters = _split_with_contents(pdf_path, units, total, class_name=class_name, subject=subject)
    if chapters and persist and class_name and subject:
        try:
            from .models import BookContents
            exists = BookContents.objects.filter(
                class_name=str(class_name), subject__iexact=str(subject), school_id=school_id
            ).exists()
            if not exists:
                BookContents.objects.create(
                    class_name=str(class_name), subject=str(subject), school_id=school_id,
                    title=(parsed.get("title") or ""), units=units,
                )
                print(f"[MaterialIntel] saved embedded contents as BookContents ({len(units)} units, "
                      f"class={class_name} subject={subject}) for future uploads")
        except Exception as e:
            print(f"[MaterialIntel] could not persist embedded TOC: {e}")
    return chapters


def detect_book_chapters(pdf_path, class_name, subject, refine_names=True, school_id=None,
                         persist_toc=False) -> list:
    """Split a whole-textbook PDF into per-chapter page ranges.

    Strategy, most-reliable first: (1) PDF bookmarks/outline; (1.5) TOC-guided from a SEPARATELY
    uploaded contents PDF (BookContents row); (1.7) TOC-guided from a contents page EMBEDDED in this
    same PDF (no separate upload needed — a bulk-uploaded whole book self-splits); (2) 'Chapter
    N'/'Unit N' regex; (3) LLM lesson detection (reads page tops — for NCERT 'Poorvi' English units
    that mix lessons with 'Let us read/…' activity headers); (4) TITLE-FONT headings fallback.
    Returns [{"unit", "start_page", "end_page"}, ...] (page indices, end exclusive). Returns [] if it
    can't find at least 2 chapters (caller then treats the file as a single unit). `school_id` scopes
    the BookContents lookup (superadmin/global = None). `persist_toc=True` saves a TOC found via step
    1.7 as a BookContents row for future uploads to reuse — leave False for read-only previews."""
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

    # 1.5) TOC-guided — most authoritative: split by the book's own parsed contents (BookContents),
    #      giving exact official lesson titles at the TOC page offsets.
    smart_named = False
    if len(chapters) < 2:
        try:
            toc = _detect_chapters_by_toc(pdf_path, class_name, subject, school_id, total)
            if len(toc) >= 2:
                chapters = toc
                smart_named = True
        except Exception as e:
            print(f"[MaterialIntel] TOC-guided split failed: {e}")

    # 1.7) Embedded contents page — the PDF being split carries its OWN contents page (e.g. a bulk
    #      upload of a whole book with all units, no separately-uploaded BookContents). Parses it
    #      inline; no extra upload step needed. See _detect_chapters_by_embedded_toc.
    if len(chapters) < 2:
        try:
            emb = _detect_chapters_by_embedded_toc(pdf_path, total, persist=persist_toc,
                                                   class_name=class_name, subject=subject,
                                                   school_id=school_id)
            if len(emb) >= 2:
                chapters = emb
                smart_named = True
        except Exception as e:
            print(f"[MaterialIntel] embedded-TOC split failed: {e}")

    # 2) Heading-regex — books with explicit "Chapter N" / "Unit N" numbering (free, no LLM).
    if len(chapters) < 2:
        starts = []
        for i in range(total):
            # Clean the DTP footer first, else 'Unit N.indd' running footers match on every page.
            head = _clean_snippet(extract_pages_text(pdf_path, i, i + 1, max_chars=400))
            m = _CHAPTER_HEADING_RE.search(head or "")
            if m:
                # Use the line after the "Chapter N" marker as the title when available.
                after = (head[m.end():].strip().splitlines() or [""])[0].strip()
                starts.append((after or f"Chapter {m.group(2)}", i))
        if len(starts) >= 2:
            chapters = _ranges_from_starts(starts, total)

    # 3) LLM lesson detection — no bookmarks AND no numbered headings (NCERT 'Poorvi' English units
    #    mix prose/poem lessons with 'Let us read/listen/…' activity headers that look identical
    #    typographically). The LLM reads each page's top text and returns the real lessons.
    if len(chapters) < 2:
        try:
            llm = _detect_lessons_by_llm(pdf_path, class_name, subject, total)
            if len(llm) >= 2:
                chapters = llm
                smart_named = True
                print(f"[MaterialIntel] LLM lesson split → {len(llm)} lesson(s)")
        except Exception as e:
            print(f"[MaterialIntel] LLM lesson split failed: {e}")

    # 4) Title-font heuristic — fallback when the LLM is unavailable / declines.
    if len(chapters) < 2:
        try:
            tf = _detect_chapters_by_titlefont(pdf_path, total)
            if len(tf) >= 2:
                chapters = tf
                smart_named = True
                print(f"[MaterialIntel] title-font split → {len(tf)} lesson(s)")
        except Exception as e:
            print(f"[MaterialIntel] title-font split failed: {e}")

    if len(chapters) < 2:
        return []

    # Optionally refine each chapter's name from its own first page (snaps to catalog). Skipped for
    # the title-font path: those names ARE the exact printed lesson titles, and the LLM would often
    # mis-pick the unit header that shares the first lesson's opening page. Still snap to the catalog
    # (cheap, no LLM) so names stay consistent when the book IS in the CBSE catalog.
    if refine_names and not smart_named:
        for ch in chapters:
            sample = extract_pages_text(pdf_path, ch["start_page"], ch["start_page"] + 2, max_chars=2000)
            better = detect_unit_name(pdf_path, class_name, subject, sample_text=sample)
            if better:
                ch["unit"] = better
            else:
                ch["unit"] = _snap_to_catalog(ch["unit"], subject)
    elif smart_named:
        # LLM / title-font names are the actual lesson titles — keep them, just snap to catalog.
        for ch in chapters:
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
