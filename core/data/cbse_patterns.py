"""
CBSE Exam Patterns & Assessment Structure — 2025-26
Sources: cbseacademic.nic.in SQPs, CBSE Circular Acad-30/2024, NEP 2020 implementation updates.

Key changes from 2024-25:
  - Class 10 board exam now held TWICE a year (Feb + May); best of 2 attempts counts.
  - Class 11 syllabus reduced ~30% across subjects (NEP-driven content rationalisation).
  - Class 11/12 section structures and marks distributions are UNCHANGED.
  - 50% competency-based questions policy continues for all classes 9-12.
"""

# ---------------------------------------------------------------------------
# ASSESSMENT / EXAM TYPES
# ---------------------------------------------------------------------------

EXAM_TYPES = {
    "unit_test": {
        "label": "Unit Test",
        "abbrev": "UT",
        "classes": "6-12",
        "marks": 20,
        "duration_minutes": 40,
        "syllabus_pct": 15,
        "conducted_by": "school",
        "month": "any",
        "status": "informal",
        "description": "Chapter-level test, school's discretion, not reported to CBSE.",
    },
    "pt1": {
        "label": "Periodic Test 1",
        "abbrev": "PT-1",
        "classes": "6-12",
        "marks": 20,
        "duration_minutes": 60,
        "syllabus_pct": 25,
        "conducted_by": "school",
        "month": "July-August",
        "status": "current",
        "ia_contribution": "Best 2 of 3 PTs averaged → 5 marks toward IA",
        "description": "First unit/chapter set; cumulative.",
    },
    "pt2": {
        "label": "Periodic Test 2",
        "abbrev": "PT-2",
        "classes": "6-12",
        "marks": 20,
        "duration_minutes": 60,
        "syllabus_pct": 50,
        "conducted_by": "school",
        "month": "September-October",
        "status": "current",
        "ia_contribution": "Best 2 of 3 PTs averaged → 5 marks toward IA",
        "description": "Expanded syllabus, pre-half-yearly.",
    },
    "pt3": {
        "label": "Periodic Test 3",
        "abbrev": "PT-3",
        "classes": "6-12",
        "marks": 20,
        "duration_minutes": 60,
        "syllabus_pct": 75,
        "conducted_by": "school",
        "month": "January-February",
        "status": "current",
        "ia_contribution": "Best 2 of 3 PTs averaged → 5 marks toward IA",
        "description": "Post-half-yearly syllabus.",
    },
    "half_yearly": {
        "label": "Half Yearly Exam",
        "abbrev": "HY",
        "classes": "6-12",
        "marks": 80,
        "duration_minutes": 180,
        "syllabus_pct": 50,
        "conducted_by": "school",
        "month": "September-October",
        "status": "current",
        "description": "First half of academic year. Standard practice, not a CBSE-reported component.",
    },
    "pre_board": {
        "label": "Pre-Board Exam",
        "abbrev": "Pre-Board",
        "classes": "10,12",
        "marks": 80,
        "duration_minutes": 180,
        "syllabus_pct": 100,
        "conducted_by": "school",
        "month": "November-January",
        "status": "current",
        "description": "2-3 rounds, full board-pattern paper, purely preparatory.",
    },
    "annual": {
        "label": "Annual / Final Exam",
        "abbrev": "Annual",
        "classes": "6-9,11",
        "marks": 80,
        "duration_minutes": 180,
        "syllabus_pct": 100,
        "conducted_by": "school",
        "month": "February-March",
        "status": "current",
        "description": "Full-year cumulative. School-conducted for Classes 6-9 and 11.",
    },
    "board_10": {
        "label": "Board Exam Class 10",
        "abbrev": "Board-10",
        "classes": "10",
        "marks": 80,
        "duration_minutes": 180,
        "syllabus_pct": 100,
        "conducted_by": "CBSE",
        "month": "February + May (two attempts)",
        "status": "current",
        "description": (
            "From 2025-26: two board exams per year (Exam 1: Feb, Exam 2: May). "
            "Best of 2 attempts is counted. Both cover full syllabus. "
            "80 marks theory + 20 marks IA = 100. Compulsory since 2017-18."
        ),
        "dual_exam": True,
        "exam_1_month": "February",
        "exam_2_month": "May",
        "scoring": "best_of_two",
    },
    "board_12": {
        "label": "Board Exam Class 12",
        "abbrev": "Board-12",
        "classes": "12",
        "marks_theory": "70 or 80 (subject-dependent)",
        "duration_minutes": 180,
        "syllabus_pct": 100,
        "conducted_by": "CBSE",
        "month": "February-March",
        "status": "current",
        "description": "Science/practical subjects: 70 theory + 30 practical. Others: 80 theory + 20 IA.",
    },
    # Legacy CCE system (discontinued 2017)
    "fa1": {"label": "Formative Assessment 1", "abbrev": "FA1", "status": "discontinued_2017", "marks_pct": 10},
    "fa2": {"label": "Formative Assessment 2", "abbrev": "FA2", "status": "discontinued_2017", "marks_pct": 10},
    "fa3": {"label": "Formative Assessment 3", "abbrev": "FA3", "status": "discontinued_2017", "marks_pct": 10},
    "fa4": {"label": "Formative Assessment 4", "abbrev": "FA4", "status": "discontinued_2017", "marks_pct": 10},
    "sa1": {"label": "Summative Assessment 1", "abbrev": "SA1", "status": "discontinued_2017", "marks_pct": 30},
    "sa2": {"label": "Summative Assessment 2", "abbrev": "SA2", "status": "discontinued_2017", "marks_pct": 30},
}

# ---------------------------------------------------------------------------
# INTERNAL ASSESSMENT (IA) STRUCTURE — current system
# ---------------------------------------------------------------------------

INTERNAL_ASSESSMENT = {
    "classes_6_8": {
        "total": 20,
        "components": {
            "periodic_test": 5,     # best 2 of 3 PTs
            "multiple_assessment": 5,
            "portfolio_notebook": 5,
            "subject_enrichment": 5,
        },
    },
    "classes_9_10": {
        "total": 20,
        "components": {
            "periodic_tests": 5,        # best 2 of 3 PTs, averaged, out of 5
            "multiple_assessment": 5,   # quizzes, oral, group work
            "portfolio_notebook": 5,
            "subject_enrichment": 5,    # lab/project/speaking
        },
    },
    "classes_11_12_non_practical": {
        "total": 20,
        "components": {"periodic_tests": 10, "projects_activities": 10},
    },
    "classes_11_12_practical": {
        "total": 30,
        "components": "See subject-specific practical breakdown",
    },
}

# ---------------------------------------------------------------------------
# QUESTION PAPER DESIGN — 50/20/30 POLICY (Acad-30/2024)
# ---------------------------------------------------------------------------

CBQ_POLICY_2025_26 = {
    "classes_9_10": {
        "competency_focused_pct": 50,   # MCQ, case-based, assertion-reason
        "objective_mcq_pct": 20,
        "constructed_response_pct": 30,  # SA, LA
    },
    "classes_11_12": {
        "competency_focused_pct": 50,
        "objective_mcq_pct": 20,
        "constructed_response_pct": 30,
    },
}

# ---------------------------------------------------------------------------
# SUBJECT PAPER PATTERNS — CLASS 12
# ---------------------------------------------------------------------------

PATTERNS = {}

# --- PHYSICS (042) ---
PATTERNS["Physics"] = {
    "code": "042", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 16, "marks_each": 1, "total": 16,
         "internal_choice": False, "notes": "Q1-12 MCQ, Q13-16 Assertion-Reason"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 5, "marks_each": 2, "total": 10,
         "internal_choice": True, "choices": "1 internal choice"},
        {"name": "C", "type": "Short Answer (SA)", "count": 7, "marks_each": 3, "total": 21,
         "internal_choice": True, "choices": "1 internal choice"},
        {"name": "D", "type": "Case-Based Questions", "count": 2, "marks_each": 4, "total": 8,
         "internal_choice": True, "notes": "Internal choice within each CBQ"},
        {"name": "E", "type": "Long Answer (LA)", "count": 3, "marks_each": 5, "total": 15,
         "internal_choice": True, "choices": "All 3 have internal choice"},
    ],
    "total_questions": 33,
    "practical_breakdown": {
        "two_experiments": 14, "activity": 3, "investigatory_project": 3,
        "practical_record": 5, "viva": 5,
    },
}

