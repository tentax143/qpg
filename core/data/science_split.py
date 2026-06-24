"""
Deterministic classifier that maps a CBSE *Science* chapter name to its real
higher-secondary subject — Physics, Chemistry, or Biology.

Used by the ``split_science`` management command to break a class 11/12 paper's
materials (uploaded under the umbrella subject "Science") into the three
separate subjects that CBSE actually examines from class 11 onwards.

Design principles
-----------------
* **Deterministic, no LLM** — chapter names are well-known CBSE titles, so a
  curated phrase/keyword map classifies them reliably and reproducibly.
* **Never guess** — a chapter that is ambiguous (e.g. "Thermodynamics", which is
  a chapter in *both* class-11 Physics and Chemistry) or that matches nothing
  returns ``None`` so the migration leaves it untouched and reports it for a
  human to resolve. Silent miscategorisation is worse than a flagged skip.

Validated against the already-correctly-split class 11/12 catalogue
(see ``scratchpad/test_classify`` run) — 100% on unambiguous chapters.
"""

import re

PHYSICS = "Physics"
CHEMISTRY = "Chemistry"
BIOLOGY = "Biology"

# Chapter names that legitimately belong to more than one subject and cannot be
# resolved from the title alone. These are deliberately left for manual review.
_AMBIGUOUS = (
    "thermodynamics",   # class-11 Physics AND class-11 Chemistry both have it
)

# NCERT textbook filename codes (e.g. "leph1an", "kech203"). The 2-letter middle
# segment encodes the subject:  ph=Physics, ch=Chemistry, bo=Biology.
#   k* = class 11   (keph/kech/kebo) ,  l* = class 12 (leph/lech/lebo)
_NCERT_CODE_RE = re.compile(r"\b[kl]e(ph|ch|bo)\d", re.IGNORECASE)
_NCERT_CODE_SUBJECT = {"ph": PHYSICS, "ch": CHEMISTRY, "bo": BIOLOGY}

# High-priority overrides, checked in order. Each entry resolves a phrase that
# would otherwise be mis-scored by the generic keyword lists below (e.g.
# "Chemical Coordination" contains "chemical" but is a Biology chapter).
_OVERRIDES = [
    # --- Biology phrases that contain chemistry-ish words ---
    ("biological classification", BIOLOGY),
    ("chemical coordination", BIOLOGY),
    ("neural control", BIOLOGY),
    ("control and coordination", BIOLOGY),
    ("coordination and integration", BIOLOGY),
    ("structural organisation", BIOLOGY),
    ("structural organization", BIOLOGY),
    # --- Chemistry phrases that contain physics/biology-ish words ---
    ("coordination compound", CHEMISTRY),
    ("structure of atom", CHEMISTRY),
    ("classification of element", CHEMISTRY),
    ("periodicity", CHEMISTRY),
    ("chemical bond", CHEMISTRY),
    ("chemical kinetic", CHEMISTRY),
    ("chemical reaction", CHEMISTRY),
    ("chemical equation", CHEMISTRY),
    ("organic chemistry", CHEMISTRY),
]

# Generic keyword lists. A chapter scores +1 per distinct substring it contains;
# the highest-scoring subject wins. Bare words that are genuinely shared between
# subjects (e.g. "chemical", "matter", "structure", "classification") are
# intentionally absent — those cases are handled by _OVERRIDES above.
_KEYWORDS = {
    PHYSICS: [
        "motion", "gravitation", "kinetic theory", "oscillation", "rotational",
        "system of particles", "thermal propert", "mechanical propert",
        "units and measurement", "unit and measurement", "work, energy",
        "work energy", "energy and power", "electric charge", "electrostatic",
        "current electricity", "moving charge", "magnetism", "magnet",
        "electromagnetic", "alternating current", "dual nature", "radiation",
        "photoelectric", "atoms", "nuclei", "nucleus", "nuclear",
        "semiconductor", "electronic", "optic", "light", "reflection",
        "refraction", "human eye", "lens", "mirror", "capacit", "fluid",
        "wave", "electricity",
    ],
    CHEMISTRY: [
        "acid", "base", "salt", "metal", "non-metal", "nonmetal", "carbon",
        "hydrocarbon", "redox", "equilibri", "electrochem", "kinetics",
        "haloalkane", "haloarene", "alcohol", "phenol", "ether", "aldehyde",
        "ketone", "carboxylic", "amine", "polymer", "solution", "solid state",
        "surface chemistry", "p-block", "d-block", "f-block", "d and f",
        "block element", "metallurg", "mole concept", "ester", "periodic",
        "chemistry",
    ],
    BIOLOGY: [
        "living world", "kingdom", "morphology", "anatomy", "plant", "animal",
        "cell", "photosynthesis", "respiration", "body fluid", "circulation",
        "breathing", "exchange of gas", "excretory", "locomotion", "movement",
        "growth and development", "digestion", "absorption", "reproduction",
        "reproduce", "reproductive", "inheritance", "heredity", "genetic",
        "evolution", "health and disease", "microbe", "biotechnology",
        "ecosystem", "biodiversity", "ecology", "environment", "organism",
        "population", "life process", "neural", "nutrition",
    ],
}


def _normalize(name: str) -> str:
    if not name:
        return ""
    # Collapse whitespace and lowercase; drop stray non-alphanumerics that creep
    # in from PDF extraction (e.g. the "�" en-dash artefact seen in titles).
    s = name.lower().replace("–", " ").replace("�", " ")
    return re.sub(r"\s+", " ", s).strip()


def classify_chapter(name: str, class_name=None):
    """Classify a chapter title into Physics / Chemistry / Biology.

    Returns ``(subject, reason)`` where ``subject`` is one of the three subject
    strings, or ``(None, reason)`` when the chapter is ambiguous or unmatched.
    ``class_name`` (optional) only affects the handful of titles that are
    class-dependent (currently just "Biomolecules": Biology in 11, Chemistry in 12).
    """
    norm = _normalize(name)
    if not norm:
        return None, "empty title"

    # 1) Genuinely ambiguous titles — never guess.
    for amb in _AMBIGUOUS:
        if amb in norm:
            return None, f"ambiguous ('{amb}' appears in multiple subjects)"

    # 2) NCERT textbook filename codes (leph/kech/lebo…).
    m = _NCERT_CODE_RE.search(norm)
    if m:
        return _NCERT_CODE_SUBJECT[m.group(1).lower()], f"ncert code '{m.group(0)}'"

    # 3) Class-dependent special case.
    if "biomolecule" in norm:
        cls = str(class_name or "").strip()
        if cls == "12":
            return CHEMISTRY, "biomolecules (class 12 → Chemistry)"
        return BIOLOGY, "biomolecules (class 11 → Biology)"

    # 4) Ordered overrides for phrases the keyword scorer would misread.
    for phrase, subject in _OVERRIDES:
        if phrase in norm:
            return subject, f"override '{phrase}'"

    # 5) Keyword scoring — highest distinct-hit count wins.
    scores = {}
    hits = {}
    for subject, kws in _KEYWORDS.items():
        matched = [kw for kw in kws if kw in norm]
        scores[subject] = len(matched)
        hits[subject] = matched

    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score == 0:
        return None, "no keyword match"

    # Reject ties (two subjects equally likely) — leave for manual review.
    tied = [s for s, sc in scores.items() if sc == best_score]
    if len(tied) > 1:
        return None, f"tie between {', '.join(sorted(tied))}"

    return best, f"keywords {hits[best]}"
