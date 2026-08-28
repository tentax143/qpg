"""Subject-name families.

CBSE names the same subject differently by stage and stream: a Class 6 timetable says "English",
the paper that syllabus builds towards is "English Language & Literature", and the senior-secondary
one is "English Core". A teacher who picks "English" must still be matched to the right sample
paper, so comparisons go through a family rather than string equality.

Mirrored in `frontend/src/lib/patterns.js` (`subjectFamily`) — the front end ranks the picker with
the same rule the API orders templates by, and the two must not drift.
"""

SUBJECT_FAMILIES = {
    "english": (
        "english",
        "english core",
        "english elective",
        "english language & literature",
        "english language and literature",
    ),
    "mathematics": (
        "maths",
        "mathematics",
        "mathematics standard",
        "mathematics basic",
        "applied mathematics",
    ),
}

_FAMILY_BY_SUBJECT = {
    name: family
    for family, names in SUBJECT_FAMILIES.items()
    for name in names
}


def subject_family(subject) -> str:
    """The family a subject belongs to, or the normalised subject itself.

    Deliberately NOT a general similarity match: Physics, Chemistry and Biology are their own
    families and must never collapse into Science, or a Class 11 Physics teacher would be handed
    the combined Class 10 Science paper.
    """
    key = " ".join(str(subject or "").strip().lower().split())
    return _FAMILY_BY_SUBJECT.get(key, key)


def same_subject(a, b) -> bool:
    family = subject_family(a)
    return bool(family) and family == subject_family(b)
