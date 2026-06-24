"""
Audit an assembled question paper against its ExamPattern.

Question: do the per-question marks — counting an OR / internal-choice pair only
ONCE — add up, per section and overall, to what the pattern specifies?

A choice ("Q5 … OR …") is worth the marks of a *single* question: the student
answers one alternative. The alternative is normally stored as a field on the
primary question (``or_alternative`` / ``or``), so summing each question's
``marks`` once already counts it correctly. As a safety net we also detect an
alternative that leaked in as its own list entry and exclude it, so it can never
inflate the total.

``audit_paper_marks`` returns a structured diagnosis so a mismatch can be pinned
to the exact section and cause (missing questions, wrong per-question marks,
missing/extra section, uncounted OR entry).
"""


def _norm_name(s):
    return str(s or "").strip().lower()


def _q_marks(q):
    try:
        return float(q.get("marks", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_or_alternative_entry(q):
    """True if this list entry is an OR / internal-choice ALTERNATIVE that must
    NOT be counted as its own question (its marks belong to the primary)."""
    if not isinstance(q, dict):
        return False
    for flag in ("is_or_alternative", "is_or", "or_of", "is_choice_alternative", "is_alternative"):
        if q.get(flag):
            return True
    if _norm_name(q.get("text")) == "or":
        return True
    if _norm_name(q.get("type")) in ("or", "or_alternative", "choice"):
        return True
    return False


def _iter_assembled_sections(paper_data):
    """Yield (display_name, section_dict) from paper_data, which stores sections
    either as a name→section dict or as a list of section dicts."""
    if not isinstance(paper_data, dict):
        return []
    secs = paper_data.get("sections", paper_data)
    if isinstance(secs, dict):
        return [(name, sec) for name, sec in secs.items() if isinstance(sec, dict)]
    if isinstance(secs, list):
        out = []
        for i, sec in enumerate(secs):
            if isinstance(sec, dict):
                out.append((sec.get("section_name") or sec.get("name") or f"#{i + 1}", sec))
        return out
    return []


def _pattern_sections(pattern):
    """Normalise a pattern's sections to [{name, marks, q_count, mpq}], folding in
    subsection breakdowns when a section carries no marks/count of its own."""
    out = []
    for s in (getattr(pattern, "sections", None) or []):
        if not isinstance(s, dict):
            continue
        marks = s.get("marks") or 0
        q_count = s.get("questions_count") or s.get("questions") or 0
        subs = s.get("subsections") or []
        if not marks and subs:
            marks = sum((ss.get("marks", 0) or 0) for ss in subs)
        if not q_count and subs:
            q_count = sum((ss.get("questions_count") or ss.get("questions", 0) or 0) for ss in subs)
        out.append({
            "name": s.get("name") or s.get("id") or "",
            "marks": marks,
            "q_count": q_count,
            "mpq": s.get("marks_per_question"),
        })
    return out


def audit_paper_marks(paper_data, pattern, tolerance=0.5):
    """Compare the assembled paper to its pattern.

    Returns a dict::

        {
          "ok": bool,                      # total AND every section match
          "expected_total": int,           # pattern.total_marks
          "actual_total": float,           # Σ per-question marks (OR counted once)
          "issues": [str, ...],            # human-readable, most important first
          "sections": [ {name, expected_marks, actual_marks,
                         expected_q, actual_q, ok}, ... ],
        }
    """
    expected_total = (getattr(pattern, "total_marks", 0) if pattern else 0) or 0
    pat_secs = _pattern_sections(pattern) if pattern else []
    pat_keys = {_norm_name(s["name"]) for s in pat_secs}

    # Tally each assembled section (primary questions only; OR-entries excluded).
    asm_by_name = {}
    actual_total = 0.0
    for name, sec in _iter_assembled_sections(paper_data):
        qs = [q for q in sec.get("questions", []) if isinstance(q, dict)]
        primary = [q for q in qs if not _is_or_alternative_entry(q)]
        sec_marks = sum(_q_marks(q) for q in primary)
        actual_total += sec_marks
        asm_by_name[_norm_name(name)] = {
            "display": name,
            "count": len(primary),
            "marks": sec_marks,
            "or_entries": len(qs) - len(primary),
        }

    issues = []
    section_rows = []

    # Compare each pattern section (the source of truth) against the paper.
    for s in pat_secs:
        a = asm_by_name.get(_norm_name(s["name"]))
        if a is None:
            issues.append(f"{s['name']}: MISSING from the paper "
                          f"(expected {s['q_count']}q / {s['marks']}m).")
            section_rows.append({"name": s["name"], "expected_marks": s["marks"],
                                 "actual_marks": 0, "expected_q": s["q_count"],
                                 "actual_q": 0, "ok": False})
            continue

        marks_off = abs(a["marks"] - s["marks"]) > tolerance and bool(s["marks"])
        count_off = bool(s["q_count"]) and a["count"] != s["q_count"]
        ok = not (marks_off or count_off)
        if not ok:
            parts = []
            if count_off:
                d = a["count"] - s["q_count"]
                parts.append(f"{a['count']}/{s['q_count']} questions ({'+' if d > 0 else ''}{d})")
            if marks_off:
                d = a["marks"] - s["marks"]
                parts.append(f"{a['marks']:g}/{s['marks']} marks ({'+' if d > 0 else ''}{d:g})")
            if a["or_entries"]:
                parts.append(f"{a['or_entries']} OR-alternative entr"
                             f"{'y' if a['or_entries'] == 1 else 'ies'} not counted")
            issues.append(f"{s['name']}: " + ", ".join(parts) + ".")
        section_rows.append({"name": s["name"], "expected_marks": s["marks"],
                             "actual_marks": a["marks"], "expected_q": s["q_count"],
                             "actual_q": a["count"], "ok": ok})

    # Sections in the paper that the pattern doesn't define.
    for key, a in asm_by_name.items():
        if key not in pat_keys:
            issues.append(f"{a['display']}: present in the paper but not in the pattern "
                          f"({a['count']}q / {a['marks']:g}m).")

    total_off = bool(expected_total) and abs(actual_total - expected_total) > tolerance
    if total_off:
        d = actual_total - expected_total
        issues.insert(0, f"Total {actual_total:g}/{expected_total} marks ({'+' if d > 0 else ''}{d:g}).")

    return {
        "ok": (not total_off) and not issues,
        "expected_total": expected_total,
        "actual_total": actual_total,
        "issues": issues,
        "sections": section_rows,
    }


def summary_line(result, max_len=480):
    """One-line, teacher-facing summary of a failed audit (empty string if ok)."""
    if result.get("ok"):
        return ""
    return " ".join(result.get("issues", []))[:max_len]


# ── Chapter coverage ──────────────────────────────────────────────────────────
def _chapter_matches_tag(chapter, tag):
    """Fuzzy match a planned chapter name against a question's chapter_tag (the model may
    phrase the tag slightly differently), substring either direction, case-insensitive."""
    c, t = _norm_name(chapter), _norm_name(tag)
    if not c or not t:
        return False
    return c in t or t in c


def audit_chapter_coverage(paper_data):
    """Check whether every planned chapter received at least one question SOMEWHERE in the
    finished paper.

    The chapter plan is per-section (plan_chapter_allocation spreads each section across a
    weighted set of chapters), so the SAME chapter is normally planned in several sections —
    a 5-section paper covering 9 chapters can carry ~26 section-level slots. What a teacher
    actually cares about for a full-portion paper is *distinct* coverage: does every chapter
    appear at least once. So the headline numbers (``planned``/``covered``/``missed``) count
    DISTINCT chapters paper-wide — a chapter planned for Section C but answered in Section A
    still counts as covered, and is no longer falsely reported as a gap. The finer per-section
    slot detail is preserved in ``sections`` and the ``slot_*`` totals for the diagnostic
    ``audit_papers`` command.

    Returns ``{ok, has_plan, planned, covered, missed:[chapter,...], offplan,
               slot_planned, slot_covered, sections:[...]}``. ``ok`` is True when there is no
    plan (nothing to check) or every distinct planned chapter got at least one question."""
    rows, has_plan = [], False
    planned_chapters: list = []          # distinct chapters, paper-wide, order preserved
    slot_planned = slot_covered = offplan = 0

    # Every question tag in the whole paper — coverage is judged paper-wide, not per-section.
    all_tags = []
    for _name, sec in _iter_assembled_sections(paper_data):
        for q in sec.get("questions", []):
            if isinstance(q, dict):
                t = str(q.get("chapter_tag") or q.get("chapter") or "")
                if t:
                    all_tags.append(t)

    for name, sec in _iter_assembled_sections(paper_data):
        plan = sec.get("_chapter_plan") or []
        if not plan:
            continue
        has_plan = True
        qs = [q for q in sec.get("questions", []) if isinstance(q, dict)]
        tags = [str(q.get("chapter_tag") or q.get("chapter") or "") for q in qs]
        plan_chapters = list(dict.fromkeys(plan))   # unique within the section
        for ch in plan_chapters:
            if ch not in planned_chapters:
                planned_chapters.append(ch)
        sec_missed = [ch for ch in plan_chapters
                      if not any(_chapter_matches_tag(ch, t) for t in tags)]
        slot_planned += len(plan_chapters)
        slot_covered += len(plan_chapters) - len(sec_missed)
        offplan += sum(1 for t in tags
                       if t and not any(_chapter_matches_tag(ch, t) for ch in plan_chapters))
        rows.append({"name": name, "planned": len(plan_chapters),
                     "covered": len(plan_chapters) - len(sec_missed), "missed": sec_missed})

    # Distinct, paper-wide: a chapter is covered if ANY question anywhere matches it.
    missed = [ch for ch in planned_chapters
              if not any(_chapter_matches_tag(ch, t) for t in all_tags)]
    covered = len(planned_chapters) - len(missed)

    return {
        "ok": (not has_plan) or not missed,
        "has_plan": has_plan,
        "planned": len(planned_chapters),
        "covered": covered,
        "missed": missed,
        "offplan": offplan,
        "slot_planned": slot_planned,
        "slot_covered": slot_covered,
        "sections": rows,
    }


def coverage_summary_line(result, max_len=480):
    """One-line, teacher-facing summary of chapter-coverage gaps (empty if ok / no plan)."""
    if not result.get("has_plan") or result.get("ok"):
        return ""
    parts = [f"{result['covered']}/{result['planned']} chapters covered."]
    if result.get("missed"):
        parts.append("No question anywhere for: " + ", ".join(result["missed"][:12]) + ".")
    return " ".join(parts)[:max_len]