# --- CHEMISTRY (043) ---
PATTERNS["Chemistry"] = {
    "code": "043", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 16, "marks_each": 1, "total": 16, "internal_choice": False},
        {"name": "B", "type": "Short Answer I (SA-I)", "count": 5, "marks_each": 2, "total": 10, "internal_choice": True},
        {"name": "C", "type": "Short Answer II (SA-II)", "count": 7, "marks_each": 3, "total": 21, "internal_choice": True},
        {"name": "D", "type": "Case-Based Questions", "count": 2, "marks_each": 4, "total": 8, "internal_choice": True},
        {"name": "E", "type": "Long Answer (LA)", "count": 3, "marks_each": 5, "total": 15, "internal_choice": True, "choices": "All 3 have internal choice"},
    ],
    "total_questions": 33,
    "practical_breakdown": {
        "volumetric_analysis": 8, "salt_analysis": 8, "content_based_experiment": 6,
        "project_work": 4, "class_record_viva": 4,
    },
}

# --- BIOLOGY (044) ---
PATTERNS["Biology"] = {
    "code": "044", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 16, "marks_each": 1, "total": 16, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 5, "marks_each": 2, "total": 10, "internal_choice": True},
        {"name": "C", "type": "Short Answer (SA)", "count": 7, "marks_each": 3, "total": 21, "internal_choice": False},
        {"name": "D", "type": "Case-Based Questions", "count": 2, "marks_each": 4, "total": 8, "internal_choice": False},
        {"name": "E", "type": "Long Answer (LA)", "count": 3, "marks_each": 5, "total": 15, "internal_choice": True},
    ],
    "total_questions": 33,
    "notes": "Neat and properly labelled diagrams required where necessary.",
    "practical_breakdown": {
        "major_experiment": 5, "minor_experiment": 4, "slide_preparation": 5,
        "spotting": 7, "record_viva": 4, "investigatory_project": 5,
    },
}

# --- MATHEMATICS (041) — Class 12 ---
PATTERNS["Mathematics"] = {
    "code": "041", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 20, "marks_each": 1, "total": 20,
         "internal_choice": False, "notes": "Q1-18 MCQ, Q19-20 Assertion-Reason"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 5, "marks_each": 2, "total": 10,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "choices": "3 internal choices"},
        {"name": "D", "type": "Long Answer (LA)", "count": 4, "marks_each": 5, "total": 20,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "E", "type": "Case Study-Based", "count": 3, "marks_each": 4, "total": 12,
         "internal_choice": True, "notes": "1 sub-part choice each in 2 questions"},
    ],
    "total_questions": 38,
}

# --- COMPUTER SCIENCE (083) ---
PATTERNS["Computer Science"] = {
    "code": "083", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ / 1-mark (T/F, fill-blanks)", "count": 21, "marks_each": 1, "total": 21, "internal_choice": True},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 7, "marks_each": 2, "total": 14, "internal_choice": True},
        {"name": "C", "type": "Short Answer (SA)", "count": 3, "marks_each": 3, "total": 9, "internal_choice": True},
        {"name": "D", "type": "Long Answer I", "count": 4, "marks_each": 4, "total": 16, "internal_choice": True},
        {"name": "E", "type": "Long Answer II", "count": 2, "marks_each": 5, "total": 10, "internal_choice": True},
    ],
    "total_questions": 37,
    "notes": "All programming questions must use Python.",
    "practical_breakdown": {
        "lab_test_python_sql": 12, "report_file": 7, "project_work": 8, "viva": 3,
    },
}

# --- PHYSICAL EDUCATION (048) ---
PATTERNS["Physical Education"] = {
    "code": "048", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 18, "attempt": 18, "marks_each": 1, "total": 18, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA, ≤90 words)", "count": 6, "attempt": 5, "marks_each": 2, "total": 10, "internal_choice": True, "notes": "Attempt any 5 of 6"},
        {"name": "C", "type": "Short Answer (SA, ≤150 words)", "count": 6, "attempt": 5, "marks_each": 3, "total": 15, "internal_choice": True, "notes": "Attempt any 5 of 6"},
        {"name": "D", "type": "Case-Based Questions", "count": 3, "attempt": 3, "marks_each": 4, "total": 12, "internal_choice": True},
        {"name": "E", "type": "Long Answer (LA, ≤300 words)", "count": 4, "attempt": 3, "marks_each": 5, "total": 15, "internal_choice": True, "notes": "Attempt any 3 of 4"},
    ],
    "total_questions": 37,
    "practical_breakdown": {
        "physical_fitness_test": 6, "proficiency_games_sports": 7,
        "yogic_practices": 7, "record_file": 5, "viva": 5,
    },
}

# --- ACCOUNTANCY (055) ---
PATTERNS["Accountancy"] = {
    "code": "055", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "structure": "Part A (60 marks) + Part B — choose Analysis of Financial Statements OR Computerised Accounting (20 marks)",
    "sections": [
        {"name": "Part A — Q1-16", "type": "MCQ / Assertion-Reason / Objective", "count": 16, "marks_each": 1, "total": 16, "internal_choice": True, "notes": "7 of 16 have internal choice"},
        {"name": "Part A — Q17-20", "type": "Short Answer (SA, 3 marks)", "count": 4, "marks_each": 3, "total": 12, "internal_choice": True, "choices": "2 of 4"},
        {"name": "Part A — Q21-22", "type": "Short Answer II (4 marks)", "count": 2, "marks_each": 4, "total": 8, "internal_choice": False},
        {"name": "Part A — Q23-26", "type": "Long Answer (LA, 6 marks)", "count": 4, "marks_each": 6, "total": 24, "internal_choice": True, "choices": "2 of 4"},
        {"name": "Part B — Q27-30", "type": "MCQ / Objective", "count": 4, "marks_each": 1, "total": 4, "internal_choice": True},
        {"name": "Part B — Q31-32", "type": "Short Answer (3 marks)", "count": 2, "marks_each": 3, "total": 6, "internal_choice": False},
        {"name": "Part B — Q33", "type": "Short Answer (4 marks)", "count": 1, "marks_each": 4, "total": 4, "internal_choice": True},
        {"name": "Part B — Q34", "type": "Long Answer (6 marks)", "count": 1, "marks_each": 6, "total": 6, "internal_choice": False},
    ],
    "total_questions": 34,
    "internal_assessment_breakdown": {"project_file": 12, "viva": 8},
}

# --- BUSINESS STUDIES (054) ---
PATTERNS["Business Studies"] = {
    "code": "054", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "Q1-20", "type": "MCQ / Assertion-Reason / Statement-based", "count": 20, "marks_each": 1, "total": 20, "internal_choice": False},
        {"name": "Q21-24", "type": "Short Answer I (SA1, 3 marks)", "count": 4, "marks_each": 3, "total": 12, "internal_choice": True, "choices": "2 of 4"},
        {"name": "Q25-30", "type": "Short Answer II (SA2, 4 marks)", "count": 6, "marks_each": 4, "total": 24, "internal_choice": True, "choices": "2 of 6"},
        {"name": "Q31-34", "type": "Long Answer (LA, 6 marks)", "count": 4, "marks_each": 6, "total": 24, "internal_choice": True, "choices": "1 of 4"},
    ],
    "total_questions": 34,
    "word_limits": {"3_mark": "50-75 words", "4_mark": "150 words", "6_mark": "200 words"},
}

# --- ECONOMICS (030) ---
PATTERNS["Economics"] = {
    "code": "030", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "structure": "Section A (Macroeconomics, 40 marks) + Section B (Indian Economic Development, 40 marks)",
    "sections": [
        {"name": "A — Q1-10 / B — Q18-27", "type": "MCQ (Standalone + AR + Case-based)", "count": 10, "marks_each": 1, "total": 10, "internal_choice": False, "notes": "Per section"},
        {"name": "A — Q11-12 / B — Q28-29", "type": "Short Answer I (SA1, 60-80 words)", "count": 2, "marks_each": 3, "total": 6, "internal_choice": True, "choices": "1 internal choice", "notes": "Per section"},
        {"name": "A — Q13-15 / B — Q30-32", "type": "Short Answer II (SA2, 80-100 words)", "count": 3, "marks_each": 4, "total": 12, "internal_choice": True, "choices": "1 internal choice", "notes": "Per section"},
        {"name": "A — Q16-17 / B — Q33-34", "type": "Long Answer (LA, 100-150 words)", "count": 2, "marks_each": 6, "total": 12, "internal_choice": True, "choices": "1 internal choice", "notes": "Per section"},
    ],
    "total_questions": 34,
}

