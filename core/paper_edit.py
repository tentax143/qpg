"""Operation-based question-paper editor.

The AI editor turns a teacher's natural-language instruction into a list of structured
operations (the LLM planner lives in the view), then this module applies them to a
``paper_data`` dict. The structural operations — move / delete / swap / set / reorder /
renumber — are pure data manipulation and fully unit-testable WITHOUT an LLM. Content
operations — edit / replace / add — delegate question generation to a ``generate_fn``
callback the caller supplies (the real one calls the model; tests inject a fake), so this
module stays free of any model dependency.

Design choice (confirmed with the user): operations are applied AS REQUESTED — moving a
1-mark MCQ into a 3-mark section is honoured, not blocked. The caller audits the result
afterwards and surfaces any pattern mismatch as a warning; nothing is silently rewritten.

Supported operations (one dict each, in an ``operations`` list):
    {"action": "edit",    "qnum": 5, "instruction": "make it harder"}
    {"action": "replace", "qnum": 2, "instruction": "fresh question on decimals"}
    {"action": "add",     "section": "Section A", "type": "MCQ", "marks": 1,
                          "instruction": "about fractions", "position": "end"}
    {"action": "move",    "qnum": 7, "to_section": "Section B", "position": "end"}
    {"action": "delete",  "qnum": 3}
    {"action": "swap",    "qnum_a": 2, "qnum_b": 4}
    {"action": "set",     "qnum": 3, "fields": {"marks": 5}}
    {"action": "set_section", "section": "Section B", "fields": {"instructions": "…"}}
"""
from __future__ import annotations

import copy

# Fields a `set` op may write directly on a question (no model call). Anything else is ignored
# so a planner can't inject arbitrary keys.
_SETTABLE_Q_FIELDS = {
    "marks", "type", "subtype", "answer", "text", "options",
    "chapter_tag", "competency_type", "or_alternative", "answer_explanation",
    "source_text", "sub_questions", "image_prompt",
}
_SETTABLE_SECTION_FIELDS = {"instructions", "title", "marks", "section_name"}


def iter_sections(paper_data):
    """Yield (display_name, section_dict) for every section holding a questions list.
    Mirrors api.views._paper_section_iter so both layers agree on paper_data shape
    ({Section:{...}}, {sections:{...}}, or {sections:[...]})."""
    if not isinstance(paper_data, (dict, list)):
        return
    secs = paper_data.get("sections", paper_data) if isinstance(paper_data, dict) else paper_data
    if isinstance(secs, dict):
        for sname, sec in secs.items():
            if isinstance(sec, dict) and isinstance(sec.get("questions"), list):
                yield (sec.get("section_name") or sname), sec
    elif isinstance(secs, list):
        for sec in secs:
            if isinstance(sec, dict) and isinstance(sec.get("questions"), list):
                yield (sec.get("section_name") or sec.get("name") or ""), sec


def _find_question(paper_data, qnum):
    """Return (section_name, section_dict, index, question) for the question whose qnum
    matches, else None. qnum is compared loosely (int/str)."""
    if qnum is None:
        return None
    try:
        target = int(qnum)
    except (TypeError, ValueError):
        return None
    for sname, sec in iter_sections(paper_data):
        for i, q in enumerate(sec["questions"]):
            if isinstance(q, dict):
                try:
                    if int(q.get("qnum")) == target:
                        return sname, sec, i, q
                except (TypeError, ValueError):
                    continue
    return None


def resolve_section(paper_data, target):
    """Find a section dict by name or id, tolerant of how a teacher might name it:
    exact name, section_id, 'Section B' ↔ id 'B', or a substring match."""
    if not target:
        return None
    t = str(target).strip().lower()
    sections = list(iter_sections(paper_data))
    # 1. exact display-name match
    for name, sec in sections:
        if str(name).strip().lower() == t:
            return sec
    # 2. section_id match (also handles "section b" → id "b")
    t_id = t[len("section"):].strip() if t.startswith("section") else t
    for name, sec in sections:
        sid = str(sec.get("section_id", "")).strip().lower()
        if sid and (sid == t or sid == t_id):
            return sec
    # 3. substring either direction (last resort)
    for name, sec in sections:
        n = str(name).strip().lower()
        if n and (t in n or n in t):
            return sec
    return None


def _insert_at(questions, item, position):
    """Insert item into the questions list at 'start', 'end' (default), or an integer index."""
    if position in (None, "end", ""):
        questions.append(item)
    elif position == "start":
        questions.insert(0, item)
    else:
        try:
            questions.insert(int(position), item)
        except (TypeError, ValueError):
            questions.append(item)


def renumber(paper_data):
    """Reassign qnum sequentially (1-based) across all sections in document order. Run after
    any structural change so the rendered paper numbers questions 1..N with no gaps."""
    n = 1
    for _name, sec in iter_sections(paper_data):
        for q in sec["questions"]:
            if isinstance(q, dict):
                q["qnum"] = n
                n += 1
    return paper_data


