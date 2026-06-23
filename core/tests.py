"""Regression tests for compound-paper marks handling.

These lock in two production bugs so they can't silently return:

  1. ExamPattern.get_total_marks / get_total_questions double-counted compound
     papers (section marks + subsection marks) — an 80-mark paper reported 160.

  2. The section generator crashed on compound sections because their
     marks_per_question is the literal string "varies" (real per-type marks live
     in `subsections`):  TypeError: '>=' not supported between 'str' and 'int'.

Run with:  python manage.py test core
"""

from django.test import TestCase

from core.models import ExamPattern
from core import section_generator as sg
from core import generator as sg_gen


def _sub(name, qtype, marks, q, mpq):
    return {"name": name, "question_types": [qtype], "marks": marks,
            "questions_count": q, "marks_per_question": mpq}


def _compound_sections():
    """A compound Science board paper: each section's `marks` equals the sum of
    its subsections, marks_per_question == "varies", question_types is a flat list
    of type-name strings. Mirrors the real DB pattern that triggered both bugs."""
    types = ["MCQ", "Assertion-Reason", "VSA", "SA", "Source-Based/CBQ", "LA"]
    bio = [_sub("MCQ", "MCQ", 7, 7, 1), _sub("AR", "Assertion-Reason", 2, 2, 1),
           _sub("VSA", "VSA", 6, 3, 2), _sub("SA", "SA", 6, 2, 3),
           _sub("CBQ", "Source-Based/CBQ", 4, 1, 4), _sub("LA", "LA", 5, 1, 5)]   # = 30 / 16q
    chem = [_sub("MCQ", "MCQ", 7, 7, 1), _sub("AR", "Assertion-Reason", 1, 1, 1),
            _sub("VSA", "VSA", 2, 1, 2), _sub("SA", "SA", 6, 2, 3),
            _sub("CBQ", "Source-Based/CBQ", 4, 1, 4), _sub("LA", "LA", 5, 1, 5)]   # = 25 / 13q
    return [
        {"name": "Biology", "marks": 30, "questions_count": 16,
         "marks_per_question": "varies", "question_types": types, "subsections": bio},
        {"name": "Chemistry", "marks": 25, "questions_count": 13,
         "marks_per_question": "varies", "question_types": types, "subsections": chem},
    ]


class TotalMarksTest(TestCase):
    def test_compound_total_not_doubled(self):
        p = ExamPattern(name="t", sections=_compound_sections())
        self.assertEqual(p.get_total_marks(), 55)        # 30 + 25, NOT 110
        self.assertEqual(p.get_total_questions(), 29)    # 16 + 13, NOT 58

    def test_save_stores_correct_totals(self):
        p = ExamPattern.objects.create(name="t2", sections=_compound_sections())
        self.assertEqual(p.total_marks, 55)
        self.assertEqual(p.total_questions, 29)

    def test_plain_section_unchanged(self):
        # A normal (non-compound) section with no subsections must still total normally.
        p = ExamPattern(name="t3", sections=[{"name": "A", "marks": 20, "questions_count": 10}])
        self.assertEqual(p.get_total_marks(), 20)
        self.assertEqual(p.get_total_questions(), 10)


class VariesWorkOrderTest(TestCase):
    def setUp(self):
        self.pattern = ExamPattern(name="wo", sections=_compound_sections())
        self.blueprint = {s["name"]: s for s in self.pattern.sections}

    def _build(self):
        return sg.build_work_orders(self.blueprint, self.pattern, {}, "Hard",
                                    "10", "Science", ["Life Processes"])

    def test_per_q_tokens_tolerates_non_numeric(self):
        self.assertIsInstance(sg._per_q_tokens("varies"), int)
        self.assertIsInstance(sg._per_q_tokens("3"), int)
        self.assertIsInstance(sg._per_q_tokens(None), int)

    def test_build_work_orders_numeric_and_mixed(self):
        wos = self._build()
        self.assertEqual(len(wos), 2)
        for wo in wos:
            self.assertIsInstance(wo.marks_per_question, (int, float))   # never "varies"
            self.assertTrue(wo.mixed_marks)
            self.assertTrue(wo.question_types and all(isinstance(qt, dict) for qt in wo.question_types))
            self.assertTrue(all("marks_each" in qt for qt in wo.question_types))

    def test_estimate_token_budget_no_crash(self):
        for wo in self._build():
            budget = sg.estimate_token_budget(wo)        # this is the call that used to crash
            self.assertIsInstance(budget, int)
            self.assertGreaterEqual(budget, 3000)
            self.assertLessEqual(budget, 8192)

    def test_prompt_emits_per_type_marks(self):
        prompt = sg.build_section_prompt(self._build()[0])
        self.assertIn("VARIES BY TYPE", prompt)
        self.assertIn("assertion_reason", prompt)