# --- ENGLISH CORE (301) ---
PATTERNS["English Core"] = {
    "code": "301", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A — Reading Skills", "total": 22,
         "sub": [
             {"q": "Q1", "type": "Unseen prose/factual passage (~750 words)", "marks": 12, "sub_questions": 10, "types": "MCQ + SA (40-50 words)"},
             {"q": "Q2", "type": "Case-based factual passage with charts/data", "marks": 10, "sub_questions": 8, "types": "MCQ + SA"},
         ]},
        {"name": "B — Creative Writing Skills", "total": 18,
         "sub": [
             {"q": "Q3", "type": "Notice writing (≤50 words)", "marks": 4, "choice": "1 of 2"},
             {"q": "Q4", "type": "Formal/Informal Invitation & Reply (≤50 words)", "marks": 4, "choice": "1 of 2"},
             {"q": "Q5", "type": "Letter (job application + bio-data / letter to editor, 120-150 words)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q6", "type": "Article or Report Writing (120-150 words)", "marks": 5, "choice": "1 of 2"},
         ]},
        {"name": "C — Literature (Flamingo + Vistas)", "total": 40,
         "sub": [
             {"q": "Q7", "type": "Flamingo Poetry extract (6 sub-q: MCQ+SA)", "marks": 6, "choice": "1 of 2 extracts"},
             {"q": "Q8", "type": "Vistas Prose extract (4 sub-q: MCQ+objective)", "marks": 4, "choice": "1 of 2 extracts"},
             {"q": "Q9", "type": "Flamingo Prose extract (6 sub-q)", "marks": 6, "choice": "1 of 2 extracts"},
             {"q": "Q10", "type": "Flamingo short answer (40-50 words each)", "marks": 10, "attempt": "5 of 6", "marks_each": 2},
             {"q": "Q11", "type": "Vistas short answer (40-50 words each)", "marks": 4, "attempt": "2 of 3", "marks_each": 2},
             {"q": "Q12", "type": "Flamingo long answer (120-150 words)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q13", "type": "Vistas long answer (120-150 words)", "marks": 5, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 13,
    "internal_assessment_breakdown": {"listening": 5, "speaking": 5, "project_viva": 10},
}

# --- HINDI CORE (302) ---
PATTERNS["Hindi Core"] = {
    "code": "302", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "खंड-क — Unseen Comprehension", "total": 18,
         "sub": [
             {"q": "Q1", "type": "Prose passage (Gadyansh)", "marks": 10, "sub_questions": "7 (3 MCQ×1 + 1×1 + 3×2)"},
             {"q": "Q2", "type": "Poetry passage (Padyansh)", "marks": 8, "sub_questions": "6 (4 MCQ×1 + 2×2)"},
         ]},
        {"name": "खंड-ख — Expression & Media", "total": 22,
         "sub": [
             {"q": "Q3", "type": "Creative writing (Rachanatmak Lekh, ~120 words)", "marks": 6, "choice": "1 of 3"},
             {"q": "Q4", "type": "Short answers from Abhivyakti aur Madhyam (~40 words)", "marks": 8, "attempt": "4 of 5", "marks_each": 2},
             {"q": "Q5", "type": "Long answers from Abhivyakti aur Madhyam (~80 words)", "marks": 8, "attempt": "2 of 3", "marks_each": 4},
         ]},
        {"name": "खंड-ग — Aaroh + Vitaan Literature", "total": 40,
         "sub": [
             {"q": "Q6", "type": "Aaroh Poetry extract MCQ", "marks": 5, "count": 5, "marks_each": 1},
             {"q": "Q7", "type": "Aaroh Poetry short answer (~60 words)", "marks": 6, "attempt": "2 of 3", "marks_each": 3},
             {"q": "Q8", "type": "Aaroh Poetry very short answer (~40 words)", "marks": 4, "attempt": "2 of 3", "marks_each": 2},
             {"q": "Q9", "type": "Aaroh Prose extract MCQ", "marks": 5, "count": 5, "marks_each": 1},
             {"q": "Q10", "type": "Aaroh Prose short answer (~60 words)", "marks": 6, "attempt": "2 of 3", "marks_each": 3},
             {"q": "Q11", "type": "Aaroh Prose very short answer (~40 words)", "marks": 4, "attempt": "2 of 3", "marks_each": 2},
             {"q": "Q12", "type": "Vitaan long answer (~100 words)", "marks": 10, "attempt": "2 of 3", "marks_each": 5},
         ]},
    ],
    "total_questions": 12,
    "internal_assessment_breakdown": {"listening_shravan": 10, "speaking_vachan": 10},
}

# --- HISTORY (027) ---
PATTERNS["History"] = {
    "code": "027", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ incl. Assertion-Reason + image-based", "count": 21, "marks_each": 1, "total": 21, "internal_choice": False},
        {"name": "B", "type": "Short Answer (SA, 60-80 words)", "count": 6, "marks_each": 3, "total": 18, "internal_choice": True, "choices": "2 of 6 have OR"},
        {"name": "C", "type": "Long Answer (LA, 300-350 words)", "count": 3, "marks_each": 8, "total": 24, "internal_choice": True, "choices": "All 3 have OR"},
        {"name": "D", "type": "Source-Based (3 sub-q: 1+1+2 marks each)", "count": 3, "marks_each": 4, "total": 12, "internal_choice": False},
        {"name": "E", "type": "Map Work", "count": 1, "marks_each": 5, "total": 5, "internal_choice": True,
         "notes": "Q34A: locate 3 sites (3m), Q34B: identify 2 marked centres (2m)"},
    ],
    "total_questions": 34,
}

# --- GEOGRAPHY (029) ---
PATTERNS["Geography"] = {
    "code": "029", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ", "count": 17, "marks_each": 1, "total": 17, "internal_choice": False},
        {"name": "B", "type": "Source-Based (passage/data analysis)", "count": 2, "marks_each": 3, "total": 6, "internal_choice": False},
        {"name": "C", "type": "Short Answer (SA, 80-100 words)", "count": 4, "marks_each": 3, "total": 12, "internal_choice": True, "choices": "All 4 have OR"},
        {"name": "D", "type": "Long Answer (LA, 120-150 words)", "count": 5, "marks_each": 5, "total": 25, "internal_choice": True},
        {"name": "E", "type": "Map Work", "count": 2, "marks_each": 5, "total": 10, "internal_choice": True,
         "notes": "Q29: World map (any 5 of 7 features), Q30: India map (any 5 of 7 features)"},
    ],
    "total_questions": 30,
    "curriculum_split": {"fundamentals_of_human_geography": 35, "india_people_economy": 35},
}

# --- POLITICAL SCIENCE (028) ---
PATTERNS["Political Science"] = {
    "code": "028", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ", "count": 12, "marks_each": 1, "total": 12, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA, 50-60 words)", "count": 6, "marks_each": 2, "total": 12, "internal_choice": False},
        {"name": "C", "type": "Long Answer I (100-120 words)", "count": 5, "marks_each": 4, "total": 20, "internal_choice": True, "choices": "2 of 5 have OR"},
        {"name": "D", "type": "Source-Based (Passage + Cartoon + Map)", "count": 3, "marks_each": 4, "total": 12, "internal_choice": True,
         "notes": "Q24 passage, Q25 cartoon, Q26 map"},
        {"name": "E", "type": "Long Answer II / Essay (170-180 words)", "count": 4, "marks_each": 6, "total": 24, "internal_choice": True, "choices": "All 4 have OR"},
    ],
    "total_questions": 30,
    "curriculum_split": {"contemporary_world_politics": 40, "politics_in_india": 40},
}

# --- SOCIOLOGY (039) ---
PATTERNS["Sociology"] = {
    "code": "039", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ incl. Assertion-Reason", "count": 16, "marks_each": 1, "total": 16, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA, ≤30 words)", "count": 9, "marks_each": 2, "total": 18, "internal_choice": True, "choices": "2 of 9 have OR"},
        {"name": "C", "type": "Short Answer (SA, ≤80 words)", "count": 7, "marks_each": 4, "total": 28, "internal_choice": True, "choices": "1 of 7 has OR"},
        {"name": "D", "type": "Long Answer (LA, ≤200 words)", "count": 3, "marks_each": 6, "total": 18, "internal_choice": False,
         "notes": "Q33 must reference given graphics/data"},
    ],
    "total_questions": 35,
}