def _coerce_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def apply_operations(paper_data, operations, generate_fn=None):
    """Apply ``operations`` to a deep copy of ``paper_data`` and return
    ``(new_paper_data, applied, notes)``.

    ``applied`` is a list of short human-readable strings (one per successful op).
    ``notes`` collects warnings for ops that were skipped or could not be applied — never
    raises for a single bad op, so one malformed instruction can't abort the whole edit.

    ``generate_fn(kind, context) -> dict | None`` produces question JSON for the content
    operations:
      kind="edit"    context={"question": <q>, "instruction": str}
      kind="replace" context={"question": <q>, "instruction": str}
      kind="add"     context={"section": str, "type": str|None, "marks": any, "instruction": str}
    Returning None (or no generate_fn) makes that content op a no-op with a note.
    """
    pd = copy.deepcopy(paper_data)
    applied: list = []
    notes: list = []

    for op in (operations or []):
        if not isinstance(op, dict):
            notes.append("Skipped a malformed operation (not an object).")
            continue
        action = str(op.get("action", "")).strip().lower()

        try:
            if action == "delete":
                found = _find_question(pd, op.get("qnum"))
                if not found:
                    notes.append(f"delete: question {op.get('qnum')} not found.")
                    continue
                _sname, sec, i, q = found
                sec["questions"].pop(i)
                applied.append(f"deleted Q{op.get('qnum')}")

            elif action == "move":
                found = _find_question(pd, op.get("qnum"))
                if not found:
                    notes.append(f"move: question {op.get('qnum')} not found.")
                    continue
                _sname, src_sec, i, q = found
                dest = resolve_section(pd, op.get("to_section") or op.get("section"))
                if dest is None:
                    notes.append(f"move: target section "
                                 f"'{op.get('to_section') or op.get('section')}' not found.")
                    continue
                src_sec["questions"].pop(i)
                _insert_at(dest["questions"], q, op.get("position", "end"))
                applied.append(f"moved Q{op.get('qnum')} → "
                               f"{dest.get('section_name') or dest.get('section_id') or 'section'}")

            elif action == "swap":
                a = _find_question(pd, op.get("qnum_a"))
                b = _find_question(pd, op.get("qnum_b"))
                if not a or not b:
                    notes.append(f"swap: question {op.get('qnum_a')} or "
                                 f"{op.get('qnum_b')} not found.")
                    continue
                _, sec_a, ia, _qa = a
                _, sec_b, ib, _qb = b
                sec_a["questions"][ia], sec_b["questions"][ib] = (
                    sec_b["questions"][ib], sec_a["questions"][ia])
                applied.append(f"swapped Q{op.get('qnum_a')} ↔ Q{op.get('qnum_b')}")

            elif action == "set":
                found = _find_question(pd, op.get("qnum"))
                if not found:
                    notes.append(f"set: question {op.get('qnum')} not found.")
                    continue
                _sname, sec, i, q = found
                fields = op.get("fields")
                if not isinstance(fields, dict):
                    # tolerate flat form: {"action":"set","qnum":3,"marks":5}
                    fields = {k: v for k, v in op.items()
                              if k in _SETTABLE_Q_FIELDS}
                clean = {k: v for k, v in fields.items() if k in _SETTABLE_Q_FIELDS}
                if not clean:
                    notes.append(f"set: no settable fields for Q{op.get('qnum')}.")
                    continue
                q.update(clean)
                applied.append(f"set {', '.join(clean)} on Q{op.get('qnum')}")

            elif action == "set_section":
                dest = resolve_section(pd, op.get("section"))
                if dest is None:
                    notes.append(f"set_section: section '{op.get('section')}' not found.")
                    continue
                fields = op.get("fields") if isinstance(op.get("fields"), dict) else {}
                clean = {k: v for k, v in fields.items() if k in _SETTABLE_SECTION_FIELDS}
                if not clean:
                    notes.append(f"set_section: no settable fields for '{op.get('section')}'.")
                    continue
                dest.update(clean)
                applied.append(f"updated section '{op.get('section')}' ({', '.join(clean)})")

            elif action in ("edit", "replace"):
                found = _find_question(pd, op.get("qnum"))
                if not found:
                    notes.append(f"{action}: question {op.get('qnum')} not found.")
                    continue
                _sname, sec, i, q = found
                if generate_fn is None:
                    notes.append(f"{action}: no generator available — skipped.")
                    continue
                newq = generate_fn(action, {"question": q, "instruction": op.get("instruction", "")})
                if not (isinstance(newq, dict) and str(newq.get("text", "")).strip()):
                    notes.append(f"{action}: model returned nothing usable for Q{op.get('qnum')}.")
                    continue
                # Preserve identity unless the instruction explicitly changed structure: for a
                # plain `edit` keep type/subtype/marks; `replace` may legitimately change them.
                newq["qnum"] = q.get("qnum")
                if action == "edit":
                    newq.setdefault("type", q.get("type"))
                    newq.setdefault("subtype", q.get("subtype"))
                    if newq.get("marks") in (None, "", 0):
                        newq["marks"] = q.get("marks")
                sec["questions"][i] = newq
                applied.append(f"{action}ed Q{op.get('qnum')}")

            elif action == "add":
                dest = resolve_section(pd, op.get("section") or op.get("to_section"))
                if dest is None:
                    notes.append(f"add: section '{op.get('section')}' not found.")
                    continue
                if generate_fn is None:
                    notes.append("add: no generator available — skipped.")
                    continue
                newq = generate_fn("add", {
                    "section": dest.get("section_name") or dest.get("section_id") or "",
                    "type": op.get("type"),
                    "marks": op.get("marks"),
                    "instruction": op.get("instruction", ""),
                })
                if not (isinstance(newq, dict) and str(newq.get("text", "")).strip()):
                    notes.append("add: model returned nothing usable.")
                    continue
                if newq.get("marks") in (None, "", 0) and op.get("marks") not in (None, ""):
                    newq["marks"] = op.get("marks")
                _insert_at(dest["questions"], newq, op.get("position", "end"))
                applied.append(f"added a question to "
                               f"{dest.get('section_name') or dest.get('section_id') or 'section'}")

            else:
                notes.append(f"Unknown action '{action}' — skipped.")
                continue

        except Exception as e:  # one bad op must never abort the whole edit
            notes.append(f"{action or 'operation'} failed: {e}")

    renumber(pd)
    return pd, applied, notes