class CompoundChapterRoutingTest(TestCase):
    """A Biology section of a Science paper must only see Biology chapters — otherwise
    it generates Chemistry/Physics questions (the cross-subject leak bug)."""

    CHAPTERS = ["Acids, Bases and Salts", "Carbon and its Compounds",
                "Chemical Reactions and Equations", "Control and Coordination",
                "Electricity", "Heredity", "How do Organisms Reproduce", "Life Processes",
                "Light – Reflection and Refraction", "Magnetic Effects of Electric Current",
                "Metals and Non-metals", "Our Environment",
                "The Human Eye and the Colourful World"]

    def test_section_subject_inferred_from_name(self):
        # Pattern omits section_subject — it must be inferred from the section name.
        self.assertEqual(sg._resolve_section_subject("Science", "Biology", ""), "Biology")
        self.assertEqual(sg._resolve_section_subject("Science", "Chemistry", ""), "Chemistry")
        # Explicit value wins; ordinary papers stay unscoped.
        self.assertEqual(sg._resolve_section_subject("Science", "Biology", "Physics"), "Physics")
        self.assertEqual(sg._resolve_section_subject("Physics", "Section A", ""), "")

    def test_biology_section_excludes_chem_and_physics(self):
        bio = sg._chapters_for_subject("Biology", "Science", self.CHAPTERS)
        self.assertIn("Life Processes", bio)
        self.assertIn("Heredity", bio)
        for leaked in ("Acids, Bases and Salts", "Metals and Non-metals",
                       "Electricity", "Magnetic Effects of Electric Current"):
            self.assertNotIn(leaked, bio)

    def test_each_subject_partitions_chapters(self):
        bio = sg._chapters_for_subject("Biology", "Science", self.CHAPTERS)
        chem = sg._chapters_for_subject("Chemistry", "Science", self.CHAPTERS)
        phys = sg._chapters_for_subject("Physics", "Science", self.CHAPTERS)
        self.assertEqual(len(bio) + len(chem) + len(phys), len(self.CHAPTERS))
        self.assertEqual(set(bio) | set(chem) | set(phys), set(self.CHAPTERS))

    def test_single_subject_paper_keeps_all_chapters(self):
        # A real Biology paper (parent == section) must not be scoped down.
        self.assertEqual(sg._chapters_for_subject("Biology", "Biology", self.CHAPTERS),
                         list(self.CHAPTERS))