# --- PSYCHOLOGY (037) ---
PATTERNS["Psychology"] = {
    "code": "037", "classes": ["11", "12"],
    "theory_marks": 70, "practical_marks": 30, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ", "count": 15, "marks_each": 1, "total": 15, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer I (VSA, 30 words)", "count": 6, "marks_each": 2, "total": 12, "internal_choice": True},
        {"name": "C", "type": "Short Answer II (SA, 60 words)", "count": 3, "marks_each": 3, "total": 9, "internal_choice": True},
        {"name": "D", "type": "Long Answer I (LA-I, 120 words)", "count": 4, "marks_each": 4, "total": 16, "internal_choice": True},
        {"name": "E", "type": "Long Answer II (LA-II, 200 words)", "count": 2, "marks_each": 6, "total": 12, "internal_choice": True, "choices": "Both have OR"},
        {"name": "F", "type": "Case-Based (2 cases, 20-30 words)", "count": 4, "marks_each": "1 or 2", "total": 6, "internal_choice": False},
    ],
    "total_questions": 34,
    "practical_breakdown": {"two_practicals": 15, "practical_file": 10, "viva": 5},
}

# ---------------------------------------------------------------------------
# SUBJECT PAPER PATTERNS — CLASS 9-10
# ---------------------------------------------------------------------------

# --- MATHEMATICS STANDARD (Class 10) ---
PATTERNS["Mathematics Standard"] = {
    "code": "041", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 20, "marks_each": 1, "total": 20,
         "internal_choice": False, "notes": "Q1-18 MCQ, Q19-20 Assertion-Reason"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 5, "marks_each": 2, "total": 10,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "choices": "3 internal choices"},
        {"name": "D", "type": "Long Answer (LA)", "count": 4, "marks_each": 5, "total": 20,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "E", "type": "Case Study-Based", "count": 3, "marks_each": 4, "total": 12,
         "internal_choice": True, "notes": "Sub-part choice in 2 of 3"},
    ],
    "total_questions": 38,
}

# --- MATHEMATICS BASIC (Class 10) ---
PATTERNS["Mathematics Basic"] = {
    "code": "241", "classes": ["10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "notes": "Same syllabus as Standard, easier difficulty level. Same section structure.",
    "sections": [
        {"name": "A", "type": "MCQ + Assertion-Reason", "count": 20, "marks_each": 1, "total": 20, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 5, "marks_each": 2, "total": 10, "internal_choice": True},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18, "internal_choice": True},
        {"name": "D", "type": "Long Answer (LA)", "count": 4, "marks_each": 5, "total": 20, "internal_choice": True},
        {"name": "E", "type": "Case Study-Based", "count": 3, "marks_each": 4, "total": 12, "internal_choice": True},
    ],
    "total_questions": 38,
}

# --- SCIENCE (Class 9-10) ---
# Structure: per-subject sections (Biology § A, Chemistry § B, Physics § C)
# Each section total verified: 26 + 26 + 28 = 80 marks.
PATTERNS["Science"] = {
    "code": "086", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "compound_subject": True,
    "component_subjects": ["Biology", "Chemistry", "Physics"],
    "sections": [
        {
            # SQP 2025-26: Q1-16 = 30m (7MCQ+2AR+3VSA+2SA+1CBQ+1LA)
            "name": "A", "subject": "Biology",
            "count": 16, "total": 30,
            "internal_choice": True, "choices": 2,
            "hots": 2, "cbq": 1,
            "notes": (
                "Q1-7: MCQ (1m each). Q8-9: Assertion-Reason (1m each). "
                "Q10-12: VSA 2m each (Q11 has internal choice A or B). "
                "Q13-14: SA 3m each. "
                "Q15: Scenario/CBQ 4m (attempt sub-part A or B + C + D). "
                "Q16: LA 5m (internal choice A or B)."
            ),
            "question_types": [
                {"range": "Q1-7",   "type": "MCQ",                 "count": 7, "marks_each": 1, "total": 7},
                {"range": "Q8-9",   "type": "Assertion-Reason",     "count": 2, "marks_each": 1, "total": 2},
                {"range": "Q10-12", "type": "VSA",                  "count": 3, "marks_each": 2, "total": 6,
                 "internal_choice": True, "choice_at": "Q11"},
                {"range": "Q13-14", "type": "Short Answer (SA)",    "count": 2, "marks_each": 3, "total": 6},
                {"range": "Q15",    "type": "Source-Based/CBQ",     "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 2}, {"marks": 1}, {"marks": 1}],
                 "notes": "Sub-part A-or-B (2m) + C (1m) + D (1m); attempt A or B"},
                {"range": "Q16",    "type": "Long Answer (LA)",     "count": 1, "marks_each": 5, "total": 5,
                 "internal_choice": True},
            ],
        },
        {
            # SQP 2025-26: Q17-29 = 25m (7MCQ+1AR+1VSA+2SA+1CBQ+1LA)
            "name": "B", "subject": "Chemistry",
            "count": 13, "total": 25,
            "internal_choice": True, "choices": 2,
            "hots": 2, "cbq": 1,
            "notes": (
                "Q17-23: MCQ (1m each). Q24: Assertion-Reason (1m). "
                "Q25: VSA 2m. "
                "Q26: SA 3m (internal choice A or B). Q27: SA 3m. "
                "Q28: Scenario/CBQ 4m (sub-part B has OR). "
                "Q29: LA 5m (internal choice A or B)."
            ),
            "question_types": [
                {"range": "Q17-23", "type": "MCQ",                 "count": 7, "marks_each": 1, "total": 7},
                {"range": "Q24",    "type": "Assertion-Reason",     "count": 1, "marks_each": 1, "total": 1},
                {"range": "Q25",    "type": "VSA",                  "count": 1, "marks_each": 2, "total": 2},
                {"range": "Q26-27", "type": "Short Answer (SA)",    "count": 2, "marks_each": 3, "total": 6,
                 "internal_choice": True, "choice_at": "Q26"},
                {"range": "Q28",    "type": "Source-Based/CBQ",     "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 1}, {"marks": 1}, {"marks": 2}],
                 "notes": "Parts A + B-or-OR + C; sub-part B has internal OR"},
                {"range": "Q29",    "type": "Long Answer (LA)",     "count": 1, "marks_each": 5, "total": 5,
                 "internal_choice": True},
            ],
        },
        {
            # SQP 2025-26: Q30-39 = 25m (2MCQ+1AR+2VSA+3SA+1CBQ+1LA)
            "name": "C", "subject": "Physics",
            "count": 10, "total": 25,
            "internal_choice": True, "choices": 2,
            "hots": 2, "cbq": 1,
            "notes": (
                "Q30-31: MCQ (1m each). Q32: Assertion-Reason (1m). "
                "Q33: VSA 2m. Q34: VSA 2m (internal choice A or B). "
                "Q35-37: SA 3m each. "
                "Q38: Scenario/CBQ 4m (attempt sub-part C or D). "
                "Q39: LA 5m (internal choice A or B)."
            ),
            "question_types": [
                {"range": "Q30-31", "type": "MCQ",                 "count": 2, "marks_each": 1, "total": 2},
                {"range": "Q32",    "type": "Assertion-Reason",     "count": 1, "marks_each": 1, "total": 1},
                {"range": "Q33-34", "type": "VSA",                  "count": 2, "marks_each": 2, "total": 4,
                 "internal_choice": True, "choice_at": "Q34"},
                {"range": "Q35-37", "type": "Short Answer (SA)",    "count": 3, "marks_each": 3, "total": 9},
                {"range": "Q38",    "type": "Source-Based/CBQ",     "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 1}, {"marks": 1}, {"marks": 2}],
                 "notes": "Parts A + B + attempt C or D; sub-parts C and D have internal OR"},
                {"range": "Q39",    "type": "Long Answer (LA)",     "count": 1, "marks_each": 5, "total": 5,
                 "internal_choice": True},
            ],
        },
    ],
    "total_questions": 39,
    "notes": "Biology § A (30m) + Chemistry § B (25m) + Physics § C (25m) = 80m. Verified against CBSE SQP 2025-26.",
}

