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
PATTERNS["Science"] = {
    "code": "086", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ (Q1-16) + Assertion-Reason (Q17-20)", "count": 20, "marks_each": 1, "total": 20, "internal_choice": False},
        {"name": "B", "type": "Very Short Answer (VSA)", "count": 6, "marks_each": 2, "total": 12,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "C", "type": "Short Answer (SA)", "count": 7, "marks_each": 3, "total": 21,
         "internal_choice": True, "choices": "3 internal choices"},
        {"name": "D", "type": "Long Answer (LA)", "count": 3, "marks_each": 5, "total": 15,
         "internal_choice": True, "choices": "Internal choices in all 3"},
        {"name": "E", "type": "Case-Based / Data-Based Questions", "count": 3, "marks_each": 4, "total": 12,
         "internal_choice": True, "notes": "Q37-39; each has 4 sub-questions (1+1+1+1 or 2+2)"},
    ],
    "total_questions": 39,
    "notes": "Covers Biology, Chemistry, Physics integrated. 2025-26 onwards split into explicit subject sections.",
}

# --- SOCIAL SCIENCE (Class 9-10) ---
PATTERNS["Social Science"] = {
    "code": "087", "classes": ["9", "10"],
    "theory_marks": 80, "internal_assessment": 20, "total": 100,
    "duration_minutes": 180,
    "sections": [
        {"name": "A", "type": "MCQ incl. Assertion-Reason", "count": 20, "marks_each": 1, "total": 20, "internal_choice": False},
        {"name": "B", "type": "Short Answer (SA, 60-80 words)", "count": 5, "marks_each": 3, "total": 15,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "C", "type": "Long Answer (LA, 100-120 words)", "count": 3, "marks_each": 5, "total": 15,
         "internal_choice": True, "choices": "2 internal choices"},
        {"name": "D", "type": "Source-Based / Case-Based Questions", "count": 3, "marks_each": 4, "total": 12,
         "internal_choice": False, "notes": "Passage + image/cartoon + data-based"},
        {"name": "E", "type": "Map Work", "count": 2, "marks_each": 5, "total": 10,
         "internal_choice": False,
         "notes": "Q33 locate/label on India map (5m), Q34 identify marked features (5m). Only one attempted (attempt any 1 of 2 map questions = 5+5 but one map is History, one Geography)"},
    ],
    "total_questions": 33,
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
        {"name": "खंड-क — Apathit Bodh", "total": 14},
        {"name": "खंड-ख — Vyakaran", "total": 16},
        {"name": "खंड-ग — Sahitya (Sparsh + Sanchayan)", "total": 34},
        {"name": "खंड-घ — Lekhan", "total": 16},
    ],
    "total_questions": 14,
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