class RenderGroupingTest(TestCase):
    """Render layer must group questions by type and restore per-type marks, so an SA
    never lands in the MCQ block and a 1-mark MCQ never shows the section average."""

    SEC_INFO = {
        "name": "Biology", "marks": 30,
        "subsections": [
            {"name": "MCQ", "question_types": ["MCQ"], "marks": 7, "questions_count": 7, "marks_per_question": 1},
            {"name": "Assertion-Reason", "question_types": ["Assertion-Reason"], "marks": 2, "questions_count": 2, "marks_per_question": 1},
            {"name": "VSA", "question_types": ["VSA"], "marks": 6, "questions_count": 3, "marks_per_question": 2},
            {"name": "SA", "question_types": ["SA"], "marks": 6, "questions_count": 2, "marks_per_question": 3},
            {"name": "CBQ", "question_types": ["Source-Based/CBQ"], "marks": 4, "questions_count": 1, "marks_per_question": 4},
            {"name": "LA", "question_types": ["LA"], "marks": 5, "questions_count": 1, "marks_per_question": 5},
        ],
    }

    def _questions(self):
        # Deliberately jumbled order + wrong average marks (mimics fallback output).
        return [
            {"qnum": 1, "type": "MCQ", "subtype": "assertion_reason", "marks": 1.9},
            {"qnum": 2, "type": "SA", "subtype": "standard", "marks": 1.9},
            {"qnum": 3, "type": "MCQ", "subtype": "standard", "marks": 1.9},
            {"qnum": 4, "type": "LA", "subtype": "standard", "marks": 1.9},
            {"qnum": 5, "type": "VSA", "subtype": "standard", "marks": 1.9},
            {"qnum": 6, "type": "CBQ", "subtype": "source_based", "marks": 1.9},
        ]

    def test_marks_map_from_subsections(self):
        m = sg_gen._section_type_marks(self.SEC_INFO)
        self.assertEqual(m, {"mcq": 1.0, "ar": 1.0, "vsa": 2.0, "sa": 3.0, "cbq": 4.0, "la": 5.0})

    def test_category_assignment(self):
        self.assertEqual(sg_gen._question_category({"type": "MCQ", "subtype": "assertion_reason"}), "ar")
        self.assertEqual(sg_gen._question_category({"type": "MCQ", "subtype": "standard"}), "mcq")
        self.assertEqual(sg_gen._question_category({"type": "CBQ", "subtype": "source_based"}), "cbq")
        self.assertEqual(sg_gen._question_category({"type": "SA"}), "sa")
        self.assertEqual(sg_gen._question_category({"type": "LA"}), "la")

    def test_regroup_orders_and_fixes_marks(self):
        groups = sg_gen._regroup_section(self._questions(), self.SEC_INFO)
        labels = [lbl for lbl, _ in groups if lbl]
        # Canonical order, MCQ group first, LA last.
        self.assertTrue(labels[0].startswith("I.") and "Multiple Choice" in labels[0])
        self.assertIn("Long Answer", labels[-1])
        # Per-type marks restored — no 1.9 anywhere.
        flat = [q for _, qs in groups for q in qs]
        by_cat = {sg_gen._question_category(q): q["marks"] for q in flat}
        self.assertEqual(by_cat["mcq"], 1)
        self.assertEqual(by_cat["sa"], 3)
        self.assertEqual(by_cat["cbq"], 4)
        self.assertEqual(by_cat["la"], 5)
        self.assertFalse(any(q["marks"] == 1.9 for q in flat))

    def test_uniform_section_gets_no_group_labels(self):
        # All-MCQ section → single group, no roman-numeral headers, no behaviour change.
        qs = [{"type": "MCQ", "subtype": "standard", "marks": 1} for _ in range(5)]
        groups = sg_gen._regroup_section(qs, {"name": "A", "subsections": []})
        self.assertEqual([lbl for lbl, _ in groups if lbl], [])


class MissingCountDerivationTest(TestCase):
    """AI-generated patterns sometimes leave questions_count / marks_per_question null with
    only the section marks set. The work-order builder must derive a non-zero count from
    marks + question type, otherwise the section generates nothing and comes out empty."""

    def _pattern(self):
        # Mirrors the real broken pattern 342: only Section A had counts.
        return ExamPattern(name="pt", subject="Mathematics", class_name="6", sections=[
            {"name": "Section A — Objective Type", "marks": 20, "questions_count": 20,
             "marks_per_question": 1, "question_types": ["MCQ", "True/False", "Fill in the Blanks"]},
            {"name": "Section B — Very Short Answer (VSA)", "marks": 12, "questions_count": None,
             "marks_per_question": None, "question_types": ["Very Short Answer"]},
            {"name": "Section C — Short Answer (SA)", "marks": 18, "questions_count": None,
             "marks_per_question": None, "question_types": ["Short Answer"]},
            {"name": "Section D — Long Answer (LA)", "marks": 30, "questions_count": None,
             "marks_per_question": None, "question_types": ["Long Answer"]},
        ])

    def test_typical_marks(self):
        self.assertEqual(sg._typical_marks_for_types(["Very Short Answer"]), 2.0)
        self.assertEqual(sg._typical_marks_for_types(["Short Answer"]), 3.0)
        self.assertEqual(sg._typical_marks_for_types(["Long Answer"]), 5.0)
        self.assertEqual(sg._typical_marks_for_types(["MCQ"]), 1.0)

    def test_work_orders_derive_nonzero_counts(self):
        p = self._pattern()
        bp = {s["name"]: s for s in p.sections}
        wos = sg.build_work_orders(bp, p, {}, "Medium", "6", "Mathematics", ["Patterns"])
        counts = {wo.section_name.split("—")[1].strip()[:3]: wo.questions_count for wo in wos}
        # No section may ask for 0 questions; derived from marks ÷ per-type marks.
        for wo in wos:
            self.assertGreater(wo.questions_count, 0, f"{wo.section_name} got 0 questions")
        self.assertEqual(counts["Obj"], 20)   # A unchanged
        self.assertEqual(counts["Ver"], 6)     # B: 12 / 2
        self.assertEqual(counts["Sho"], 6)     # C: 18 / 3
        self.assertEqual(counts["Lon"], 6)     # D: 30 / 5