# --- SOCIAL SCIENCE (Class 9-10) ---
# Structure: per-subject sections (History § A, Geography § B, Political Science § C, Economics § D)
PATTERNS["Social Science"] = {
    "code": "087", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "compound_subject": True,
    "component_subjects": ["History", "Geography", "Political Science", "Economics"],
    "sections": [
        {
            "name": "A", "subject": "History",
            "count": 9, "total": 20,
            "internal_choice": True, "choices": 3,
            "hots": 2, "cbq": 1,
            "notes": "Q1-4 MCQ (1M each). Q5 VSA 2M (OR). Q6 SA 3M (OR). Q7 LA 5M (OR). Q8 Source-Based CBQ 4M (3 sub-Qs). Q9 Map Work 2M.",
            "question_types": [
                {"range": "Q1-4", "type": "MCQ / Objective", "count": 4, "marks_each": 1, "total": 4},
                {"range": "Q5", "type": "VSA — max 40 words", "count": 1, "marks_each": 2, "total": 2},
                {"range": "Q6", "type": "Short Answer — max 60 words", "count": 1, "marks_each": 3, "total": 3},
                {"range": "Q7", "type": "Long Answer — max 120 words", "count": 1, "marks_each": 5, "total": 5},
                {"range": "Q8", "type": "Source-Based / CBQ (3 sub-questions)", "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 1}, {"marks": 1}, {"marks": 2}]},
                {"range": "Q9", "type": "Map Work", "count": 1, "marks_each": 2, "total": 2},
            ],
        },
        {
            "name": "B", "subject": "Geography",
            "count": 10, "total": 20,
            "internal_choice": True, "choices": 2,
            "hots": 2, "cbq": 1,
            "notes": "Q10-15 MCQ (1M each). Q16 VSA 2M. Q17 LA 5M (OR). Q18 Source-Based CBQ 4M (3 sub-Qs). Q19 Map Work 3M (Part I has OR).",
            "question_types": [
                {"range": "Q10-15", "type": "MCQ / Objective", "count": 6, "marks_each": 1, "total": 6},
                {"range": "Q16", "type": "VSA — max 40 words", "count": 1, "marks_each": 2, "total": 2},
                {"range": "Q17", "type": "Long Answer — max 120 words", "count": 1, "marks_each": 5, "total": 5},
                {"range": "Q18", "type": "Source-Based / CBQ (3 sub-questions)", "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 1}, {"marks": 2}, {"marks": 1}]},
                {"range": "Q19", "type": "Map Work (Part I OR + Part II any 2 of 3)", "count": 1, "marks_each": 3, "total": 3},
            ],
        },
        {
            "name": "C", "subject": "Political Science",
            "count": 9, "total": 20,
            "internal_choice": True, "choices": 1,
            "hots": 2, "cbq": 1,
            "notes": "Q20-23 MCQ incl. Assertion-Reason (1M each). Q24-25 VSA 2M each. Q26 SA 3M. Q27 LA 5M (OR). Q28 CBQ 4M (3 sub-Qs).",
            "question_types": [
                {"range": "Q20-23", "type": "MCQ / Assertion-Reason", "count": 4, "marks_each": 1, "total": 4},
                {"range": "Q24-25", "type": "VSA — max 40 words", "count": 2, "marks_each": 2, "total": 4},
                {"range": "Q26", "type": "Short Answer — max 60 words", "count": 1, "marks_each": 3, "total": 3},
                {"range": "Q27", "type": "Long Answer — max 120 words", "count": 1, "marks_each": 5, "total": 5},
                {"range": "Q28", "type": "Case-Based / CBQ (3 sub-questions)", "count": 1, "marks_each": 4, "total": 4,
                 "sub_questions": [{"marks": 1}, {"marks": 1}, {"marks": 2}]},
            ],
        },
        {
            "name": "D", "subject": "Economics",
            "count": 10, "total": 20,
            "internal_choice": True, "choices": 1,
            "hots": 2, "cbq": 0,
            "notes": "Q29-34 MCQ (1M each). Q35-37 SA 3M each. Q38 LA 5M (OR). No CBQ in Economics.",
            "question_types": [
                {"range": "Q29-34", "type": "MCQ / Objective", "count": 6, "marks_each": 1, "total": 6},
                {"range": "Q35-37", "type": "Short Answer — max 60 words", "count": 3, "marks_each": 3, "total": 9},
                {"range": "Q38", "type": "Long Answer — max 120 words", "count": 1, "marks_each": 5, "total": 5},
            ],
        },
    ],
    "total_questions": 38,
    "curriculum": "History + Geography + Political Science (Civics) + Economics",
}

# --- ENGLISH LANGUAGE & LITERATURE (Class 9-10) ---
PATTERNS["English Language & Literature"] = {
    "code": "184", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A — Reading", "total": 20,
         "sub": [
             {"q": "Q1", "type": "Unseen prose passage (factual/descriptive, 450-500 words)", "marks": 10, "types": "MCQ (5×1) + SA (5×1)"},
             {"q": "Q2", "type": "Unseen case-based passage with visual (400-450 words)", "marks": 10, "types": "MCQ (5×1) + SA (5×1)"},
         ]},
        {"name": "B — Grammar", "total": 10,
         "sub": [
             {"q": "Q3-Q7", "type": "Gap-filling, editing, omission, reordering (1 mark each)", "marks": 10},
         ]},
        {"name": "C — Writing", "total": 10,
         "sub": [
             {"q": "Q8", "type": "Formal letter / Notice / Email (100-120 words)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q9", "type": "Paragraph / Article / Report (100-150 words)", "marks": 5, "choice": "1 of 2"},
         ]},
        {"name": "D — Literature (First Flight + Footprints)", "total": 40,
         "sub": [
             {"q": "Q10", "type": "Prose extract (First Flight) — 5 sub-q MCQ+VSA", "marks": 5, "choice": "1 of 2 extracts"},
             {"q": "Q11", "type": "Poetry extract (First Flight) — 5 sub-q MCQ+VSA", "marks": 5, "choice": "1 of 2 extracts"},
             {"q": "Q12", "type": "Footprints extract — 4 sub-q MCQ+VSA", "marks": 4, "choice": "1 of 2 extracts"},
             {"q": "Q13-Q15", "type": "Short answer (First Flight, 40-50 words, 2 marks)", "marks": 6, "attempt": "3 of 4"},
             {"q": "Q16", "type": "Short answer (Footprints, 40-50 words, 2 marks)", "marks": 4, "attempt": "2 of 3"},
             {"q": "Q17", "type": "Long answer (First Flight, 100-120 words, 5 marks)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q18", "type": "Long answer (Footprints / value-based, 100-120 words, 5 marks)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q19", "type": "Long answer (First Flight, 100-120 words, 6 marks)", "marks": 6, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 19,
}

# --- HINDI COURSE A (Class 9-10) ---
PATTERNS["Hindi Course A"] = {
    "code": "002", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "खंड-क — Apathit Bodh (Unseen)", "total": 16,
         "sub": [
             {"q": "Q1", "type": "Unseen Gadyansh (Prose, ~500 words)", "marks": 10, "sub": "5 MCQ + 5 VSA"},
             {"q": "Q2", "type": "Unseen Padyansh (Poetry)", "marks": 6, "sub": "3 MCQ + 3 VSA"},
         ]},
        {"name": "खंड-ख — Vyakaran (Grammar)", "total": 16,
         "sub": [
             {"type": "Shabdalankaar, Sandhi/Samaas, Muhavare, Ras, Vaakya bhed", "marks": 16, "format": "Mostly MCQ + 2-mark SA"},
         ]},
        {"name": "खंड-ग — Sahitya (Textbooks)", "total": 36,
         "sub": [
             {"q": "Q — Kshitij (Poetry/Prose)", "marks": 25, "types": "Extracts MCQ+SA + Long answer"},
             {"q": "Q — Kritika (Supplementary)", "marks": 11, "types": "SA + LA"},
         ]},
        {"name": "खंड-घ — Lekhan (Writing)", "total": 12,
         "sub": [
             {"q": "Q — Patra Lekhan (Letter)", "marks": 5},
             {"q": "Q — Nibandh/Anuched (Essay/Paragraph)", "marks": 7},
         ]},
    ],
    "total_questions": 15,
    "notes": "Exact sub-question distribution varies slightly year to year.",
}

# --- HINDI COURSE B (Class 9-10) ---
PATTERNS["Hindi Course B"] = {
    "code": "085", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "notes": "Similar structure to Course A but uses Sparsh (poetry/prose) + Sanchayan (supplementary). Slightly easier level than Course A.",
    "sections": [
        {"name": "खंड-क — Apathit Bodh (Unseen)", "total": 14,
         "sub": [
             {"q": "Q1", "type": "Unseen Gadyansh (Prose, ~300 words)", "marks": 8, "sub": "MCQ + VSA"},
             {"q": "Q2", "type": "Unseen Padyansh (Poetry)", "marks": 6, "sub": "MCQ + VSA"},
         ]},
        {"name": "खंड-ख — Vyakaran (Grammar)", "total": 16,
         "sub": [
             {"type": "Pad-parichay, Rachna ke aadhar par vakya bhed, Vachya, Alankar, Muhavare", "marks": 16, "format": "Mostly MCQ + 2-mark SA"},
         ]},
        {"name": "खंड-ग — Sahitya (Sparsh + Sanchayan)", "total": 34,
         "sub": [
             {"q": "Q — Sparsh (Poetry/Prose)", "marks": 24, "types": "Extracts MCQ+SA + Long answer"},
             {"q": "Q — Sanchayan (Supplementary)", "marks": 10, "types": "SA + LA"},
         ]},
        {"name": "खंड-घ — Lekhan (Writing)", "total": 16,
         "sub": [
             {"q": "Q — Patra Lekhan (Letter)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q — Anuched Lekhan (Paragraph)", "marks": 6, "choice": "1 of 3"},
             {"q": "Q — Vigyapan / Soochna / Samvad Lekhan", "marks": 5, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 14,
    "notes_detail": "Exact sub-question distribution varies year to year.",
}

# ---------------------------------------------------------------------------
# SUBJECT PAPER PATTERNS — CLASSES 6, 7, 8 (Middle School)
# Annual / Final Exam: 80 marks theory + 20 marks IA = 100
# Source: CBSE Assessment Policy 2024-25 (Acad-30/2024), school-conducted.
# ---------------------------------------------------------------------------

PATTERNS_MIDDLE_SCHOOL = {}

# --- MATHEMATICS (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["Mathematics"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "Objective Type (MCQ / True-False / Fill in the Blanks)",
         "count": 20, "marks_each": 1, "total": 20, "internal_choice": False,
         "notes": "8 MCQ + 6 True/False + 6 Fill in the blanks"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 6, "marks_each": 2, "total": 12,
         "internal_choice": True, "notes": "1 internal choice; show working"},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "notes": "1 internal choice; step-wise marks"},
        {"name": "D", "type": "Long Answer (LA)", "count": 6, "marks_each": 5, "total": 30,
         "internal_choice": True, "notes": "2 internal choices"},
    ],
    "total_questions": 38,
}

# --- SCIENCE (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["Science"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "Objective Type (MCQ / Match the Column / True-False)",
         "count": 20, "marks_each": 1, "total": 20, "internal_choice": False,
         "notes": "8 MCQ + 6 Match the Column + 6 True/False"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 6, "marks_each": 2, "total": 12,
         "internal_choice": True, "notes": "Definition / one-liner with diagram where needed"},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "notes": "1 internal choice; labelled diagrams expected"},
        {"name": "D", "type": "Long Answer / Diagram-Based", "count": 6, "marks_each": 5, "total": 30,
         "internal_choice": True, "notes": "2 internal choices; includes experiment / diagram questions"},
    ],
    "total_questions": 38,
}

# --- SOCIAL SCIENCE (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["Social Science"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "Objective Type (MCQ / True-False / Match / Fill in the Blanks)",
         "count": 20, "marks_each": 1, "total": 20, "internal_choice": False,
         "notes": "Covers History, Geography, Civics (Political Science)"},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 6, "marks_each": 2, "total": 12,
         "internal_choice": False, "notes": "One-liners / definitions"},
        {"name": "C", "type": "Short Answer (SA)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "notes": "1 internal choice; reason-based / explain questions"},
        {"name": "D", "type": "Long Answer / Map Work", "count": 6, "marks_each": 5, "total": 30,
         "internal_choice": True, "notes": "Includes compulsory map work (locate & label)"},
    ],
    "total_questions": 38,
    "curriculum": "History + Geography + Civics (Political Science)",
}

# --- ENGLISH LANGUAGE & LITERATURE (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["English Language & Literature"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A — Reading", "total": 20,
         "sub": [
             {"q": "Q1", "type": "Unseen prose passage (factual, 300-350 words)", "marks": 10,
              "types": "5 MCQ (1M each) + 5 VSA (1M each)"},
             {"q": "Q2", "type": "Unseen poem or short passage", "marks": 10,
              "types": "5 MCQ (1M each) + 5 VSA (1M each)"},
         ]},
        {"name": "B — Grammar", "total": 20,
         "sub": [
             {"q": "Q3-Q7", "type": "Tenses, Articles, Prepositions, Voice, Narration, Sentence transformation",
              "marks": 20, "types": "Fill in the blanks / MCQ / Rewrite (1-2M each)"},
         ]},
        {"name": "C — Writing", "total": 20,
         "sub": [
             {"q": "Q8", "type": "Formal / Informal Letter or Notice", "marks": 10, "choice": "1 of 2"},
             {"q": "Q9", "type": "Paragraph / Short composition (80-100 words)", "marks": 10, "choice": "1 of 2"},
         ]},
        {"name": "D — Literature (Textbook + Supplementary)", "total": 20,
         "sub": [
             {"q": "Q10", "type": "Prose extract — comprehension sub-questions", "marks": 5, "choice": "1 of 2 extracts"},
             {"q": "Q11", "type": "Poetry extract — comprehension sub-questions", "marks": 5, "choice": "1 of 2 extracts"},
             {"q": "Q12-Q13", "type": "Short answer questions (Textbook prose/poem)", "marks": 6,
              "types": "2M each, attempt 3 of 4"},
             {"q": "Q14", "type": "Long answer (value-based / character-based, 80-100 words)", "marks": 4,
              "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 14,
}

# --- HINDI COURSE A (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["Hindi Course A"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "खंड-क — अपठित बोध (Unseen)", "total": 15,
         "sub": [
             {"q": "Q1", "type": "अपठित गद्यांश (Unseen Prose ~300 शब्द)", "marks": 10,
              "types": "5 MCQ + 5 VSA (1M each)"},
             {"q": "Q2", "type": "अपठित पद्यांश (Unseen Poem)", "marks": 5,
              "types": "MCQ / VSA"},
         ]},
        {"name": "खंड-ख — व्याकरण (Grammar)", "total": 15,
         "sub": [
             {"type": "संज्ञा, सर्वनाम, विशेषण, क्रिया, काल, वाक्य-भेद, मुहावरे, विराम-चिह्न",
              "marks": 15, "format": "MCQ + रिक्त स्थान + मिलान (1-2M each)"},
         ]},
        {"name": "खंड-ग — साहित्य (Literature — Vasant / Durva)", "total": 30,
         "sub": [
             {"q": "गद्यांश / पद्यांश", "type": "पाठ्यपुस्तक से प्रसंग — बोध प्रश्न", "marks": 10,
              "types": "MCQ + लघु उत्तर"},
             {"q": "लघु उत्तरीय", "type": "प्रश्न (Short Answer, 2M each)", "marks": 10,
              "types": "4-5 questions, 2M each"},
             {"q": "दीर्घ उत्तरीय", "type": "प्रश्न (Long Answer, 5M)", "marks": 10,
              "choice": "1 of 2"},
         ]},
        {"name": "खंड-घ — लेखन (Writing)", "total": 20,
         "sub": [
             {"q": "Q — पत्र लेखन", "type": "औपचारिक / अनौपचारिक पत्र", "marks": 10, "choice": "1 of 2"},
             {"q": "Q — अनुच्छेद / निबंध", "type": "80-100 शब्द", "marks": 10, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 16,
    "notes": "Textbooks: Vasant (main) + Durva (supplementary) as per class.",
}

# --- SANSKRIT (Classes 6-8) ---
PATTERNS_MIDDLE_SCHOOL["Sanskrit"] = {
    "classes": ["6", "7", "8"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "Objective Type (MCQ / Match / Fill in the Blanks)", "count": 20, "marks_each": 1, "total": 20,
         "internal_choice": False, "notes": "Grammar, vocabulary, sandhi/samaas recognition"},
        {"name": "B", "type": "अपठित गद्यांश (Unseen Passage)", "count": 5, "marks_each": 2, "total": 10,
         "internal_choice": False, "notes": "Translation or comprehension sub-questions"},
        {"name": "C", "type": "व्याकरण (Grammar Application)", "count": 6, "marks_each": 3, "total": 18,
         "internal_choice": True, "notes": "Roop (Shabd/Dhatu), Sandhi, Karak, Shloka meaning; 1 internal choice"},
        {"name": "D", "type": "पाठ्यपुस्तक — प्रश्न (Textbook Questions)", "count": 4, "marks_each": 4, "total": 16,
         "internal_choice": True, "notes": "Extract comprehension + Short/Long answer; 1 internal choice"},
        {"name": "E", "type": "निबंध / पत्र / अनुवाद (Writing / Translation)", "count": 2, "marks_each": 8, "total": 16,
         "internal_choice": True, "notes": "Essay in Sanskrit or formal letter; 1 internal choice"},
    ],
    "total_questions": 37,
    "notes": "Textbook: Ruchira (NCERT). Emphasis on Dhatu-roop and Shabd-roop.",
}

# ---------------------------------------------------------------------------
# ENGLISH NCERT LESSON LISTS — by class, AY 2025-26
# Used by generator.py instead of hardcoded lesson names.
# Update here when NCERT revises the readers; no code change needed.
# ---------------------------------------------------------------------------

ENGLISH_LESSONS = {
    # Class 11 — Hornbill (prose + poetry) + Snapshots (supplementary)
    "11": {
        "hornbill_prose": [
            "The Portrait of a Lady",
            "We're Not Afraid to Die... if We Can All Be Together",
            "Discovering Tut: The Saga Continues",
            "Landscape of the Soul",
            "The Ailing Planet: The Green Movement's Role",
            "The Browning Version",
            "The Adventure",
            "Silk Road",
        ],
        "hornbill_poetry": [
            "A Photograph",
            "The Laburnum Top",
            "The Voice of the Rain",
            "Childhood",
            "Father to Son",
        ],
        "snapshots": [
            "The Summer of the Beautiful White Horse",
            "The Address",
            "Ranga's Marriage",
            "Albert Einstein at School",
            "Mother's Day",
            "The Ghat of the Only World",
            "Birth",
            "The Tale of Melon City",
        ],
    },
    # Class 12 — Flamingo (prose + poetry) + Vistas (supplementary)
    "12": {
        "flamingo_prose": [
            "The Last Lesson",
            "Lost Spring",
            "Deep Water",
            "The Rattrap",
            "Indigo",
            "Poets and Pancakes",
            "The Interview",
            "Going Places",
        ],
        "flamingo_poetry": [
            "My Mother at Sixty-six",
            "Keeping Quiet",
            "A Thing of Beauty",
            "A Roadside Stand",
            "Aunt Jennifer's Tigers",
        ],
        "vistas": [
            "The Third Level",
            "The Tiger King",
            "Journey to the End of the Earth",
            "The Enemy",
            "Should Wizard Hit Mommy",
            "On the Face of It",
            "Evans Tries an O-level",
            "Memories of Childhood",
        ],
    },
    # Class 9 — Beehive (prose + poetry) + Moments (supplementary)
    "9": {
        "beehive_prose": [
            "The Fun They Had",
            "The Sound of Music",
            "The Little Girl",
            "A Truly Beautiful Mind",
            "The Snake and the Mirror",
            "My Childhood",
            "Packing",
            "Reach for the Top",
            "The Bond of Love",
            "Kathmandu",
            "If I Were You",
        ],
        "beehive_poetry": [
            "The Road Not Taken",
            "Wind",
            "Rain on the Roof",
            "The Lake Isle of Innisfree",
            "A Legend of the Northland",
            "No Men Are Foreign",
            "The Duck and the Kangaroo",
            "On Killing a Tree",
            "The Snake Trying",
            "A Slumber Did My Spirit Seal",
        ],
        "moments": [
            "The Lost Child",
            "The Adventures of Toto",
            "Iswaran the Storyteller",
            "In the Kingdom of Fools",
            "The Happy Prince",
            "Weathering the Storm in Ersama",
            "The Last Leaf",
            "A House Is Not a Home",
            "The Accidental Tourist",
            "The Beggar",
        ],
    },
    # Class 10 — First Flight (prose + poetry) + Footprints without Feet (supplementary)
    "10": {
        "first_flight_prose": [
            "A Letter to God",
            "Nelson Mandela: Long Walk to Freedom",
            "Two Stories about Flying",
            "From the Diary of Anne Frank",
            "Glimpses of India",
            "Mijbil the Otter",
            "Madam Rides the Bus",
            "The Sermon at Benares",
            "The Proposal",
        ],
        "first_flight_poetry": [
            "Dust of Snow",
            "Fire and Ice",
            "A Tiger in the Zoo",
            "How to Tell Wild Animals",
            "The Ball Poem",
            "Amanda",
            "Animals",
            "The Trees",
            "Fog",
            "The Tale of Custard the Dragon",
            "For Anne Gregory",
        ],
        "footprints": [
            "A Triumph of Surgery",
            "The Thief's Story",
            "The Midnight Visitor",
            "A Question of Trust",
            "Footprints without Feet",
            "The Making of a Scientist",
            "The Necklace",
            "The Hack Driver",
            "Bholi",
            "The Book That Saved the Earth",
        ],
    },
}

# Flat list of all lessons for a given class (used by generate_english_paper fallback)
def get_english_lessons(class_name: str) -> list:
    lessons = ENGLISH_LESSONS.get(str(class_name), {})
    flat = []
    for section_lessons in lessons.values():
        flat.extend(section_lessons)
    return flat


# ---------------------------------------------------------------------------
# UNIT-WISE MARKS WEIGHTS — for RAG context proportional allocation
# Source: CBSE SQP unit-wise marks distribution (AY 2025-26)
# Format: subject → {unit/chapter_name_fragment: marks_weight}
# Used by section_generator.get_section_context() to allocate n_results.
# ---------------------------------------------------------------------------

UNIT_MARKS_WEIGHTS = {
    "Physics": {
        # Class 12 unit-wise marks (total 70M theory)
        "Electric Charges": 16,
        "Current Electricity": 17,
        "Moving Charges": 18,
        "Magnetism": 18,
        "Electromagnetic Induction": 12,
        "Alternating Current": 12,
        "Electromagnetic Waves": 4,
        "Ray Optics": 18,
        "Wave Optics": 18,
        "Dual Nature": 11,
        "Atoms": 12,
        "Nuclei": 12,
        "Semiconductor": 10,
    },
    "Chemistry": {
        # Class 12 (total 70M theory)
        "Solutions": 7,
        "Electrochemistry": 9,
        "Chemical Kinetics": 7,
        "d and f Block": 7,
        "Coordination Compounds": 7,
        "Haloalkanes": 6,
        "Alcohols Phenols": 6,
        "Aldehydes Ketones": 8,
        "Amines": 6,
        "Biomolecules": 4,
        "Polymers": 3,
        "Chemistry in Everyday Life": 3,
        "Solid State": 4,
        "Surface Chemistry": 3,
    },
    "Mathematics": {
        # Class 12 (total 80M theory)
        "Relations and Functions": 8,
        "Inverse Trigonometric Functions": 8,
        "Matrices": 10,
        "Determinants": 10,
        "Continuity and Differentiability": 8,
        "Applications of Derivatives": 10,
        "Integrals": 8,
        "Applications of Integrals": 5,
        "Differential Equations": 5,
        "Vector Algebra": 6,
        "Three Dimensional Geometry": 6,
        "Linear Programming": 5,
        "Probability": 8,
    },
    "Biology": {
        # Class 12 (total 70M theory)
        "Reproduction": 16,
        "Genetics and Evolution": 18,
        "Biology and Human Welfare": 14,
        "Biotechnology": 12,
        "Ecology": 10,
    },
    "Science": {
        # Class 9-10 (total 80M theory; spread across Bio/Chem/Physics sections)
        "Chemical Reactions": 10,
        "Acids Bases Salts": 10,
        "Metals and Non-metals": 10,
        "Carbon Compounds": 10,
        "Life Processes": 10,
        "Control and Coordination": 8,
        "Reproduction": 8,
        "Heredity": 8,
        "Light": 8,
        "Electricity": 8,
        "Magnetic Effects": 8,
    },
    "Economics": {
        # Class 12 (total 80M theory)
        "National Income": 10,
        "Money and Banking": 6,
        "Determination of Income": 10,
        "Government Budget": 6,
        "Balance of Payments": 8,
        "Micro Economics Intro": 4,
        "Consumer Behaviour": 6,
        "Producer Behaviour": 6,
        "Forms of Market": 6,
        "Indian Economy": 18,
    },
    # --- Social Science sub-subjects (Class 9-10) ---
    # Each sub-subject contributes 20 marks to the 80-mark paper.
    "History": {
        # Class 10 — Contemporary India / India and the Contemporary World
        "Nationalism in Europe": 4,
        "Nationalism in India": 5,
        "The Making of a Global World": 4,
        "The Age of Industrialisation": 4,
        "Print Culture and the Modern World": 3,
    },
    "Geography": {
        # Class 10 — India — Resources and Development
        "Resources and Development": 5,
        "Forest and Wildlife Resources": 3,
        "Water Resources": 3,
        "Agriculture": 4,
        "Minerals and Energy Resources": 3,
        "Manufacturing Industries": 4,
        "Lifelines of National Economy": 3,
    },
    "Political Science": {
        # Class 10 — Democratic Politics II
        "Power Sharing": 4,
        "Federalism": 4,
        "Democracy and Diversity": 3,
        "Gender Religion and Caste": 3,
        "Popular Struggles and Movements": 3,
        "Political Parties": 4,
        "Outcomes of Democracy": 3,
        "Challenges to Democracy": 3,
    },
    "Economics Class 10": {
        # Class 10 — Understanding Economic Development
        "Development": 5,
        "Sectors of the Indian Economy": 5,
        "Money and Credit": 4,
        "Globalisation and the Indian Economy": 4,
        "Consumer Rights": 2,
    },
}


# Which CLASS each table above was compiled for (see the per-table comments). Every table is
# ONE class's unit-marks distribution, so scoring another class's chapters against it is
# meaningless — and not harmlessly so: Class 11's "Trigonometric Functions" matched Class 12's
# "Inverse Trigonometric Functions" under the old two-way substring test and inherited its
# weight of 8, while its genuine co-chapter "Linear Inequalities" (absent from the Class 12
# table) fell back to 1. The 8:1 ratio handed one chapter 19 of 21 questions AND ~89% of the
# retrieval budget on a two-chapter paper.
#
# A (subject, class) pair that is absent from this map means "no weightage data for that
# class" → uniform weighting, which is the correct default for a unit test: the teacher chose
# the chapters, so they get equal share unless CBSE says otherwise for THIS class.
UNIT_MARKS_WEIGHT_CLASSES = {
    "Physics": {"12"},
    "Chemistry": {"12"},
    "Mathematics": {"12"},
    "Biology": {"12"},
    "Economics": {"12"},
    "Science": {"9", "10"},
    "History": {"10"},
    "Geography": {"10"},
    "Political Science": {"10"},
    "Economics Class 10": {"10"},
}


# --- SANSKRIT AADHAAR (322) — Class 11 & 12 ---
PATTERNS["Sanskrit"] = {
    "code": "322", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "Apathit Anuvad / Gadyansh (Unseen Translation/Comprehension)",
         "total": 15,
         "sub": [
             {"q": "Q1", "type": "अपठित गद्यांश — Unseen Prose passage", "marks": 10,
              "types": "3 MCQ (1m) + 3 अर्थबोध SA (1m) + 2 vyakaran (2m)"},
             {"q": "Q2", "type": "अपठित पद्यांश — Unseen Poetry shloka", "marks": 5,
              "types": "2 MCQ + 2 SA + 1 bhavarth"},
         ]},
        {"name": "B", "type": "Vyakaran (Grammar)", "total": 25,
         "sub": [
             {"q": "Q3", "type": "Sandhi / Samaas (Split or merge)", "marks": 6},
             {"q": "Q4", "type": "Shabd-roop (Declension) — Noun / Pronoun forms", "marks": 6},
             {"q": "Q5", "type": "Dhatu-roop (Conjugation) — verb forms", "marks": 6},
             {"q": "Q6", "type": "Karak / Vibhakti (Case endings)", "marks": 4},
             {"q": "Q7", "type": "Anuvad — Hindi to Sanskrit translation (5 sentences)", "marks": 3},
         ]},
        {"name": "C", "type": "Pathyapustak — Textbook (Shashwati / Bhaswati)", "total": 30,
         "sub": [
             {"q": "Q8",  "type": "Gadyansh / Padyansh extract — comprehension sub-questions", "marks": 8, "choice": "1 of 2 extracts"},
             {"q": "Q9",  "type": "Shloka meaning (Sanskrit or Hindi)", "marks": 6, "attempt": "2 of 3"},
             {"q": "Q10", "type": "Short answer from prose chapters (~30 words)", "marks": 8, "attempt": "4 of 5", "marks_each": 2},
             {"q": "Q11", "type": "Long answer — character / theme / message (~80 words)", "marks": 8, "choice": "1 of 2"},
         ]},
        {"name": "D", "type": "Rachnatmak Lekhan (Creative Writing)", "total": 10,
         "sub": [
             {"q": "Q12", "type": "Patra Lekhan — Formal letter in Sanskrit (50-60 words)", "marks": 5, "choice": "1 of 2"},
             {"q": "Q13", "type": "Nibandh Lekhan — Sanskrit essay (50-60 words)", "marks": 5, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 13,
    "textbooks": {
        "11": "Shashwati — Part 1 (NCERT)",
        "12": "Bhaswati — Part 2 (NCERT)",
    },
    "internal_assessment_breakdown": {"listening_speaking": 10, "project_portfolio": 10},
}

# --- HINDI ELECTIVE (009) — Class 11 & 12 ---
PATTERNS["Hindi Elective"] = {
    "code": "009", "classes": ["11", "12"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "notes": "Deeper literary analysis than Hindi Core. Textbooks: Aaroh + Vitaan (11), Antara + Antaraal (12).",
    "sections": [
        {"name": "खंड-क — Apathit Bodh", "total": 20,
         "sub": [
             {"q": "Q1", "type": "Apathit Gadyansh (Prose, ~600 words)", "marks": 12,
              "sub_questions": "4 MCQ×1 + 2 SA×2 + 2 SA×2"},
             {"q": "Q2", "type": "Apathit Padyansh (Poetry, ~12 lines)", "marks": 8,
              "sub_questions": "4 MCQ×1 + 2 SA×2"},
         ]},
        {"name": "खंड-ख — Rachnatmak Lekhan", "total": 20,
         "sub": [
             {"q": "Q3", "type": "Nibandh (Essay, 300-350 words)", "marks": 8, "choice": "1 of 3"},
             {"q": "Q4", "type": "Vyavharik Lekhan — Patra / Avedan / Report", "marks": 6, "choice": "1 of 2"},
             {"q": "Q5", "type": "Sankhipt / Saar Lekhan (Summary/Précis, ~100 words)", "marks": 6},
         ]},
        {"name": "खंड-ग — Sahitya (Aaroh / Antara)", "total": 40,
         "sub": [
             {"q": "Q6",  "type": "Kavita / Gadh extract MCQ + SA", "marks": 10, "choice": "1 of 2 extracts"},
             {"q": "Q7",  "type": "Kavita vyakhya / bhavarth (~80 words)", "marks": 6, "attempt": "2 of 3", "marks_each": 3},
             {"q": "Q8",  "type": "Gadh chapter short answer (~60 words)", "marks": 8, "attempt": "2 of 3", "marks_each": 4},
             {"q": "Q9",  "type": "Vitaan / Antaraal long answer (~150 words)", "marks": 8, "attempt": "2 of 3", "marks_each": 4},
             {"q": "Q10", "type": "Essay-type critical question (~200 words)", "marks": 8, "choice": "1 of 2"},
         ]},
    ],
    "total_questions": 10,
    "textbooks": {
        "11": {"main": "Aaroh — Part 1", "supplementary": "Vitaan — Part 1"},
        "12": {"main": "Antara — Part 2", "supplementary": "Antaraal — Part 2"},
    },
    "internal_assessment_breakdown": {"listening_shravan": 10, "speaking_vachan": 10},
}

# ---------------------------------------------------------------------------
# HELPER: get pattern by subject name (case-insensitive)
# ---------------------------------------------------------------------------

def get_pattern(subject_name: str) -> dict | None:
    """Return the paper pattern dict for a subject, or None if not found."""
    for key, val in PATTERNS.items():
        if key.lower() == subject_name.strip().lower():
            return val
    return None


def get_exam_type(abbrev: str) -> dict | None:
    """Return exam type metadata by abbreviation (e.g. 'PT-1', 'HY')."""
    abbrev_lower = abbrev.strip().lower().replace("-", "").replace(" ", "")
    for key, val in EXAM_TYPES.items():
        if val.get("abbrev", "").lower().replace("-", "").replace(" ", "") == abbrev_lower:
            return val
    return EXAM_TYPES.get(abbrev_lower)


def list_subjects() -> list[str]:
    return list(PATTERNS.keys())
