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

from django.contrib.auth.models import User

from core.models import ExamPattern, School, ExamBlueprint
from core import section_generator as sg
from core import generator as sg_gen
from core import paper_edit as pe
from api.views import _scoped_blueprints


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

    def test_render_stamps_display_qnums_on_shared_dicts(self):
        # _render_paper_from_stored_data persists paper_data after rendering BECAUSE the
        # renderer writes each question's PRINTED number back into the shared question dicts
        # (blueprint section order + type regrouping), regardless of paper_data dict order or
        # stale stored qnums. paper_edit.renumber() numbers in storage order instead, so
        # without this write-back+save the ai_edit planner targets numbers the teacher
        # doesn't see. This test pins the write-back contract the fix relies on.
        blueprint = {
            "Section A": {"title": "Objective", "marks": 2},
            "Section B": {"title": "Short Answer", "marks": 3},
        }
        a_mcq = {"qnum": 99, "type": "MCQ", "subtype": "standard", "marks": 1, "text": "pick",
                 "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a"}
        a_sa = {"qnum": 98, "type": "SA", "subtype": "standard", "marks": 1, "text": "why"}
        b_sa = {"qnum": 97, "type": "SA", "subtype": "standard", "marks": 3, "text": "explain"}
        # dict order (B first) deliberately differs from blueprint order (A first); Section A
        # stores its SA before its MCQ while the print regroups MCQ first.
        data = {
            "Section B": {"questions": [b_sa]},
            "Section A": {"questions": [a_sa, a_mcq]},
        }
        sg_gen.render_section_questions([], data, blueprint)
        self.assertEqual({a_mcq["qnum"], a_sa["qnum"]}, {1, 2})   # Section A printed first
        self.assertLess(a_mcq["qnum"], a_sa["qnum"])              # regrouped: MCQ before SA
        self.assertEqual(b_sa["qnum"], 3)                         # B last despite dict order


class SectionHeaderLabelTest(TestCase):
    """AI/teacher-authored patterns often name a section 'Section A — Objective Type'
    (the label already spelled out) rather than a bare letter. The renderer used to
    always prefix 'SECTION – ', producing a doubled word: 'SECTION – Section A —
    Objective Type'. Reported production bug on a Social Science paper."""

    def _headers(self, blueprint, data):
        all_q = []
        sg_gen.render_section_questions(all_q, data, blueprint)
        return [text for typ, text in all_q if typ == "header"]

    def test_no_duplicate_section_word_when_name_already_labelled(self):
        blueprint = {"Section A — Objective Type": {"title": "", "marks": 10}}
        data = {"Section A — Objective Type": {"questions": []}}
        self.assertEqual(self._headers(blueprint, data),
                         ["Section A — Objective Type (10 MARKS)"])

    def test_bare_letter_keeps_section_prefix(self):
        blueprint = {"A": {"title": "", "marks": 5}}
        data = {"A": {"questions": []}}
        self.assertEqual(self._headers(blueprint, data), ["SECTION – A (5 MARKS)"])

    def test_title_suffix_still_appended_for_bare_letter(self):
        blueprint = {"A": {"title": "Objective Type", "marks": 5}}
        data = {"A": {"questions": []}}
        self.assertEqual(self._headers(blueprint, data),
                         ["SECTION – A: OBJECTIVE TYPE (5 MARKS)"])

    def test_compound_sub_subject_no_duplicate_when_already_labelled(self):
        blueprint = {"Section A": {"title": "", "marks": 26, "section_subject": "Biology"}}
        data = {"Section A": {"questions": []}}
        self.assertEqual(self._headers(blueprint, data), ["Section A — BIOLOGY (26 MARKS)"])

    def test_compound_sub_subject_bare_letter_unchanged(self):
        blueprint = {"A": {"title": "", "marks": 26, "section_subject": "Biology"}}
        data = {"A": {"questions": []}}
        self.assertEqual(self._headers(blueprint, data), ["SECTION A — BIOLOGY (26 MARKS)"])


class CountBasedValidationTest(TestCase):
    """Section validation must check the right NUMBER of each type (renderer handles order),
    not that each type sits at an exact position."""

    def _wo(self):
        pattern = ExamPattern(name="cv", subject="Science", class_name="10", sections=[{
            "name": "Biology", "marks": 8, "questions_count": 5, "marks_per_question": "varies",
            "question_types": ["MCQ", "Assertion-Reason", "VSA", "SA"],
            "subsections": [
                {"name": "MCQ", "question_types": ["MCQ"], "marks": 2, "questions_count": 2, "marks_per_question": 1},
                {"name": "AR", "question_types": ["Assertion-Reason"], "marks": 1, "questions_count": 1, "marks_per_question": 1},
                {"name": "VSA", "question_types": ["VSA"], "marks": 2, "questions_count": 1, "marks_per_question": 2},
                {"name": "SA", "question_types": ["SA"], "marks": 3, "questions_count": 1, "marks_per_question": 3},
            ],
        }])
        bp = {s["name"]: s for s in pattern.sections}
        return sg.build_work_orders(bp, pattern, {}, "Medium", "10", "Science", ["Life"])[0]

    def _mcq(self, m=1, ar=False):
        q = {"type": "MCQ", "subtype": "assertion_reason" if ar else "standard", "marks": m,
             "text": "Assertion (A): x\nReason (R): y" if ar else "q", "answer": "a",
             "options": {"a": "1", "b": "2", "c": "3", "d": "4"}}
        return q

    def test_right_counts_wrong_order_passes_type_check(self):
        # Jumbled order, but exactly 2 MCQ + 1 AR + 1 VSA + 1 SA.
        qs = [
            {"type": "SA", "marks": 3, "text": "q", "answer_explanation": "a"},
            {"type": "VSA", "marks": 2, "text": "q", "answer_explanation": "a"},
            self._mcq(1),
            self._mcq(1, ar=True),
            self._mcq(1),
        ]
        errors = sg.validate_section_output({"questions": qs}, self._wo())
        self.assertFalse(any("distribution wrong" in e for e in errors), errors)
        self.assertFalse(any("type mismatch" in e for e in errors), errors)

    def test_wrong_counts_flagged(self):
        # 3 MCQ, 0 AR, 1 VSA, 1 SA — AR missing, MCQ over.
        qs = [self._mcq(1), self._mcq(1), self._mcq(1),
              {"type": "VSA", "marks": 2, "text": "q", "answer_explanation": "a"},
              {"type": "SA", "marks": 3, "text": "q", "answer_explanation": "a"}]
        errors = sg.validate_section_output({"questions": qs}, self._wo())
        dist = [e for e in errors if "distribution wrong" in e]
        self.assertTrue(dist, errors)
        self.assertIn("AR", dist[0])


class SectionTypeEnforcementTest(TestCase):
    """Uniform sections must reject foreign question types and the prompt must forbid them."""

    def _wo(self, types, count=5, mpq=2.0):
        from core import section_generator as sg
        return sg.SectionWorkOrder(
            section_name="Section B", section_id="B", title="Short Answer I", marks=int(count * mpq),
            questions_count=count, marks_per_question=mpq, question_types=types, instructions=[],
            constraints={}, context_text="ctx", difficulty="medium", subject="Chemistry",
            class_name="12", chapters=["Equilibrium"])

    def _sa_q(self, n):
        return {"qnum": n, "type": "SA", "subtype": "standard", "text": f"Explain concept {n}.",
                "marks": 2, "answer_explanation": "…", "competency_type": "constructed"}

    def _mcq_q(self, n):
        return {"qnum": n, "type": "MCQ", "subtype": "standard", "text": f"Pick {n}",
                "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a",
                "marks": 2, "answer_explanation": "…", "competency_type": "recall"}

    def test_mcq_in_short_answer_section_is_rejected(self):
        from core import section_generator as sg
        wo = self._wo(["Short Answer I"])
        data = {"questions": [self._sa_q(1), self._sa_q(2), self._sa_q(3), self._mcq_q(4), self._mcq_q(5)]}
        errs = sg.validate_section_output(data, wo)
        self.assertTrue(any("Wrong question type" in e and "MCQ" in e for e in errs), errs)

    def test_all_short_answer_section_passes_type_check(self):
        from core import section_generator as sg
        wo = self._wo(["Short Answer I"])
        data = {"questions": [self._sa_q(i) for i in range(1, 6)]}
        errs = sg.validate_section_output(data, wo)
        self.assertFalse(any("Wrong question type" in e for e in errs), errs)

    def test_mcq_and_ar_both_allowed_in_objective_section(self):
        from core import section_generator as sg
        wo = self._wo(["MCQ", "Assertion-Reason"], count=2, mpq=1.0)
        ar = {"qnum": 2, "type": "MCQ", "subtype": "assertion_reason",
              "text": "Assertion (A): x.\nReason (R): y.",
              "options": {"a": "Both A and R are true and R is the correct explanation of A",
                          "b": "Both true, R not correct explanation", "c": "A true R false", "d": "A false R true"},
              "answer": "a", "marks": 1, "answer_explanation": "…", "competency_type": "application"}
        mcq = self._mcq_q(1); mcq["marks"] = 1
        errs = sg.validate_section_output({"questions": [mcq, ar]}, wo)
        self.assertFalse(any("Wrong question type" in e for e in errs), errs)

    def test_prompt_forbids_other_types_for_short_answer(self):
        from core import section_generator as sg
        wo = self._wo(["Short Answer I"])
        sg.plan_chapter_allocation([wo])
        p = sg.build_section_prompt(wo)
        self.assertIn("QUESTION TYPE — MANDATORY", p)
        self.assertIn("WRITTEN-ANSWER", p)
        self.assertIn('"type":"SA"', p)

    def test_mcq_token_budget_fits_sixteen(self):
        from core import section_generator as sg
        wo = self._wo(["MCQ", "Assertion-Reason"], count=16, mpq=1.0)
        # 16 MCQs must budget well above the old 3380 truncation point.
        self.assertGreater(sg.estimate_token_budget(wo), 4000)

    def test_enforce_pass_strips_mcq_from_sa_section(self):
        from core import section_generator as sg
        wo = self._wo(["Short Answer I"])
        paper_data = {"Section B": {"section_name": "Section B", "questions": [
            self._sa_q(1), self._mcq_q(2), self._sa_q(3)]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        kinds = [q["type"] for q in out["Section B"]["questions"]]
        self.assertEqual(kinds, ["SA", "SA"])                         # MCQ removed
        self.assertEqual(len(out["Section B"]["_dropped_wrong_type"]), 1)

    def test_enforce_pass_keeps_assertion_reason_in_objective_section(self):
        from core import section_generator as sg
        wo = self._wo(["MCQ", "Assertion-Reason"], count=2, mpq=1.0)
        ar = {"qnum": 2, "type": "MCQ", "subtype": "assertion_reason", "text": "A…R…",
              "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a", "marks": 1}
        paper_data = {"Section B": {"section_name": "Section B", "questions": [self._mcq_q(1), ar]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 2)        # nothing dropped
        self.assertNotIn("_dropped_wrong_type", out["Section B"])

    def test_enforce_pass_keeps_cbq_with_subtype(self):
        from core import section_generator as sg
        wo = self._wo(["Case-Based Questions"], count=2, mpq=4.0)
        cbq = {"qnum": 1, "type": "CBQ", "subtype": "image_based", "text": "Observe…",
               "marks": 4, "sub_questions": [{"text": "a?", "marks": 2}, {"text": "b?", "marks": 2}]}
        paper_data = {"Section B": {"section_name": "Section B", "questions": [cbq]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 1)        # CBQ kept despite subtype

    def _map_q(self, n, marks=1):
        # Map questions are emitted as type "SA" + subtype "map_based" per the schema.
        return {"qnum": n, "type": "SA", "subtype": "map_based",
                "text": f"On the given outline map of India, locate and label: (a) place {n} (b) place {n + 1}",
                "marks": marks, "map_note": "[Attach outline map of India — examiner to supply]",
                "chapter_tag": "Ch", "competency_type": "application"}

    def test_enforce_pass_keeps_map_based_in_pure_map_section(self):
        # SS Section F ("Map location" / "Diagram-based"): every valid map question was
        # stripped as a foreign SA, shipping the section 0/3.
        from core import section_generator as sg
        wo = self._wo(["Map location", "Diagram-based"], count=3, mpq=1.0)
        paper_data = {"Section B": {"section_name": "Section B",
                                    "questions": [self._map_q(1), self._map_q(2), self._map_q(3)]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 3)        # nothing dropped
        self.assertNotIn("_dropped_wrong_type", out["Section B"])

    def test_enforce_pass_keeps_map_and_la_in_mixed_section(self):
        # SS Section D ("Long Answer" / "Map Work"): the map half was dropped, shipping 1/2.
        from core import section_generator as sg
        wo = self._wo(["Long Answer", "Map Work"], count=2, mpq=5.0)
        la = {"qnum": 1, "type": "LA", "subtype": "standard", "text": "Explain in detail…",
              "marks": 5, "or_alternative": {"text": "Or explain…"}}
        paper_data = {"Section B": {"section_name": "Section B",
                                    "questions": [la, self._map_q(2, marks=5)]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 2)        # LA and map both kept
        self.assertNotIn("_dropped_wrong_type", out["Section B"])

    def test_enforce_pass_keeps_map_by_map_note_when_subtype_missing(self):
        from core import section_generator as sg
        wo = self._wo(["Map Work"], count=1, mpq=2.0)
        q = self._map_q(1, marks=2)
        q["subtype"] = "standard"                                      # model forgot the subtype
        paper_data = {"Section B": {"section_name": "Section B", "questions": [q]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 1)        # map_note is enough
        self.assertNotIn("_dropped_wrong_type", out["Section B"])

    def test_enforce_pass_still_strips_mcq_from_map_section(self):
        from core import section_generator as sg
        wo = self._wo(["Map location"], count=2, mpq=1.0)
        paper_data = {"Section B": {"section_name": "Section B",
                                    "questions": [self._map_q(1), self._mcq_q(2)]}}
        out = sg.enforce_section_question_types(paper_data, [wo])
        self.assertEqual(len(out["Section B"]["questions"]), 1)        # MCQ still removed
        self.assertEqual(len(out["Section B"]["_dropped_wrong_type"]), 1)

    def test_top_up_applies_to_map_section(self):
        # A short map section used to be refused by the top-up (no recovery path at all).
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(["Map location"], count=3, mpq=1.0)
        wo.is_map_work = True
        sec = {"section_name": "Section B", "questions": [self._map_q(1), self._map_q(3)]}
        reply = ('{"questions": [{"qnum": 3, "type": "SA", "subtype": "map_based", '
                 '"text": "On the given outline map of India, locate and label: (a) Mumbai (b) Goa", '
                 '"marks": 1, "map_note": "[Attach outline map of India — examiner to supply]", '
                 '"chapter_tag": "Ch", "competency_type": "application"}]}')
        with mock.patch.object(sg.mantle_client, "converse", return_value=(reply, 10, 20)):
            in_tok, out_tok = sg._top_up_short_section(sec, wo)
        self.assertEqual(len(sec["questions"]), 3)                     # topped up to count
        self.assertEqual(sec.get("_topped_up"), 1)
        self.assertGreater(in_tok + out_tok, 0)

    def test_top_up_still_refuses_cbq_section(self):
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(["Case-Based Questions"], count=2, mpq=4.0)
        sec = {"section_name": "Section B", "questions": []}
        with mock.patch.object(sg.mantle_client, "converse") as conv:
            in_tok, out_tok = sg._top_up_short_section(sec, wo)
        self.assertEqual((in_tok, out_tok), (0, 0))
        conv.assert_not_called()


class MarksReconcileAndTopUpLoopTest(TestCase):
    """Uniform sections must end up at the right marks AND the right count — the two shapes
    behind the recurring 'Marks check' audit warnings (9/10 marks; 18/20 questions)."""

    def _wo(self, mixed=False, mpq=2.0, count=5, types=None, name="Section B"):
        from core import section_generator as sg
        return sg.SectionWorkOrder(
            section_name=name, section_id="B", title="VSA", marks=int(count * mpq),
            questions_count=count, marks_per_question=mpq, question_types=types or ["VSA"],
            instructions=[], constraints={}, context_text="ctx", difficulty="medium",
            subject="Science", class_name="10", chapters=["Light"], mixed_marks=mixed)

    def test_reconcile_clamps_drifted_uniform_marks(self):
        from core import section_generator as sg
        wo = self._wo(mpq=2.0, count=5)
        qs = [{"type": "VSA", "text": f"q{i}", "marks": 2} for i in range(4)]
        qs.append({"type": "VSA", "text": "drift", "marks": 1})          # one drifted to 1m
        pd = {"Section B": {"section_name": "Section B", "questions": qs}}
        sg.reconcile_uniform_marks(pd, [wo])
        self.assertEqual(sum(q["marks"] for q in pd["Section B"]["questions"]), 10)

    def test_reconcile_fixes_non_numeric_marks(self):
        from core import section_generator as sg
        wo = self._wo(mpq=3.0, count=2, types=["SA"])
        pd = {"Section B": {"section_name": "Section B", "questions": [
            {"type": "SA", "text": "a", "marks": 3},
            {"type": "SA", "text": "b", "marks": "varies"}]}}
        sg.reconcile_uniform_marks(pd, [wo])
        self.assertEqual([q["marks"] for q in pd["Section B"]["questions"]], [3.0, 3.0])

    def test_reconcile_leaves_mixed_marks_untouched(self):
        from core import section_generator as sg
        wo = self._wo(mixed=True, mpq=2.0, count=3)
        qs = [{"type": "MCQ", "text": "a", "marks": 1},
              {"type": "SA", "text": "b", "marks": 3},
              {"type": "VSA", "text": "c", "marks": 2}]
        pd = {"Section B": {"section_name": "Section B", "questions": qs}}
        sg.reconcile_uniform_marks(pd, [wo])
        self.assertEqual([q["marks"] for q in pd["Section B"]["questions"]], [1, 3, 2])

    def test_reconcile_skips_cbq_subquestions(self):
        from core import section_generator as sg
        wo = self._wo(mpq=4.0, count=1, types=["CBQ"])
        pd = {"Section B": {"section_name": "Section B", "questions": [
            {"type": "CBQ", "text": "x", "marks": 4,
             "sub_questions": [{"text": "a", "marks": 2}, {"text": "b", "marks": 2}]}]}}
        sg.reconcile_uniform_marks(pd, [wo])
        self.assertEqual(pd["Section B"]["questions"][0]["marks"], 4)

    def test_distributes_marks_when_count_times_mpq_below_total(self):
        # The exact log case: Section B declared 10m but 3 SA × 3m = 9. Distribute to 4,3,3.
        from core import section_generator as sg
        wo = self._wo(mpq=3.0, count=3, types=["Short Answer I (SA-I)"])
        wo.marks = 10                                          # pattern says 10m, 3×3 can't reach it
        qs = [{"type": "SA", "text": f"q{i}", "marks": 3} for i in range(3)]
        pd = {"Section B": {"section_name": "Section B", "questions": qs}}
        sg.reconcile_uniform_marks(pd, [wo])
        marks = sorted(q["marks"] for q in pd["Section B"]["questions"])
        self.assertEqual(sum(marks), 10)                       # section now totals exactly 10
        self.assertEqual(marks, [3, 3, 4])

    def test_objective_section_not_inflated_when_short(self):
        # A short MCQ section must NOT have its marks inflated to hide the count shortfall.
        from core import section_generator as sg
        wo = self._wo(mpq=1.0, count=20, types=["MCQ", "Assertion-Reason"])
        wo.marks = 20
        qs = [{"type": "MCQ", "text": f"q{i}", "marks": 1} for i in range(18)]  # 18/20 short
        pd = {"Section A": {"section_name": "Section A", "questions": qs}}
        # work order name must match the dict key
        wo.section_name = "Section A"
        sg.reconcile_uniform_marks(pd, [wo])
        self.assertTrue(all(q["marks"] == 1 for q in pd["Section A"]["questions"]))
        self.assertEqual(sum(q["marks"] for q in pd["Section A"]["questions"]), 18)  # stays 18, not 20

    def test_fill_loop_recovers_full_count_over_rounds(self):
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(mpq=1.0, count=20, types=["MCQ"], name="Section A")
        sec = {"section_name": "Section A",
               "questions": [{"type": "MCQ", "text": f"q{i}", "marks": 1} for i in range(18)]}
        seq = {"n": 0}

        def fake_topup(section_data, w):
            # Simulate the model recovering only ONE of the missing questions per call —
            # the exact behaviour that left single-shot top-up stuck at 19/20.
            cur = len(section_data["questions"])
            if cur < w.questions_count:
                section_data["questions"].append(
                    {"type": "MCQ", "text": f"new{seq['n']}", "marks": 1})
                seq["n"] += 1
                return 1, 1
            return 0, 0

        with mock.patch.object(sg, "_top_up_short_section", side_effect=fake_topup):
            sg._fill_short_section(sec, wo, max_rounds=5)
        self.assertEqual(len(sec["questions"]), 20)        # filled, not stuck at 19
        self.assertEqual(sec.get("_topped_up"), 2)         # cumulative across rounds

    def test_fill_loop_stops_when_a_round_adds_nothing(self):
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(mpq=1.0, count=20, types=["MCQ"], name="Section A")
        sec = {"section_name": "Section A",
               "questions": [{"type": "MCQ", "text": f"q{i}", "marks": 1} for i in range(18)]}
        calls = {"n": 0}

        def stuck_topup(section_data, w):
            calls["n"] += 1                                 # spends a call but adds nothing
            return 1, 1

        with mock.patch.object(sg, "_top_up_short_section", side_effect=stuck_topup):
            sg._fill_short_section(sec, wo, max_rounds=5)
        self.assertEqual(calls["n"], 1)                     # bails after the first no-progress round
        self.assertEqual(len(sec["questions"]), 18)


class V5L2DuplicateReplacementTypeTest(TestCase):
    """A duplicate-replacement must keep the original question's TYPE. A type-drifted
    replacement (an SA where the original was an MCQ) is stripped by the type-enforcer and
    drops the section below count — the proven cause of 'Section A: 18/20 questions'."""

    def _wo(self, types, count=20, mpq=1.0):
        from core import section_generator as sg
        return sg.SectionWorkOrder(
            section_name="Section A — Objective Type", section_id="A", title="Objective",
            marks=int(count * mpq), questions_count=count, marks_per_question=mpq,
            question_types=types, instructions=[], constraints={}, context_text="ctx",
            difficulty="medium", subject="Computer Science", class_name="11",
            chapters=["Encoding Schemes and Number System"])

    def _mcq(self, n, text):
        return {"qnum": n, "type": "MCQ", "subtype": "standard", "text": text,
                "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a",
                "marks": 1, "answer_explanation": "because a", "chapter_tag": "X",
                "competency_type": "application"}

    def test_skeleton_preserves_mcq_type(self):
        from core import section_generator as sg
        instr, skel = sg._regen_question_skeleton({"type": "MCQ", "subtype": "standard"}, 5, 1)
        self.assertIn('"type": "MCQ"', skel)
        self.assertIn('"options"', skel)
        self.assertIn("MCQ", instr)

    def test_skeleton_preserves_la_type(self):
        from core import section_generator as sg
        instr, skel = sg._regen_question_skeleton({"type": "LA", "subtype": "standard"}, 31, 5)
        self.assertIn('"type": "LA"', skel)
        self.assertIn('"or_alternative"', skel)
        self.assertNotIn('"options"', skel)

    def test_drifted_sa_replacement_is_rejected_for_mcq(self):
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(["MCQ", "True/False", "Fill in the Blanks"])
        questions = [self._mcq(1, "What is binary grouping?"),
                     self._mcq(2, "What is binary grouping for octal?")]
        warnings = ["Q1 and Q2 overlap 70% — likely duplicate concept"]

        def fake_converse(**kw):
            if kw.get("model_id") == sg.mantle_client.VAL_MODEL:
                return ('{"same_concept": true, "reason": "dup"}', 0, 0)   # confirm dup
            # regen returns an SA (the old hardcoded-SA behaviour) — must be rejected
            return ('{"qnum": 2, "type": "SA", "text": "Explain binary.", "marks": 1, '
                    '"answer_explanation": "pts", "chapter_tag": "X", '
                    '"competency_type": "constructed"}', 0, 0)

        with mock.patch.object(sg.mantle_client, "converse", side_effect=fake_converse):
            out, remaining = sg.verify_and_fix_semantic_duplicates(questions, warnings, wo, [])
        self.assertEqual(out[1]["type"], "MCQ")              # original MCQ kept, not SA
        self.assertIn("options", out[1])
        self.assertEqual(len(out), 2)                         # count preserved

    def test_valid_mcq_replacement_is_applied(self):
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(["MCQ"])
        questions = [self._mcq(1, "What is binary grouping?"),
                     self._mcq(2, "What is binary grouping for octal?")]
        warnings = ["Q1 and Q2 overlap 70% — likely duplicate concept"]

        def fake_converse(**kw):
            if kw.get("model_id") == sg.mantle_client.VAL_MODEL:
                return ('{"same_concept": true, "reason": "dup"}', 0, 0)
            return ('{"qnum": 2, "type": "MCQ", "subtype": "standard", '
                    '"text": "Which radix does hexadecimal use?", '
                    '"options": {"a": "8", "b": "10", "c": "16", "d": "2"}, "answer": "c", '
                    '"answer_explanation": "hex is base 16", "chapter_tag": "X", '
                    '"competency_type": "application"}', 0, 0)

        with mock.patch.object(sg.mantle_client, "converse", side_effect=fake_converse):
            out, remaining = sg.verify_and_fix_semantic_duplicates(questions, warnings, wo, [])
        self.assertEqual(out[1]["type"], "MCQ")
        self.assertIn("radix", out[1]["text"])               # replacement applied
        self.assertEqual(remaining, [])                       # warning resolved


class SingularQuestionTypeTest(TestCase):
    """Patterns saved by the generate-page form store the type as singular 'question_type'
    (not the plural 'question_types' list). It must still reach the work order — otherwise the
    section carries no type and the model mixes MCQs into a Short-Answer section, etc."""

    SECTIONS = [
        {"id": "A", "name": "Section A", "marks": 10, "question_type": "MCQ",
         "questions_count": 10, "marks_per_question": 1},
        {"id": "B", "name": "Section B", "marks": 8, "question_type": "Short Answer",
         "questions_count": 4, "marks_per_question": 2},
        {"id": "C", "name": "Section C", "marks": 4, "question_type": "Long Answer",
         "questions_count": 1, "marks_per_question": 4},
    ]

    def test_blueprint_maps_singular_question_type(self):
        pattern = ExamPattern(name="singular", sections=self.SECTIONS)
        bp = sg_gen.pattern_sections_to_blueprint_dict(pattern)
        self.assertEqual(bp["Section A"]["question_types"], ["MCQ"])
        self.assertEqual(bp["Section B"]["question_types"], ["Short Answer"])
        self.assertEqual(bp["Section C"]["question_types"], ["Long Answer"])

    def test_work_orders_carry_type_and_enforce_it(self):
        pattern = ExamPattern(name="singular2", sections=self.SECTIONS)
        bp = sg_gen.pattern_sections_to_blueprint_dict(pattern)
        wos = sg.build_work_orders(bp, pattern, {}, "medium", "5", "Mathematics", ["Patterns"])
        by_name = {w.section_name: w for w in wos}
        self.assertEqual(by_name["Section A"].question_types, ["MCQ"])
        self.assertEqual(by_name["Section B"].question_types, ["Short Answer"])
        # The type constraint is now actually enforced: an MCQ in the SA section is rejected.
        mcq = {"qnum": 1, "type": "MCQ", "subtype": "standard", "text": "Pick", "marks": 2,
               "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a"}
        errs = sg.validate_section_output({"questions": [mcq]}, by_name["Section B"])
        self.assertTrue(any("Wrong question type" in e for e in errs), errs)

    def test_build_work_orders_reads_singular_when_blueprint_lacks_plural(self):
        # A blueprint dict carrying only the singular field must still yield a typed work order.
        bp = {"Section B": {"id": "B", "name": "Section B", "marks": 8,
                            "question_type": "Short Answer", "questions_count": 4,
                            "marks_per_question": 2}}
        wos = sg.build_work_orders(bp, None, {}, "medium", "5", "Mathematics", ["Patterns"])
        self.assertEqual(wos[0].question_types, ["Short Answer"])


class PaperEditOperationsTest(TestCase):
    """The operation-based AI editor: move/delete/swap/set/add/edit + renumber. These are the
    deterministic guts of 'full control' — verified without any model call via a fake generator."""

    def _paper(self):
        return {
            "Section A": {"section_name": "Section A", "section_id": "A", "questions": [
                {"qnum": 1, "type": "MCQ", "marks": 1, "text": "A-one",
                 "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "a"},
                {"qnum": 2, "type": "MCQ", "marks": 1, "text": "A-two",
                 "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "b"},
            ]},
            "Section B": {"section_name": "Section B", "section_id": "B", "questions": [
                {"qnum": 3, "type": "SA", "marks": 3, "text": "B-one", "answer_explanation": "…"},
                {"qnum": 4, "type": "SA", "marks": 3, "text": "B-two", "answer_explanation": "…"},
            ]},
        }

    def _qtexts(self, pd, section):
        return [q["text"] for q in pd[section]["questions"]]

    def test_move_question_across_sections(self):
        pd, applied, notes = pe.apply_operations(
            self._paper(), [{"action": "move", "qnum": 1, "to_section": "Section B"}])
        self.assertNotIn("A-one", self._qtexts(pd, "Section A"))
        self.assertIn("A-one", self._qtexts(pd, "Section B"))
        self.assertTrue(any("moved" in a for a in applied))

    def test_move_resolves_section_by_letter(self):
        # "Section B" target given simply as "B" must still resolve via section_id.
        pd, applied, _ = pe.apply_operations(
            self._paper(), [{"action": "move", "qnum": 1, "to_section": "B"}])
        self.assertIn("A-one", self._qtexts(pd, "Section B"))

    def test_delete_question(self):
        pd, applied, _ = pe.apply_operations(self._paper(), [{"action": "delete", "qnum": 2}])
        self.assertNotIn("A-two", self._qtexts(pd, "Section A"))
        self.assertEqual(len(pd["Section A"]["questions"]), 1)

    def test_set_marks_field(self):
        pd, applied, _ = pe.apply_operations(
            self._paper(), [{"action": "set", "qnum": 3, "fields": {"marks": 5}}])
        self.assertEqual(pd["Section B"]["questions"][0]["marks"], 5)

    def test_set_flat_form(self):
        # Tolerate the flat shape {"action":"set","qnum":3,"marks":5} (no nested "fields").
        pd, _a, _n = pe.apply_operations(self._paper(), [{"action": "set", "qnum": 3, "marks": 5}])
        self.assertEqual(pd["Section B"]["questions"][0]["marks"], 5)

    def test_swap_questions(self):
        pd, applied, _ = pe.apply_operations(
            self._paper(), [{"action": "swap", "qnum_a": 1, "qnum_b": 2}])
        self.assertEqual(self._qtexts(pd, "Section A"), ["A-two", "A-one"])

    def test_renumber_is_sequential_after_structural_change(self):
        pd, _a, _n = pe.apply_operations(
            self._paper(), [{"action": "move", "qnum": 1, "to_section": "Section B"}])
        nums = [q["qnum"] for _n, s in pe.iter_sections(pd) for q in s["questions"]]
        self.assertEqual(nums, [1, 2, 3, 4])

    def test_add_uses_generator_and_inserts(self):
        def fake_gen(kind, ctx):
            self.assertEqual(kind, "add")
            return {"type": ctx["type"], "marks": ctx["marks"], "text": "fresh added Q",
                    "answer_explanation": "…"}
        pd, applied, _ = pe.apply_operations(
            self._paper(),
            [{"action": "add", "section": "Section B", "type": "SA", "marks": 3,
              "instruction": "on fractions"}],
            generate_fn=fake_gen)
        self.assertIn("fresh added Q", self._qtexts(pd, "Section B"))
        self.assertEqual(len(pd["Section B"]["questions"]), 3)

    def test_edit_replaces_text_and_preserves_identity(self):
        def fake_gen(kind, ctx):
            return {"text": "reworded", "type": ctx["question"]["type"]}
        pd, applied, _ = pe.apply_operations(
            self._paper(), [{"action": "edit", "qnum": 1, "instruction": "reword"}],
            generate_fn=fake_gen)
        q1 = pd["Section A"]["questions"][0]
        self.assertEqual(q1["text"], "reworded")
        self.assertEqual(q1["marks"], 1)          # marks preserved on a plain edit

    def test_unknown_and_missing_ops_are_noted_not_fatal(self):
        pd, applied, notes = pe.apply_operations(self._paper(), [
            {"action": "frobnicate", "qnum": 1},        # unknown
            {"action": "delete", "qnum": 999},           # missing target
            {"action": "delete", "qnum": 1},             # valid — must still apply
        ])
        self.assertEqual(applied, ["deleted Q1"])
        self.assertEqual(len(notes), 2)
        self.assertNotIn("A-one", self._qtexts(pd, "Section A"))

    def test_multiple_ops_apply_in_order(self):
        pd, applied, _ = pe.apply_operations(self._paper(), [
            {"action": "delete", "qnum": 2},
            {"action": "move", "qnum": 3, "to_section": "Section A"},
            {"action": "set", "qnum": 4, "fields": {"marks": 4}},
        ])
        self.assertIn("B-one", self._qtexts(pd, "Section A"))
        self.assertEqual(len(applied), 3)
        # renumbered 1..N with no gaps
        nums = [q["qnum"] for _n, s in pe.iter_sections(pd) for q in s["questions"]]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))


class MarksRightAlignTest(TestCase):
    """Per-question marks must snap to a right-aligned tab at the supplied text-area width, so
    they sit flush at the right margin (not the old fixed 5.75\")."""

    def _render(self, text, tab_twips, left_indent=None):
        import re as _re
        from docx import Document
        from docx.shared import Inches
        from lxml import etree
        from core.generator import _add_question_with_marks
        marks_pattern = _re.compile(r"\s*\[(\d+)\s*marks?\]", _re.IGNORECASE)
        li = Inches(left_indent) if left_indent is not None else None
        p = _add_question_with_marks(Document(), text, marks_pattern,
                                     left_indent=li, right_tab_twips=tab_twips)
        return p, etree.tostring(p._element, encoding="unicode")

    def test_marks_use_supplied_right_tab(self):
        p, xml = self._render("1. What is 2+2? [2 marks]", 10068)
        self.assertIn('val="right"', xml)            # right-aligned tab stop
        self.assertIn('pos="10068"', xml)            # at the supplied text-area width
        self.assertIn("\t[2]", p.text)               # marks rendered number-only after a tab

    def test_marks_tab_tracks_position(self):
        _p, xml = self._render("3. Define osmosis. [3 marks]", 9750)
        self.assertIn('pos="9750"', xml)
        self.assertNotIn('pos="8280"', xml)          # no longer the hardcoded fallback

    def test_no_right_tab_when_no_marks(self):
        _p, xml = self._render("1. A plain question with no marks tag.", 10068)
        self.assertNotIn('val="right"', xml)

    def test_numbered_question_gets_hanging_indent(self):
        # The number is isolated in a hanging-indent column; body text snaps to it via a tab,
        # so wrapped lines align under the text — not under the number.
        p, xml = self._render("8. A long question that wraps onto a second line. [1 marks]", 10068)
        self.assertIn('hanging', xml)                # hanging indent applied
        self.assertIn('val="left"', xml)             # left tab stop at the hang column
        self.assertIn('pos="504"', xml)              # 0.35in * 1440 = 504 twips
        self.assertIn("8.\t", p.text)                # number + tab before the body text

    def test_subquestion_hang_nests_under_its_indent(self):
        # A sub-question indented 0.25" hangs relative to that → body column at 0.25+0.35=0.6".
        _p, xml = self._render("(ii) A wrapped sub-question. [2 marks]", 10068, left_indent=0.25)
        self.assertIn('hanging', xml)
        self.assertIn('pos="864"', xml)              # (0.25+0.35)*1440 = 864 twips

    def test_unnumbered_line_has_no_hanging_indent(self):
        _p, xml = self._render("A passage lead-in with no leading number.", 10068)
        self.assertNotIn('hanging', xml)

    def test_tabs_precede_ind_in_pPr(self):
        # Regression: <w:tabs> MUST come before <w:ind> in <w:pPr> (OOXML CT_PPr order). When it
        # was appended last, Word dropped the left tab and the first body line shot far right.
        p, _xml = self._render("8. A wrapped question. [1 marks]", 10068)
        order = [c.tag.split('}')[-1] for c in p._element.get_or_add_pPr()]
        self.assertIn('tabs', order)
        self.assertIn('ind', order)
        self.assertLess(order.index('tabs'), order.index('ind'))


class ChapterAllocationTest(TestCase):
    """Deterministic, CBSE-weighted, coverage-balanced chapter allocation."""

    def test_plan_length_equals_question_count(self):
        from core import section_generator as sg
        plan = sg._allocate_chapters_to_slots(["A", "B", "C", "D", "E"], 3, "X", {})
        self.assertEqual(len(plan), 3)

    def test_uniform_weights_spread_distinct_when_fewer_slots(self):
        from unittest import mock
        from core import section_generator as sg
        with mock.patch.object(sg, "_chapter_weight", return_value=1):
            plan = sg._allocate_chapters_to_slots(["A", "B", "C", "D", "E"], 3, "X", {})
        self.assertEqual(len(set(plan)), 3)        # 3 distinct chapters, no clustering

    def test_more_slots_than_chapters_covers_all_then_repeats(self):
        from collections import Counter
        from unittest import mock
        from core import section_generator as sg
        with mock.patch.object(sg, "_chapter_weight", return_value=1):
            plan = sg._allocate_chapters_to_slots(["A", "B", "C"], 7, "X", {})
        c = Counter(plan)
        self.assertEqual(set(c), {"A", "B", "C"})  # every chapter covered
        self.assertEqual(sum(c.values()), 7)
        self.assertGreaterEqual(min(c.values()), 2)

    def test_heavier_chapter_gets_more_questions(self):
        from collections import Counter
        from unittest import mock
        from core import section_generator as sg
        w = {"Heavy": 10, "Light": 1}
        with mock.patch.object(sg, "_chapter_weight", side_effect=lambda subj, ch: w.get(ch, 1)):
            plan = sg._allocate_chapters_to_slots(["Heavy", "Light"], 6, "X", {})
        c = Counter(plan)
        self.assertGreater(c["Heavy"], c.get("Light", 0))

    def test_sections_coordinate_to_fill_coverage_gaps(self):
        from unittest import mock
        from core import section_generator as sg
        with mock.patch.object(sg, "_chapter_weight", return_value=1):
            covered = {}
            p1 = sg._allocate_chapters_to_slots(["A", "B", "C", "D"], 2, "X", covered)
            p2 = sg._allocate_chapters_to_slots(["A", "B", "C", "D"], 2, "X", covered)
        self.assertEqual(len(set(p1) | set(p2)), 4)  # 2nd section fills what the 1st left out


class ChapterCoverageAuditTest(TestCase):
    """audit_chapter_coverage: every planned chapter should receive at least one question."""

    def test_no_plan_is_ok(self):
        from core.paper_audit import audit_chapter_coverage
        res = audit_chapter_coverage({"Section A": {"questions": [{"chapter_tag": "X"}]}})
        self.assertFalse(res["has_plan"])
        self.assertTrue(res["ok"])

    def test_all_planned_chapters_covered(self):
        from core.paper_audit import audit_chapter_coverage
        pd = {"Section A": {"_chapter_plan": ["Carbon", "Electricity"],
                            "questions": [{"chapter_tag": "Carbon and its Compounds"},
                                          {"chapter_tag": "Electricity"}]}}
        res = audit_chapter_coverage(pd)
        self.assertTrue(res["ok"])
        self.assertEqual(res["covered"], 2)
        self.assertEqual(res["missed"], [])

    def test_missed_chapter_is_flagged(self):
        from core.paper_audit import audit_chapter_coverage
        pd = {"Section A": {"_chapter_plan": ["Carbon", "Electricity"],
                            "questions": [{"chapter_tag": "Carbon"}, {"chapter_tag": "Carbon"}]}}
        res = audit_chapter_coverage(pd)
        self.assertFalse(res["ok"])
        self.assertEqual((res["planned"], res["covered"]), (2, 1))
        self.assertTrue(any("Electricity" in m for m in res["missed"]))

    def test_chapter_covered_in_another_section_is_not_a_gap(self):
        """A chapter planned for Section B but answered in Section A counts as covered — the
        old per-section audit wrongly reported it as 'Section B: <chapter> missing'."""
        from core.paper_audit import audit_chapter_coverage
        pd = {
            "Section A": {"_chapter_plan": ["Carbon"],
                          "questions": [{"chapter_tag": "Carbon"}]},
            "Section B": {"_chapter_plan": ["Carbon", "Acids"],
                          "questions": [{"chapter_tag": "Acids"}]},
        }
        res = audit_chapter_coverage(pd)
        self.assertTrue(res["ok"])
        self.assertEqual(res["missed"], [])
        self.assertEqual((res["planned"], res["covered"]), (2, 2))      # distinct chapters
        self.assertEqual((res["slot_planned"], res["slot_covered"]), (3, 2))  # section-slots


class SectionTopUpTest(TestCase):
    """A uniform-marks section that comes back short on count is filled by ONE focused top-up
    call, strictly additively (only valid, correctly-typed, non-duplicate questions, never
    more than the shortfall)."""

    # Genuinely distinct question stems so concept-overlap dedup doesn't falsely reject them.
    EXISTING = ["Atomic radius decreases across a period left to right.",
                "Noble gases have completely filled valence shells."]
    FRESH = ["Methane exhibits a tetrahedral molecular geometry.",
             "Sodium chloride forms via ionic bonding between Na and Cl.",
             "Benzene shows delocalised pi electron resonance stability.",
             "Hydrogen bonding raises the boiling point of water."]

    def _wo(self, n, types=("MCQ",)):
        from core.section_generator import SectionWorkOrder
        return SectionWorkOrder(
            section_name="Section A", section_id="A", title="MCQ", marks=n,
            questions_count=n, marks_per_question=1, question_types=list(types),
            instructions=[], constraints={}, context_text="", difficulty="medium",
            subject="Chemistry", class_name="11", chapters=["Structure of Atom", "Chemical Bonding"],
        )

    @staticmethod
    def _mcq(text, chapter="Chemical Bonding"):
        return {"type": "MCQ", "text": text, "options": ["a) 1", "b) 2", "c) 3", "d) 4"],
                "answer": "a", "marks": 1, "chapter_tag": chapter}

    def _existing(self, n):
        return [self._mcq(t, "Structure of Atom") for t in self.EXISTING[:n]]

    def test_topup_fills_missing_mcqs(self):
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(4)
        section_data = {"questions": self._existing(2)}
        fake = json.dumps({"questions": [self._mcq(t) for t in self.FRESH[:2]]})
        with mock.patch.object(sg.mantle_client, "converse", return_value=(fake, 10, 20)):
            tokens = sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 4)
        self.assertEqual(section_data.get("_topped_up"), 2)
        self.assertEqual(tokens, (10, 20))

    def test_topup_fills_mcq_plus_assertion_reason_section(self):
        """The reported case: a 16-q 'MCQ + Assertion-Reason' Section A short by 1 — the old
        single-category guard skipped it. An AR question (type MCQ, subtype assertion_reason)
        is a valid fill for the allowed set."""
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(3, types=("MCQ", "Assertion-Reason"))
        section_data = {"questions": self._existing(2)}
        ar = {"type": "MCQ", "subtype": "assertion_reason",
              "text": "Assertion (A): Oxygen is paramagnetic.\nReason (R): It has two unpaired electrons.",
              "options": ["a) ...", "b) ...", "c) ...", "d) ..."], "answer": "a",
              "marks": 1, "chapter_tag": "Chemical Bonding"}
        with mock.patch.object(sg.mantle_client, "converse", return_value=(json.dumps({"questions": [ar]}), 5, 5)):
            sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 3)
        self.assertEqual(section_data.get("_topped_up"), 1)

    def test_topup_rejects_near_duplicate(self):
        """A topped-up question that echoes an existing one is dropped (no V5 chain runs on it)."""
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(3)
        section_data = {"questions": self._existing(2)}
        dup = self._mcq(self.EXISTING[0])      # verbatim echo of an existing question
        with mock.patch.object(sg.mantle_client, "converse", return_value=(json.dumps({"questions": [dup]}), 1, 1)):
            sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 2)        # duplicate rejected
        self.assertNotIn("_topped_up", section_data)

    def test_topup_never_exceeds_shortfall(self):
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(3)                                   # need 3, have 2 → only 1 missing
        section_data = {"questions": self._existing(2)}
        fake = json.dumps({"questions": [self._mcq(t) for t in self.FRESH[:4]]})  # over-delivers
        with mock.patch.object(sg.mantle_client, "converse", return_value=(fake, 1, 1)):
            sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 3)

    def test_topup_noop_when_section_complete(self):
        from core import section_generator as sg
        wo = self._wo(2)
        section_data = {"questions": self._existing(2)}
        self.assertEqual(sg._top_up_short_section(section_data, wo), (0, 0))
        self.assertNotIn("_topped_up", section_data)

    def test_topup_fills_free_form_type_section(self):
        """AI-generated patterns declare descriptive types ('3-5 Mark Questions', 'Essay',
        'Letter Writing') that classify to 'other', so the old guard skipped the top-up and the
        section shipped short (the reported Tamil paper: SA 27/30, LA 15/20, etc.). A plain
        uniform-marks section with free-form types must still be filled (loose mode)."""
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(4, types=("3–5 Mark Questions",))      # descriptive label → 'other'
        sa = lambda t: {"type": "SA", "text": t, "marks": 1, "chapter_tag": "Chemical Bonding"}
        section_data = {"questions": [sa(t) for t in self.EXISTING[:2]]}
        fresh = json.dumps({"questions": [sa(t) for t in self.FRESH[:2]]})
        with mock.patch.object(sg.mantle_client, "converse", return_value=(fresh, 7, 9)):
            tokens = sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 4)        # filled 2/2 missing
        self.assertEqual(section_data.get("_topped_up"), 2)
        self.assertEqual(tokens, (7, 9))
        self.assertTrue(all(q["marks"] == 1 for q in section_data["questions"]))

    def test_topup_freeform_still_rejects_structural_types(self):
        """Loose mode accepts any written-answer question but must NOT pull a CBQ/map question
        into a plain section it can't structurally host."""
        import json
        from unittest import mock
        from core import section_generator as sg
        wo = self._wo(3, types=("Essay",))
        sa = lambda t: {"type": "SA", "text": t, "marks": 1, "chapter_tag": "Chemical Bonding"}
        section_data = {"questions": [sa(t) for t in self.EXISTING[:2]]}
        cbq = {"type": "CBQ", "text": "Read the passage and answer.", "marks": 1,
               "sub_questions": [{"text": "x", "marks": 1}], "chapter_tag": "Chemical Bonding"}
        with mock.patch.object(sg.mantle_client, "converse", return_value=(json.dumps({"questions": [cbq]}), 1, 1)):
            sg._top_up_short_section(section_data, wo)
        self.assertEqual(len(section_data["questions"]), 2)        # CBQ rejected, nothing added
        self.assertNotIn("_topped_up", section_data)


class PatternAIEnhanceTest(TestCase):
    """validate_and_enhance_pattern: a section's own marks already cover its subsections, so the
    paper total must NOT add both (a subsectioned Hindi board paper summed to 146 instead of 80)."""

    def test_subsection_marks_not_double_counted(self):
        from core import pattern_ai_generator as pag
        raw = {"sections": [
            {"id": "A", "name": "Unseen", "marks": 14, "questions_count": 2, "marks_per_question": 7,
             "question_types": ["Comprehension"], "subsections": []},
            {"id": "B", "name": "Grammar", "marks": 16, "questions_count": 4, "marks_per_question": 4,
             "question_types": ["Short Answer"],
             "subsections": [{"marks": 4, "questions_count": 4} for _ in range(4)]},
            {"id": "D", "name": "Writing", "marks": 22, "questions_count": 5, "marks_per_question": None,
             "question_types": ["Paragraph", "Letter"],
             "subsections": [{"marks": m, "questions_count": 1} for m in (5, 5, 4, 3, 5)]},
        ]}
        out = pag.validate_and_enhance_pattern(raw, "10", "Hindi", "Board")
        self.assertEqual(out["total_marks"], 52)          # 14 + 16 + 22, subsections NOT re-added
        self.assertEqual(out["total_questions"], 11)      # 2 + 4 + 5
        # None marks_per_question is coerced to the section average, never left None.
        self.assertIsNotNone(out["sections"][2]["marks_per_question"])

    def test_section_marks_fallback_to_subsection_sum(self):
        from core import pattern_ai_generator as pag
        raw = {"sections": [
            {"id": "C", "name": "Textbook", "marks": 0, "questions_count": 0,
             "question_types": ["MCQ"],
             "subsections": [{"marks": 5, "questions_count": 5}, {"marks": 6, "questions_count": 3}]},
        ]}
        out = pag.validate_and_enhance_pattern(raw, "10", "Hindi", "Board")
        # Section declared 0 → fall back to the subsection sum (11), don't leave it empty.
        self.assertEqual(out["total_marks"], 11)
        self.assertEqual(out["sections"][0]["marks"], 11)
        self.assertEqual(out["sections"][0]["questions_count"], 8)


class LanguageSupportTest(TestCase):
    """Tamil & Hindi: the right complex-script font is applied at render, and the generation
    prompt instructs the model to write in the target language/script."""

    def test_script_font_picker(self):
        from core.generator import _pick_script_font
        self.assertEqual(_pick_script_font("Hindi Core", []), "Nirmala UI")
        self.assertEqual(_pick_script_font("Sanskrit", []), "Nirmala UI")
        self.assertEqual(_pick_script_font("Tamil", []), "Latha")
        self.assertIsNone(_pick_script_font("Science", [("q", "What is photosynthesis?")]))
        # Detected from the text even when the subject name is non-obvious.
        self.assertEqual(_pick_script_font("X", [("q", "जल का सूत्र?")]), "Nirmala UI")
        self.assertEqual(_pick_script_font("X", [("q", "இது ஒரு வினா")]), "Latha")

    def test_devanagari_run_gets_complex_script_font(self):
        import re
        from docx import Document
        from docx.oxml.ns import qn
        from core.generator import _add_question_with_marks
        doc = Document()
        _add_question_with_marks(doc, "1. जल का रासायनिक सूत्र क्या है? [1 marks]",
                                 re.compile(r"\s*\[(\d+)\s*marks?\]", re.I), None, "Nirmala UI")
        run = doc.paragraphs[-1].runs[-1]
        rFonts = run._element.get_or_add_rPr().find(qn("w:rFonts"))
        self.assertIsNotNone(rFonts)
        self.assertEqual(rFonts.get(qn("w:cs")), "Nirmala UI")

    def test_language_directive_for_language_subjects(self):
        from core.section_generator import _language_directive
        self.assertIn("Devanagari", _language_directive("Hindi Course B"))
        self.assertIn("Tamil", _language_directive("Tamil"))
        self.assertEqual(_language_directive("Science"), "")
        self.assertEqual(_language_directive("Mathematics"), "")

    def test_language_directive_injected_into_section_prompt(self):
        from core.section_generator import build_section_prompt, SectionWorkOrder
        wo = SectionWorkOrder(
            section_name="Section A", section_id="A", title="MCQ", marks=5, questions_count=5,
            marks_per_question=1, question_types=["MCQ"], instructions=[], constraints={},
            context_text="", difficulty="medium", subject="Hindi", class_name="10",
            chapters=["कविता"],
        )
        prompt = build_section_prompt(wo)
        self.assertIn("LANGUAGE — MANDATORY", prompt)
        self.assertIn("Devanagari", prompt)


class MaterialIntelTest(TestCase):
    """Intelligent ingestion: chapter-name cleaning, catalog snapping, book page-range splitting,
    and LLM-based unit naming."""

    def test_clean_name_strips_chapter_prefix(self):
        from core.material_intel import _clean_name
        self.assertEqual(_clean_name("Chapter 4 - Chemical Bonding"), "Chemical Bonding")
        self.assertEqual(_clean_name("UNIT 2: Structure of Atom"), "Structure of Atom")
        self.assertEqual(_clean_name("  Thermodynamics  "), "Thermodynamics")

    def test_snap_to_catalog(self):
        from core.material_intel import _snap_to_catalog
        # Physics has a catalog → a close/substring name snaps to the official one.
        self.assertEqual(_snap_to_catalog("current electricity", "Physics"), "Current Electricity")
        # No catalog for the subject → returned unchanged.
        self.assertEqual(_snap_to_catalog("My Custom Topic", "Hindi"), "My Custom Topic")

    def test_ranges_from_starts(self):
        from core.material_intel import _ranges_from_starts
        chapters = _ranges_from_starts([("Intro", 0), ("Atoms", 5), ("Bonds", 12)], 20)
        self.assertEqual(len(chapters), 3)
        self.assertEqual((chapters[0]["start_page"], chapters[0]["end_page"]), (0, 5))
        self.assertEqual((chapters[2]["start_page"], chapters[2]["end_page"]), (12, 20))
        self.assertEqual(chapters[1]["unit"], "Atoms")

    def test_detect_unit_name_snaps_to_catalog(self):
        from unittest import mock
        from core import material_intel as mi
        with mock.patch.object(mi.mantle_client, "converse",
                               return_value=('{"chapter": "current electricity"}', 1, 1)):
            name = mi.detect_unit_name(None, "12", "Physics", sample_text="...physics text...")
        self.assertEqual(name, "Current Electricity")

    def test_detect_unit_name_empty_sample_returns_none(self):
        from core import material_intel as mi
        self.assertIsNone(mi.detect_unit_name(None, "12", "Physics", sample_text="   "))

    def test_legacy_font_gibberish_is_unreadable(self):
        """A Hindi PDF typeset in a legacy non-Unicode font (Walkman-Chanakya905) extracts as
        ASCII keystroke gibberish with no Devanagari — must be flagged unreadable so naming falls
        back to the filename instead of returning confident garbage ('dchj')."""
        from core import material_intel as mi
        chanakya = "i| [kaM ,d jk\"Vªh; vfLerk vkSj jk\"Vªh; pfj=k dk fodkl"  # real Chanakya extraction
        self.assertTrue(mi.text_is_unreadable_for_subject(chanakya, "Hindi"))
        # And detect_unit_name bails to None on it (no LLM call reached).
        self.assertIsNone(mi.detect_unit_name(None, "10", "Hindi", sample_text=chanakya))

    def test_real_devanagari_is_readable(self):
        from core import material_intel as mi
        self.assertFalse(mi.text_is_unreadable_for_subject("दो बैलों की कथा — प्रेमचंद की कहानी", "Hindi"))

    def test_latin_subject_never_flagged_unreadable(self):
        from core import material_intel as mi
        # English/maths content is ASCII by nature — the guard applies only to Indic-script subjects.
        self.assertFalse(mi.text_is_unreadable_for_subject("Chapter 1: Real Numbers", "Mathematics"))
        self.assertFalse(mi.text_is_unreadable_for_subject("The Sound of Music", "English"))

    def test_extract_html_chapters_by_heading(self):
        from core.material_intel import extract_html_chapters
        html = (
            "<html><body><h1>Book Title</h1>"
            "<h2>இயல் ஒன்று</h2>"
            "<p>தமிழ் உரை ஒன்று. இது முதல் பாடத்தின் முழுமையான உரை ஆகும் இங்கே.</p>"
            "<h2>இயல் இரண்டு</h2>"
            "<p>இரண்டாம் பாடத்தின் உரை. போதுமான நீளம் கொண்ட உரை இங்கே உள்ளது.</p>"
            "</body></html>"
        )
        chs = extract_html_chapters(html, "Tamil")
        units = [c["unit"] for c in chs]
        self.assertIn("இயல் ஒன்று", units)
        self.assertIn("இயல் இரண்டு", units)
        # Body text is captured; the <h1> book title before the first chapter is excluded.
        self.assertTrue(all(c["text"] and "Book Title" not in c["text"] for c in chs))

    def test_extract_html_single_chapter_when_no_headings(self):
        from core.material_intel import extract_html_chapters
        html = "<html><body><p>" + ("உரை " * 40) + "</p></body></html>"
        chs = extract_html_chapters(html, "Tamil")
        self.assertEqual(len(chs), 1)
        self.assertIsNone(chs[0]["unit"])   # caller will name it

    def test_preview_url_endpoint_returns_chapters_without_ingesting(self):
        from unittest import mock
        from rest_framework.test import APIClient
        u = User.objects.create_user("previewer", "p@x.com", "pw")
        api = APIClient()
        api.force_authenticate(u)
        html = ("<html><body>"
                "<h2>இயல் ஒன்று</h2><p>" + ("உரை " * 30) + "</p>"
                "<h2>இயல் இரண்டு</h2><p>" + ("உரை " * 30) + "</p></body></html>")
        with mock.patch("core.material_intel.fetch_url", return_value=html):
            r = api.post('/api/materials/preview-url/',
                         {'url': 'https://example.com/book.html', 'subject': 'Tamil'}, format='json')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['count'], 2)
        self.assertIn("இயல் ஒன்று", [c['unit'] for c in body['chapters']])


class ImageStemGuardTest(TestCase):
    """A generic 'observe the diagram and answer' stem must NOT be turned into an image prompt
    (that produced a second, irrelevant image — e.g. an org chart on a chemistry CBQ)."""

    def test_generic_pointer_stems_are_flagged(self):
        from core.generator import _is_generic_image_stem
        for s in [
            "Observe the diagram carefully and answer the following questions:",
            "Study the figure below and answer:",
            "Refer to the graph shown and identify the trend.",
            "Based on the diagram, explain the periodic trend.",
            "Read the source/case and answer the questions that follow:",
        ]:
            self.assertTrue(_is_generic_image_stem(s), f"should be generic: {s!r}")

    def test_real_descriptions_are_not_flagged(self):
        from core.generator import _is_generic_image_stem
        for s in [
            "A line graph with Atomic Number on the X-axis and Atomic Radius on the Y-axis showing a decreasing trend.",
            "The Lewis structure of carbon dioxide with two double bonds drawn around the central atom.",
            "A titration apparatus with a burette clamped above a conical flask containing an indicator.",
        ]:
            self.assertFalse(_is_generic_image_stem(s), f"should NOT be generic: {s!r}")


class RerenderImageCacheTest(TestCase):
    """Synchronous re-render must reuse cached images and NEVER call the slow image APIs
    (those calls could block the request for minutes → page timeout)."""

    @staticmethod
    def _boom(*a, **k):
        raise AssertionError("external image API was called in cache_only mode")

    def test_cache_only_raises_without_any_network_call(self):
        from unittest import mock
        from core import generator as g
        with mock.patch.object(g, "_openai_image_bytes", self._boom), \
             mock.patch.object(g, "_together_image_bytes", self._boom), \
             mock.patch.object(g, "_pollinations_image_bytes", self._boom):
            with self.assertRaises(g.ImageNotCached):
                g.generate_ai_image("a unique uncached prompt 12345", cache_only=True)

    def test_materialize_images_cache_only_skips_uncached_image(self):
        from unittest import mock
        from core import generator as g
        items = [("q", "1. A question"), ("image_gen", "another unique uncached prompt 67890")]
        with mock.patch.object(g, "_openai_image_bytes", self._boom), \
             mock.patch.object(g, "_together_image_bytes", self._boom), \
             mock.patch.object(g, "_pollinations_image_bytes", self._boom):
            out = g.materialize_images(items, allow=True, cache_only=True)
        self.assertIn(("q", "1. A question"), out)            # text preserved
        self.assertFalse(any(t == "image" for t, _ in out))   # uncached image dropped, not hung on


class PaperMarksAuditTest(TestCase):
    """audit_paper_marks: per-question marks (OR pair counted once) must add up to the pattern."""

    class _Pat:
        def __init__(self, sections, total_marks):
            self.sections = sections
            self.total_marks = total_marks

    def _pat(self):
        secs = [
            {"name": "Section A", "marks": 4, "questions_count": 4, "marks_per_question": 1.0},
            {"name": "Section E", "marks": 10, "questions_count": 2, "marks_per_question": 5.0},
        ]
        return self._Pat(secs, 14)

    def test_clean_paper_passes(self):
        from core.paper_audit import audit_paper_marks
        pd = {
            "Section A": {"marks": 4, "questions": [{"marks": 1} for _ in range(4)]},
            "Section E": {"marks": 10, "questions": [{"marks": 5}, {"marks": 5}]},
        }
        res = audit_paper_marks(pd, self._pat())
        self.assertTrue(res["ok"], res["issues"])
        self.assertEqual(res["actual_total"], 14)

    def test_under_produced_section_is_flagged(self):
        from core.paper_audit import audit_paper_marks
        pd = {  # Section A only has 2 of 4 questions
            "Section A": {"marks": 4, "questions": [{"marks": 1}, {"marks": 1}]},
            "Section E": {"marks": 10, "questions": [{"marks": 5}, {"marks": 5}]},
        }
        res = audit_paper_marks(pd, self._pat())
        self.assertFalse(res["ok"])
        self.assertEqual(res["actual_total"], 12)
        self.assertTrue(any("Section A" in i and "questions" in i for i in res["issues"]))

    def test_over_marked_section_is_flagged(self):
        from core.paper_audit import audit_paper_marks
        pd = {  # right count (4) but inflated marks (2 each → 8, expected 4)
            "Section A": {"marks": 4, "questions": [{"marks": 2} for _ in range(4)]},
            "Section E": {"marks": 10, "questions": [{"marks": 5}, {"marks": 5}]},
        }
        res = audit_paper_marks(pd, self._pat())
        self.assertFalse(res["ok"])
        self.assertTrue(any("Section A" in i and "marks" in i for i in res["issues"]))

    def test_or_alternative_field_counts_once(self):
        from core.paper_audit import audit_paper_marks
        pd = {  # Section E questions carry an OR alternative as a FIELD — still 5m each, not 10
            "Section A": {"marks": 4, "questions": [{"marks": 1} for _ in range(4)]},
            "Section E": {"marks": 10, "questions": [
                {"marks": 5, "or_alternative": "Alternative question text"},
                {"marks": 5, "or_alternative": {"text": "Alt"}},
            ]},
        }
        res = audit_paper_marks(pd, self._pat())
        self.assertEqual(res["actual_total"], 14)
        self.assertTrue(res["ok"], res["issues"])

    def test_or_alternative_as_separate_entry_is_excluded(self):
        from core.paper_audit import audit_paper_marks
        pd = {  # an OR alternative leaked in as its own entry + an "OR" marker entry
            "Section A": {"marks": 4, "questions": [{"marks": 1} for _ in range(4)]},
            "Section E": {"marks": 10, "questions": [
                {"marks": 5},
                {"text": "OR"},                              # separator entry → excluded
                {"marks": 5, "is_or_alternative": True},      # alternative entry → excluded
                {"marks": 5},
            ]},
        }
        res = audit_paper_marks(pd, self._pat())
        # Section E should count only the 2 primary 5-mark questions = 10
        self.assertEqual(res["actual_total"], 14)
        self.assertTrue(res["ok"], res["issues"])


class MCQAnswerCorrectionTest(TestCase):
    """V4 auto-corrects a wrong MCQ key only when two independent high-confidence passes agree."""

    def _mcq(self, ans):
        return [{
            "type": "MCQ", "text": "2 + 2 = ?",
            "options": {"a": "3", "b": "4", "c": "5", "d": "6"},
            "answer": ans, "marks": 1,
        }]

    def _reply(self, letter, conf):
        import json as _json
        return (_json.dumps([{"q": 1, "answer": letter, "confidence": conf}]), 0, 0)

    def test_two_high_confidence_passes_correct_the_key(self):
        from unittest import mock
        from core import section_generator as sg
        qs = self._mcq("a")  # stored wrong; verifier insists on 'b' twice, high
        with mock.patch.object(sg.mantle_client, "converse",
                               side_effect=[self._reply("b", "high"), self._reply("b", "high")]):
            res = sg.verify_mcq_answers(qs, "10", "Mathematics")
        self.assertEqual(qs[0]["answer"], "b")          # key fixed in place
        self.assertTrue(res[0]["corrected"])
        self.assertFalse(res[0]["suspect"])             # fixed → not also flagged

    def test_single_disagreement_only_flags_not_corrects(self):
        from unittest import mock
        from core import section_generator as sg
        qs = self._mcq("a")  # first says 'b' high, second pass agrees with stored 'a' → don't flip
        with mock.patch.object(sg.mantle_client, "converse",
                               side_effect=[self._reply("b", "high"), self._reply("a", "high")]):
            res = sg.verify_mcq_answers(qs, "10", "Mathematics")
        self.assertEqual(qs[0]["answer"], "a")          # key unchanged
        self.assertFalse(res[0]["corrected"])
        self.assertTrue(res[0]["suspect"])              # flagged for human review

    def test_medium_confidence_never_corrects(self):
        from unittest import mock
        from core import section_generator as sg
        qs = self._mcq("a")
        with mock.patch.object(sg.mantle_client, "converse",
                               side_effect=[self._reply("b", "medium")]):
            res = sg.verify_mcq_answers(qs, "10", "Mathematics")
        self.assertEqual(qs[0]["answer"], "a")          # medium is never enough to overwrite
        self.assertFalse(res[0]["corrected"])
        self.assertTrue(res[0]["suspect"])


class FirstLoginPasswordTest(TestCase):
    """First-login flow: set a new password OR skip — both clear require_password_change."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.user = User.objects.create_user("newbie", "n@x.com", "temppass123")
        p = self.user.profile
        p.require_password_change = True
        p.save()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_set_password_clears_flag(self):
        r = self.api.post('/api/auth/first-login-password/', {'new_password': 'brandnew123'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.require_password_change)
        self.assertTrue(self.user.check_password('brandnew123'))

    def test_skip_clears_flag_keeps_password(self):
        r = self.api.post('/api/auth/first-login-password/', {'skip': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.require_password_change)
        self.assertTrue(self.user.check_password('temppass123'))

    def test_set_rejected_when_flag_already_false(self):
        p = self.user.profile
        p.require_password_change = False
        p.save()
        r = self.api.post('/api/auth/first-login-password/', {'new_password': 'brandnew123'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_short_password_rejected(self):
        r = self.api.post('/api/auth/first-login-password/', {'new_password': 'short'}, format='json')
        self.assertEqual(r.status_code, 400)


class TeamUsagePersistenceTest(TestCase):
    """The team-usage page reads each user's tokens/cost from the UsageEvent log, so the figures
    survive paper deletion (old behaviour: recomputed from live papers → reset to 0 on delete)."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.school = School.objects.create(name="Test School")

        def mk(uname, role):
            u = User.objects.create_user(uname, f"{uname}@x.com", "pw")
            p = u.profile
            p.school = self.school
            p.role = role
            p.save()
            return u

        self.admin = mk("admin1", "school_admin")
        self.teacher = mk("teach1", "teacher")
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def _row(self, username):
        r = self.api.get(f'/api/admin/schools/{self.school.id}/user-usage/')
        self.assertEqual(r.status_code, 200)
        return next(x for x in r.json()['users'] if x['username'] == username)

    def test_usage_comes_from_events_not_live_papers(self):
        from core.models import UsageEvent
        UsageEvent.record(user=self.teacher, input_tokens=1000, output_tokens=500, cost=2)
        row = self._row("teach1")
        self.assertEqual(row['total_tokens'], 1500)      # from the event …
        self.assertEqual(float(row['total_cost']), 2.0)
        self.assertEqual(row['total_papers'], 1)
        self.assertEqual(row['current_papers'], 0)       # … even with no surviving paper

    def test_monthly_excludes_prior_months(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.models import UsageEvent
        UsageEvent.record(user=self.teacher, input_tokens=100, cost=1)           # this month
        old = UsageEvent.record(user=self.teacher, input_tokens=900, cost=9)
        UsageEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=45))
        row = self._row("teach1")
        self.assertEqual(row['total_tokens'], 1000)      # all-time
        self.assertEqual(row['monthly_tokens'], 100)     # only the current-month event


class HierarchicalVisibilityTest(TestCase):
    """Validates the `_owner_scope` helper used for QuestionPaper visibility: a teacher sees only
    their OWN papers; a school_admin sees the whole school's; superadmin sees all. (Patterns and
    blueprints are intentionally school-wide-shared and do NOT use this helper.) ExamPattern rows
    are used here only as a convenient model with a `created_by` field to exercise the helper."""

    def setUp(self):
        from api.views import _owner_scope
        self._scope = _owner_scope
        self.school = School.objects.create(name="S")
        def mk(uname, role):
            u = User.objects.create_user(uname, f"{uname}@x.com", "pw")
            p = u.profile
            p.school = self.school
            p.role = role
            p.save()
            return u
        self.admin = mk("adm", "school_admin")
        self.t1 = mk("t1", "teacher")
        self.t2 = mk("t2", "teacher")
        secs = [{"name": "A", "marks": 10, "questions_count": 5}]
        self.p_admin = ExamPattern.objects.create(name="pa", sections=secs, created_by=self.admin)
        self.p_t1 = ExamPattern.objects.create(name="p1", sections=secs, created_by=self.t1)
        self.p_t2 = ExamPattern.objects.create(name="p2", sections=secs, created_by=self.t2)

    def test_teacher_sees_only_own(self):
        ids = set(self._scope(ExamPattern.objects.all(), self.t1).values_list("id", flat=True))
        self.assertEqual(ids, {self.p_t1.id})  # not the admin's, not the other teacher's

    def test_admin_sees_whole_school(self):
        ids = set(self._scope(ExamPattern.objects.all(), self.admin).values_list("id", flat=True))
        self.assertEqual(ids, {self.p_admin.id, self.p_t1.id, self.p_t2.id})


class BlueprintIsolationTest(TestCase):
    """A teacher must not see another school's ExamBlueprints (IDOR fix #3)."""

    def setUp(self):
        self.sa = School.objects.create(name="A")
        self.sb = School.objects.create(name="B")
        self.ua = User.objects.create_user("ta", "a@x.com", "pw")
        self.ub = User.objects.create_user("tb", "b@x.com", "pw")
        for u, s in ((self.ua, self.sa), (self.ub, self.sb)):
            p = u.profile          # auto-created by signal
            p.school = s
            p.role = "teacher"
            p.save()
        self.bp_a = ExamBlueprint.objects.create(class_name="10", subject="Science", blueprint={}, created_by=self.ua)
        self.bp_b = ExamBlueprint.objects.create(class_name="10", subject="Science", blueprint={}, created_by=self.ub)

    def test_blueprints_scoped_to_own_school(self):
        ids_a = set(_scoped_blueprints(self.ua).values_list("id", flat=True))
        self.assertIn(self.bp_a.id, ids_a)
        self.assertNotIn(self.bp_b.id, ids_a)   # School A cannot see School B's blueprint


class MCQHardeningTest(TestCase):
    """MCQs must have exactly 4 non-empty a/b/c/d options and a valid answer key."""

    def _opts(self, options, answer="a"):
        return sg._validate_mcq_options({"options": options, "answer": answer}, 1, "MCQ/standard")

    def test_valid_four_pass(self):
        self.assertEqual(self._opts({"a": "1", "b": "2", "c": "3", "d": "4"}), [])

    def test_three_options_flagged(self):
        self.assertTrue(any("EXACTLY 4" in e for e in self._opts({"a": "1", "b": "2", "c": "3"})))

    def test_five_options_flagged(self):
        self.assertTrue(any("EXACTLY 4" in e for e in self._opts({"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"})))

    def test_empty_option_flagged(self):
        self.assertTrue(any("EXACTLY 4" in e for e in self._opts({"a": "1", "b": "  ", "c": "3", "d": "4"})))

    def test_wrong_keys_flagged(self):
        self.assertTrue(any("keys must be" in e for e in self._opts({"a": "1", "b": "2", "c": "3", "e": "4"})))

    def test_missing_answer_flagged(self):
        self.assertTrue(any("answer" in e for e in self._opts({"a": "1", "b": "2", "c": "3", "d": "4"}, answer="")))

    def test_bad_answer_flagged(self):
        self.assertTrue(any("a/b/c/d" in e for e in self._opts({"a": "1", "b": "2", "c": "3", "d": "4"}, answer="z")))

    def test_missing_type_flagged(self):
        pattern = ExamPattern(name="mt", subject="Science", class_name="10", sections=[{
            "name": "A", "marks": 2, "questions_count": 2, "marks_per_question": 1, "question_types": ["MCQ"],
            "subsections": [{"name": "MCQ", "question_types": ["MCQ"], "marks": 2, "questions_count": 2, "marks_per_question": 1}],
        }])
        wo = sg.build_work_orders({s["name"]: s for s in pattern.sections}, pattern, {}, "M", "10", "Science", ["x"])[0]
        errs = sg._validate_by_subtype({"text": "q", "marks": 1}, 1, wo)   # no 'type'
        self.assertTrue(any("missing 'type'" in e for e in errs))


class InlineImageSalvageTest(TestCase):
    """Models sometimes write '(Image description: …)' inline instead of an image_prompt field,
    so no image was generated. The renderer must salvage it into a real image."""

    def test_extracts_neuron_description(self):
        t = ("(Image description: A simple diagram showing a neuron with labelled parts A, B, C. "
             "Part A is a branched structure, B is a long fibre, and C is a gap between two neurons.) "
             "Which label in the diagram shows the synapse?")
        clean, prompt = sg_gen._extract_inline_image(t)
        self.assertEqual(clean, "Which label in the diagram shows the synapse?")
        self.assertIn("neuron", prompt)

    def test_bracketed_and_midsentence(self):
        clean, prompt = sg_gen._extract_inline_image("[Image: bar chart of rainfall] Which city is wettest?")
        self.assertEqual(clean, "Which city is wettest?")
        self.assertIn("bar chart", prompt)

    def test_plain_question_untouched(self):
        t = "What is the chemical formula of water?"
        clean, prompt = sg_gen._extract_inline_image(t)
        self.assertEqual(clean, t)
        self.assertIsNone(prompt)

    def test_empty_marker_not_treated_as_image(self):
        clean, prompt = sg_gen._extract_inline_image("Observe the figure (figure) below.")
        self.assertIsNone(prompt)


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


class InconsistentCountReconcileTest(TestCase):
    """Pattern 353 (English Core, cls 6, 40m) shipped a 40-mark paper as 89 marks. Its sections
    carried a section-level questions_count that disagreed with their per-type breakdown:
    questions_count=10 for a section whose two subsections describe just 2 questions worth 5m
    each. The generator asked for 10×1m while the per-type validator demanded EXACTLY
    MCQ×1+OTHER×1 at 5m — impossible to satisfy both, so the section shipped partial and blew
    the marks total (a 10-mark section rendered as 38m). The work-order builder must treat the
    per-type breakdown as authoritative for the count and marks."""

    def _pattern(self):
        return ExamPattern(name="p353", subject="English Core", class_name="6", sections=[
            # Reading: plain-string types, genuinely 10×1m — must stay UNCHANGED (no breakdown).
            {"name": "Reading Skills", "marks": 10, "questions_count": 10,
             "marks_per_question": 1, "question_types": ["MCQ"]},
            # Writing: section CLAIMS 10 questions, but subsections describe 2 (5m each, uniform).
            {"name": "Writing Skills and Applied Grammar", "marks": 10, "questions_count": 10,
             "marks_per_question": 1, "question_types": ["Short Answer"], "subsections": [
                 _sub("MCQ", "MCQ", 5, 1, 5), _sub("Letter Writing", "Letter Writing", 5, 1, 5)]},
            # Literature: section CLAIMS 20 questions; subsections describe 3 (5+10+5) → mixed.
            {"name": "Language through Literature", "marks": 20, "questions_count": 20,
             "marks_per_question": 1, "question_types": ["Short Answer"], "subsections": [
                 _sub("Extract Based", "Extract Based", 5, 1, 5),
                 _sub("Short Answer", "Short Answer", 10, 1, 10),
                 _sub("Long Answer", "Long Answer", 5, 1, 5)]},
        ])

    def _wos(self):
        p = self._pattern()
        bp = {s["name"]: s for s in p.sections}
        return {wo.section_name: wo for wo in
                sg.build_work_orders(bp, p, {}, "Medium", "6", "English Core", ["Fables"])}

    def test_count_follows_per_type_breakdown_not_stale_field(self):
        wos = self._wos()
        # Reading: no per-type breakdown → declared count/marks stand.
        self.assertEqual(wos["Reading Skills"].questions_count, 10)
        self.assertEqual(wos["Reading Skills"].marks_per_question, 1)
        # Writing: 2 questions (not 10), 5m each, section total still 10, uniform marks.
        w = wos["Writing Skills and Applied Grammar"]
        self.assertEqual(w.questions_count, 2)
        self.assertEqual(w.marks, 10)
        self.assertEqual(w.marks_per_question, 5.0)
        self.assertFalse(w.mixed_marks)
        # Literature: 3 questions (not 20), section total 20, mixed 5/10/5 marks.
        lit = wos["Language through Literature"]
        self.assertEqual(lit.questions_count, 3)
        self.assertEqual(lit.marks, 20)
        self.assertTrue(lit.mixed_marks)

    def test_reconciled_work_order_has_no_self_conflicting_validation(self):
        # A submission that matches the reconciled typed counts must satisfy BOTH the count
        # check and the marks-total check — they used to contradict each other and fail forever.
        w = self._wos()["Writing Skills and Applied Grammar"]
        data = {"questions": [
            {"qnum": 1, "type": "MCQ", "subtype": "standard", "text": "Pick one.",
             "options": {"a": "1", "b": "2", "c": "3", "d": "4"}, "answer": "b",
             "answer_explanation": "b is right.", "marks": 5, "competency_type": "recall"},
            {"qnum": 2, "type": "Letter Writing", "subtype": "standard",
             "text": "Write a letter to your friend describing your school.",
             "answer_explanation": "Format + content points.", "marks": 5,
             "competency_type": "constructed"},
        ]}
        errs = sg.validate_section_output(data, w)
        joined = " ".join(errs)
        self.assertNotIn("Expected", joined, f"count conflict remains: {errs}")
        self.assertNotIn("Section marks total", joined, f"marks-total conflict remains: {errs}")
        self.assertNotIn("distribution wrong", joined, f"type conflict remains: {errs}")


class TrimOverfullSectionTest(TestCase):
    """A section that generates MORE questions than its blueprint must be trimmed back, or the
    paper's marks overshoot (the Biology 33/30, Physics 28/25 case). Mirror of [Refill]."""

    def _wo(self):
        # Biology from _compound_sections: caps mcq7, ar2, vsa3, sa2, cbq1, la1 = 16q / 30m.
        p = ExamPattern(name="ov", subject="Science", class_name="10",
                        sections=[_compound_sections()[0]])
        bp = {s["name"]: s for s in p.sections}
        return sg.build_work_orders(bp, p, {}, "Medium", "10", "Science", ["Life Processes"])[0]

    def test_trims_excess_of_a_capped_type(self):
        wo = self._wo()
        qs = ([{"type": "MCQ", "subtype": "standard", "marks": 1} for _ in range(7)]
              + [{"type": "MCQ", "subtype": "assertion_reason", "marks": 1} for _ in range(2)]
              + [{"type": "VSA", "marks": 2} for _ in range(3)]
              + [{"type": "SA", "marks": 3} for _ in range(3)]        # one too many (cap 2)
              + [{"type": "CBQ", "subtype": "source_based", "marks": 4}]
              + [{"type": "LA", "marks": 5}])
        for i, q in enumerate(qs, 1):
            q["qnum"] = i
        out = sg.trim_overfull_sections({"Biology": {"questions": qs}}, [wo])
        kept = out["Biology"]["questions"]
        self.assertEqual(len(kept), 16)                                  # 17 → 16
        self.assertEqual(len([q for q in kept if q["type"] == "SA"]), 2)  # capped at 2
        self.assertEqual(sum(q["marks"] for q in kept), 30)              # back to section budget

    def test_leaves_on_count_section_untouched(self):
        wo = self._wo()
        qs = ([{"type": "MCQ", "subtype": "standard", "marks": 1} for _ in range(7)]
              + [{"type": "MCQ", "subtype": "assertion_reason", "marks": 1} for _ in range(2)]
              + [{"type": "VSA", "marks": 2} for _ in range(3)]
              + [{"type": "SA", "marks": 3} for _ in range(2)]
              + [{"type": "CBQ", "subtype": "source_based", "marks": 4}]
              + [{"type": "LA", "marks": 5}])
        for i, q in enumerate(qs, 1):
            q["qnum"] = i
        out = sg.trim_overfull_sections({"Biology": {"questions": qs}}, [wo])
        self.assertEqual(len(out["Biology"]["questions"]), 16)
        self.assertNotIn("_trimmed_overfull", out["Biology"])


class ParseChapterListTest(TestCase):
    """The upload view accepts the 'chapters' field as a JSON array (what the form sends), a
    single string, or a repeated form field — all normalise to a de-duplicated name list."""

    def setUp(self):
        from api.views import _parse_chapter_list
        self.parse = _parse_chapter_list

    def test_json_array_string(self):
        self.assertEqual(self.parse('["Light", "Electricity"]'), ["Light", "Electricity"])

    def test_single_plain_string(self):
        self.assertEqual(self.parse("Light"), ["Light"])

    def test_python_list(self):
        self.assertEqual(self.parse(["Light", "Electricity"]), ["Light", "Electricity"])

    def test_dedupes_case_insensitively_preserving_order(self):
        self.assertEqual(self.parse('["Light", "light", "Sound"]'), ["Light", "Sound"])

    def test_empty_and_none(self):
        self.assertEqual(self.parse(None), [])
        self.assertEqual(self.parse(""), [])
        self.assertEqual(self.parse("[]"), [])

    def test_malformed_json_falls_back_to_literal(self):
        self.assertEqual(self.parse("[oops"), ["[oops"])


class _FakePage:
    def __init__(self, text):
        self._t = text
    def extract_text(self):
        return self._t


class _FakeReader:
    def __init__(self, text):
        self.pages = [_FakePage(text)]


class ChapterIngestTest(TestCase):
    """ingest_pdf stores each chunk ONCE and links it to every chapter via ChunkChapter — a note
    spanning multiple chapters is no longer duplicated per chapter (pgvector many-to-many)."""

    def _run_ingest(self, **kwargs):
        from unittest import mock
        from core import embeddings as emb
        unit = kwargs.pop("unit", "ignored")
        with mock.patch.object(emb, "PdfReader", lambda *_a, **_k: _FakeReader("x" * 1600)), \
             mock.patch.object(emb, "get_embeddings_batch",
                               side_effect=lambda chunks, provider: [[0.0] * 768 for _ in chunks]):
            return emb.ingest_pdf("10", "Physics", unit, "C:/fake.pdf", **kwargs)

    def test_multi_chapter_note_stored_once(self):
        from core.models import MaterialChunk, ChunkChapter
        n = self._run_ingest(units=["Light", "Electricity"], material_type="notes")
        # 1600 chars → 2 chunks, stored ONCE (not 4) even though linked to 2 chapters.
        self.assertEqual(n, 2)
        self.assertEqual(MaterialChunk.objects.count(), 2)
        self.assertEqual(set(ChunkChapter.objects.values_list("unit", flat=True)), {"light", "electricity"})
        self.assertEqual(ChunkChapter.objects.count(), 4)  # 2 chunks × 2 chapters (cheap links, not chunk copies)

    def test_single_chapter_links_once(self):
        from core.models import MaterialChunk, ChunkChapter
        self._run_ingest(unit="Light", material_type="textbook")
        self.assertEqual(MaterialChunk.objects.count(), 2)
        self.assertEqual(ChunkChapter.objects.count(), 2)
        self.assertTrue(all(c.embedding_local is not None for c in MaterialChunk.objects.all()))

    def test_note_and_textbook_coexist_under_same_chapter(self):
        from core.models import MaterialChunk, ChunkChapter
        self._run_ingest(unit="Light", material_type="textbook")
        self._run_ingest(units=["Light"], material_type="notes")
        self.assertEqual(MaterialChunk.objects.count(), 4)            # separate rows — no id collision
        self.assertEqual(ChunkChapter.objects.filter(unit="light").count(), 4)


class DeleteMaterialEmbeddingsTest(TestCase):
    """delete_material_embeddings removes only one material's chunks (cascading their chapter
    links), never a textbook chapter's chunks that share the same unit label."""

    def _chunk(self, material, unit):
        from core.models import MaterialChunk, ChunkChapter
        c = MaterialChunk.objects.create(material=material, class_name="10", subject="physics",
                                         content="x", chunk_index=0, provider="local")
        ChunkChapter.objects.create(chunk=c, unit=unit)
        return c

    def test_deletes_only_that_material(self):
        from core.models import Material, MaterialChunk, ChunkChapter
        from core import embeddings as emb
        note = Material.objects.create(class_name="10", subject="Physics", title="notes", type="notes", file="")
        book = Material.objects.create(class_name="10", subject="Physics", title="book", type="textbook", file="")
        self._chunk(note, "light"); self._chunk(note, "light"); self._chunk(book, "light")
        emb.delete_material_embeddings("10", "Physics", note.id)
        self.assertEqual(MaterialChunk.objects.filter(material=note).count(), 0)
        self.assertEqual(MaterialChunk.objects.filter(material=book).count(), 1)
        self.assertEqual(ChunkChapter.objects.count(), 1)            # deleted chunks' links cascaded away

    def test_noop_when_material_id_none(self):
        from core import embeddings as emb
        emb.delete_material_embeddings("10", "Physics", None)        # must not raise / delete nothing


class ChunkingTest(TestCase):
    """Structure-aware chunker: natural boundaries, size bound, overlap, tiny-tail merge."""

    def test_short_text_is_single_chunk(self):
        from core.embeddings import _chunk_text
        out = _chunk_text("A short paragraph about photosynthesis.")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], "A short paragraph about photosynthesis.")

    def test_empty_text(self):
        from core.embeddings import _chunk_text
        self.assertEqual(_chunk_text("   "), [])

    def test_respects_size_bound(self):
        from core.embeddings import _chunk_text
        text = ". ".join(f"Sentence number {i} explains an idea" for i in range(400))
        out = _chunk_text(text, size=500, overlap=60)
        self.assertGreater(len(out), 1)
        # No chunk grossly exceeds size (allow overlap + one boundary token of slack).
        self.assertTrue(all(len(c) <= 500 + 120 for _, c in out))

    def test_prefers_sentence_boundaries(self):
        from core.embeddings import _chunk_text
        text = " ".join(f"This is sentence {i}." for i in range(200))
        out = _chunk_text(text, size=300, overlap=40)
        # Most chunks should end at a sentence terminator, not mid-word.
        ends_clean = sum(1 for _, c in out if c.endswith("."))
        self.assertGreaterEqual(ends_clean, len(out) - 1)

    def test_overlap_carries_context(self):
        from core.embeddings import _chunk_text
        text = " ".join(f"word{i}" for i in range(400))
        out = [c for _, c in _chunk_text(text, size=300, overlap=60)]
        self.assertGreater(len(out), 1)
        # The tail of one chunk should reappear at the head of the next (context overlap).
        first_tail = out[0].split()[-1]
        self.assertIn(first_tail, out[1].split()[:8])

    def test_indices_are_sequential(self):
        from core.embeddings import _chunk_text
        text = ". ".join(f"Idea {i} is described here" for i in range(120))
        out = _chunk_text(text, size=400, overlap=50)
        self.assertEqual([i for i, _ in out], list(range(len(out))))


class PgvectorQueryTest(TestCase):
    """query() returns the Chroma-shaped dict, orders by cosine distance, and scopes to chapter."""

    def setUp(self):
        from core.models import Material
        # Chunks must belong to a material for the visibility join; a shared material is visible
        # to the default (school_id=None) query context.
        self.mat = Material.objects.create(class_name="10", subject="Physics", title="t",
                                           type="notes", file="", school=None, visibility="shared")

    def _chunk(self, content, vec, unit="light"):
        from core.models import MaterialChunk, ChunkChapter
        c = MaterialChunk.objects.create(material=self.mat, class_name="10", subject="physics",
                                         content=content, chunk_index=0, provider="local",
                                         embedding_local=vec)
        ChunkChapter.objects.create(chunk=c, unit=unit)
        return c

    def test_orders_by_similarity_and_shape(self):
        from unittest import mock
        from core import embeddings as emb
        near = [1.0] + [0.0] * 767
        far = [0.0] * 767 + [1.0]
        self._chunk("near-doc", near)
        self._chunk("far-doc", far)
        with mock.patch.object(emb, "get_embedding", return_value=near):
            res = emb.query("10", "Physics", "Light", "q", n_results=5)
        self.assertEqual(len(res["documents"]), 1)                   # list-of-one-list (Chroma shape)
        self.assertEqual(res["documents"][0], ["near-doc", "far-doc"])
        self.assertIn("embeddings", res)

    def test_chapter_scoping(self):
        from unittest import mock
        from core import embeddings as emb
        self._chunk("light-doc", [1.0] + [0.0] * 767, unit="light")
        self._chunk("sound-doc", [1.0] + [0.0] * 767, unit="sound")
        with mock.patch.object(emb, "get_embedding", return_value=[1.0] + [0.0] * 767):
            res = emb.query("10", "Physics", "Sound", "q", n_results=5)
        self.assertEqual(res["documents"][0], ["sound-doc"])


class MaterialVisibilityScopeTest(TestCase):
    """visibility_q (the single access rule): a school sees its own materials ∪ shared (only if
    granted) ∪ institutional (any school), and NEVER another school's private material."""

    def setUp(self):
        from core.models import School, Material
        self.A = School.objects.create(name="A", access_shared_vector_store=True)
        self.B = School.objects.create(name="B", access_shared_vector_store=False)
        mk = lambda **kw: Material.objects.create(class_name="10", subject="Physics",
                                                  title="t", type="notes", file="", **kw)
        self.shared = mk(school=None, visibility="shared")
        self.a_priv = mk(school=self.A, visibility="private")
        self.b_priv = mk(school=self.B, visibility="private")
        self.b_inst = mk(school=self.B, visibility="institutional")

    def _visible(self, school):
        from core.models import Material
        from core.access import visibility_q
        return set(Material.objects.filter(visibility_q(school)).values_list("id", flat=True))

    def test_school_with_shared_access(self):
        v = self._visible(self.A)
        self.assertEqual(v, {self.shared.id, self.a_priv.id, self.b_inst.id})
        self.assertNotIn(self.b_priv.id, v)                  # never another school's private

    def test_school_without_shared_access(self):
        v = self._visible(self.B)
        self.assertEqual(v, {self.b_priv.id, self.b_inst.id})
        self.assertNotIn(self.shared.id, v)                  # not granted shared store
        self.assertNotIn(self.a_priv.id, v)

    def test_superadmin_or_no_school(self):
        self.assertEqual(self._visible(None), {self.shared.id, self.b_inst.id})

    def test_flip_to_institutional_exposes_cross_school(self):
        self.assertNotIn(self.b_priv.id, self._visible(self.A))
        self.b_priv.visibility = "institutional"
        self.b_priv.save()
        self.assertIn(self.b_priv.id, self._visible(self.A))   # instant, no re-ingest


class ChunkVisibilityScopeTest(TestCase):
    """The retrieval layer (_scoped_chunks) enforces the same visibility rule via the chunk→material
    join, so generation can only pull context a school is allowed to see."""

    def setUp(self):
        from core.models import School, Material, MaterialChunk, ChunkChapter
        self.A = School.objects.create(name="A", access_shared_vector_store=True)
        self.B = School.objects.create(name="B", access_shared_vector_store=False)

        def mk(school, vis):
            m = Material.objects.create(class_name="10", subject="Physics", title="t",
                                        type="notes", file="", school=school, visibility=vis)
            c = MaterialChunk.objects.create(material=m, school=school, class_name="10",
                                             subject="physics", content="c", chunk_index=0,
                                             provider="local", embedding_local=[0.0] * 768)
            ChunkChapter.objects.create(chunk=c, unit="light")
            return c

        self.shared = mk(None, "shared")
        self.a_priv = mk(self.A, "private")
        self.b_priv = mk(self.B, "private")
        self.b_inst = mk(self.B, "institutional")

    def _scoped(self, school_id):
        from core.embeddings import _scoped_chunks
        return set(_scoped_chunks("10", "physics", "embedding_local", school_id)
                   .values_list("id", flat=True))

    def test_with_access(self):
        self.assertEqual(self._scoped(self.A.id), {self.shared.id, self.a_priv.id, self.b_inst.id})

    def test_without_access(self):
        self.assertEqual(self._scoped(self.B.id), {self.b_priv.id, self.b_inst.id})

    def test_superadmin(self):
        self.assertEqual(self._scoped(None), {self.shared.id, self.b_inst.id})


class CrossSchoolLinkTest(TestCase):
    """SchoolVectorLink: a viewer school reads a source school's private materials ONLY when a
    link exists, and only in the granted direction."""

    def setUp(self):
        from core.models import School, Material
        self.A = School.objects.create(name="A")
        self.B = School.objects.create(name="B")
        mk = lambda school: Material.objects.create(class_name="10", subject="Physics", title="t",
                                                    type="notes", file="", school=school, visibility="private")
        self.a_priv = mk(self.A)
        self.b_priv = mk(self.B)

    def _visible(self, school):
        from core.models import Material
        from core.access import visibility_q
        return set(Material.objects.filter(visibility_q(school)).values_list("id", flat=True))

    def test_no_link_is_isolated(self):
        self.assertEqual(self._visible(self.A), {self.a_priv.id})
        self.assertEqual(self._visible(self.B), {self.b_priv.id})

    def test_link_is_directional(self):
        from core.models import SchoolVectorLink
        SchoolVectorLink.objects.create(viewer=self.A, source=self.B)   # A → B only
        self.assertEqual(self._visible(self.A), {self.a_priv.id, self.b_priv.id})  # A sees B's
        self.assertEqual(self._visible(self.B), {self.b_priv.id})                  # B still can't see A's

    def test_mutual_link(self):
        from core.models import SchoolVectorLink
        SchoolVectorLink.objects.create(viewer=self.A, source=self.B)
        SchoolVectorLink.objects.create(viewer=self.B, source=self.A)
        self.assertIn(self.b_priv.id, self._visible(self.A))
        self.assertIn(self.a_priv.id, self._visible(self.B))

    def test_chunk_scope_respects_link(self):
        from core.models import MaterialChunk, ChunkChapter, SchoolVectorLink
        from core.embeddings import _scoped_chunks
        c = MaterialChunk.objects.create(material=self.b_priv, school=self.B, class_name="10",
                                         subject="physics", content="x", chunk_index=0,
                                         provider="local", embedding_local=[0.0] * 768)
        ChunkChapter.objects.create(chunk=c, unit="light")
        scoped = lambda: set(_scoped_chunks("10", "physics", "embedding_local", self.A.id).values_list("id", flat=True))
        self.assertNotIn(c.id, scoped())                                # not linked → invisible
        SchoolVectorLink.objects.create(viewer=self.A, source=self.B)
        self.assertIn(c.id, scoped())                                   # linked → visible

    def test_no_self_link_allowed(self):
        from core.models import SchoolVectorLink
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SchoolVectorLink.objects.create(viewer=self.A, source=self.A)


# ─────────────────────────────────────────────
# Per-question structure (question_slots) — docs/PER_QUESTION_STRUCTURE.md
# ─────────────────────────────────────────────

from core import pattern_structure as psx
from core.tasks import _fill_section_counts


def _slot_sections():
    """Compact PT-1-style pattern: a uniform Grammar section with per-slot topics
    (incl. the teacher's real 9×1-vs-7 marks conflict) and a mixed Literature
    section with an extract (sub-parts), an open-choice group and internal choice."""
    return [
        {"id": "SEC_C", "name": "Grammar", "marks": 7, "question_slots": [
            {"qnum": 1, "type": "mcq", "topic": "Homophones", "format": "Homophones MCQ", "marks": 1},
            {"qnum": 2, "type": "fill_blank", "topic": "Conjunctions", "marks": 1},
            {"qnum": 3, "type": "fill_blank", "topic": "Conjunctions", "marks": 1},
            {"qnum": 4, "type": "punctuation", "topic": "Contracted words", "marks": 1},
            {"qnum": 5, "type": "mcq", "topic": "Present progressive", "marks": 1},
            {"qnum": 6, "type": "rewrite", "topic": "Punctuation", "marks": 1},
            {"qnum": 7, "type": "error_correction", "topic": "Past tense", "marks": 1},
            {"qnum": 8, "type": "mcq", "topic": "Past progressive", "marks": 1},
            {"qnum": 9, "type": "error_correction", "topic": "Past perfect", "marks": 1},
        ]},
        {"id": "SEC_D", "name": "Literature", "marks": 19, "question_slots": [
            {"qnum": 10, "type": "extract", "marks": 5, "source": "textbook",
             "parts": [{"label": "A", "type": "mcq", "marks": 1},
                       {"label": "B", "type": "mcq", "marks": 1},
                       {"label": "C", "type": "sa", "marks": 1},
                       {"label": "D", "type": "sa", "marks": 1},
                       {"label": "E", "type": "sa", "marks": 1}]},
            {"qnum": 11, "type": "sa", "marks": 10, "choice": "open", "attempt": 5,
             "parts": [{"label": l, "type": "sa", "marks": 2} for l in "ABCDEF"]},
            {"qnum": 12, "type": "la", "marks": 4, "choice": "internal",
             "alternatives": ["critical from prose/poem", "direct from supplementary reader"]},
        ]},
    ]


class SlotStructureValidatorTest(TestCase):
    def test_normalize_coerces_and_canonicalises(self):
        secs = [{"name": "A", "question_slots": [
            {"qnum": "3", "type": "Fill in the blanks", "marks": "1", "choice": None},
        ]}]
        psx.normalize_slots(secs)
        s = secs[0]["question_slots"][0]
        self.assertEqual(s["qnum"], 3)
        self.assertEqual(s["type"], "fill_blank")
        self.assertEqual(s["marks"], 1)
        self.assertEqual(s["choice"], "none")

    def test_flags_teacher_marks_conflict(self):
        secs = psx.normalize_slots(_slot_sections())
        errors = psx.validate_pattern_structure(secs, declared_total=26)
        msgs = " | ".join(e["msg"] for e in errors)
        self.assertIn("slot marks sum to 9 but the section declares 7", msgs)
        # paper sum uses slot sums (9 + 19 = 28) vs the declared 26
        self.assertIn("paper marks sum to 28", msgs)

    def test_clean_pattern_validates(self):
        secs = psx.normalize_slots(_slot_sections())
        secs[0]["marks"] = 9
        self.assertEqual(psx.validate_pattern_structure(secs, declared_total=28), [])

    def test_qnum_duplicates_and_gaps(self):
        secs = [{"name": "A", "marks": 2, "question_slots": [
            {"qnum": 1, "type": "mcq", "marks": 1},
            {"qnum": 3, "type": "mcq", "marks": 1},
        ]}]
        msgs = " | ".join(e["msg"] for e in psx.validate_pattern_structure(secs))
        self.assertIn("no gaps", msgs)
        secs[0]["question_slots"][1]["qnum"] = 1
        msgs = " | ".join(e["msg"] for e in psx.validate_pattern_structure(secs))
        self.assertIn("ascending", msgs)
        self.assertIn("duplicate", msgs)

    def test_open_choice_rules(self):
        base = {"qnum": 1, "type": "sa", "marks": 4, "choice": "open",
                "parts": [{"label": "A", "marks": 2}, {"label": "B", "marks": 2}]}
        # attempt missing
        errs = psx.validate_pattern_structure([{"name": "A", "question_slots": [dict(base)]}])
        self.assertTrue(any("requires 'attempt'" in e["msg"] for e in errs))
        # attempt == len(parts) → not a choice
        errs = psx.validate_pattern_structure([{"name": "A", "question_slots": [dict(base, attempt=2)]}])
        self.assertTrue(any("less than the number of parts" in e["msg"] for e in errs))
        # valid: attempt 2 of 3 → 2×2 == marks 4
        ok = dict(base, attempt=2, parts=[{"label": c, "marks": 2} for c in "ABC"])
        self.assertEqual(psx.validate_pattern_structure([{"name": "A", "question_slots": [ok]}]), [])

    def test_parts_sum_rule(self):
        secs = [{"name": "A", "question_slots": [
            {"qnum": 1, "type": "extract", "marks": 5,
             "parts": [{"label": "A", "marks": 1}, {"label": "B", "marks": 1}]},
        ]}]
        msgs = " | ".join(e["msg"] for e in psx.validate_pattern_structure(secs))
        self.assertIn("parts marks sum to 2 but slot marks is 5", msgs)


class SlotAggregateDerivationTest(TestCase):
    def test_derive_uniform_and_mixed(self):
        secs = psx.normalize_slots(_slot_sections())
        secs[0]["marks_per_question"] = [1] * 9        # stale mpq-list must be replaced
        psx.derive_aggregates_from_slots(secs)
        g, l = secs
        self.assertEqual((g["questions_count"], g["marks"], g["marks_per_question"]), (9, 9, 1))
        self.assertEqual((l["questions_count"], l["marks"]), (3, 19))
        self.assertNotIn("marks_per_question", l)       # mixed marks → no scalar mpq
        # typed dicts with real qnum ranges, contiguous same-(type,marks) runs merged
        self.assertEqual(g["question_types"][1],
                         {"type": "Fill in the blank", "count": 2, "marks_each": 1, "range": "Q2-Q3"})
        self.assertTrue(all(isinstance(qt, dict) for qt in l["question_types"]))

    def test_model_totals_prefer_slots(self):
        p = ExamPattern(name="slots", sections=psx.normalize_slots(_slot_sections()))
        self.assertEqual(p.get_total_marks(), 28)       # 9 + 19 from slots (not section 7)
        self.assertEqual(p.get_total_questions(), 12)

    def test_fill_section_counts_skips_slot_sections(self):
        secs = psx.normalize_slots(_slot_sections())
        psx.derive_aggregates_from_slots(secs)
        out = _fill_section_counts(secs)
        self.assertNotIn("marks_per_question", out[1])  # no bogus avg re-invented for mixed


class SlotTypeCategoryTest(TestCase):
    def test_slot_types_never_other(self):
        for t, cat in psx.SLOT_TYPE_CATEGORY.items():
            self.assertEqual(sg._type_category(t), cat, t)

    def test_free_text_spellings(self):
        self.assertEqual(sg._type_category("Fill in the blanks"), "vsa")
        self.assertEqual(sg._type_category("Error correction"), "vsa")
        self.assertEqual(sg._type_category("Rewrite sentences"), "vsa")
        self.assertEqual(sg._type_category("Descriptive Paragraph"), "la")
        self.assertEqual(sg._type_category("Story Writing"), "la")

    def test_legacy_classifications_unchanged(self):
        self.assertEqual(sg._type_category("MCQ"), "mcq")
        self.assertEqual(sg._type_category("Short Answer"), "sa")
        self.assertEqual(sg._type_category("Long Answer"), "la")
        self.assertEqual(sg._type_category("Source-Based/CBQ"), "cbq")
        self.assertEqual(sg._type_category("Map work"), "map")


class SlotWorkOrderTest(TestCase):
    def _wos(self):
        secs = psx.normalize_slots(_slot_sections())
        secs[0]["marks"] = 9
        psx.derive_aggregates_from_slots(secs)
        pattern = ExamPattern(name="p", sections=secs)
        blueprint = sg_gen.pattern_sections_to_blueprint_dict(pattern)
        return sg.build_work_orders(blueprint, pattern, {}, "Medium", "6", "English", ["Ch1"])

    def test_counts_marks_and_slots(self):
        g, l = self._wos()
        self.assertEqual((g.questions_count, g.marks, g.marks_per_question, g.mixed_marks),
                         (9, 9, 1.0, False))
        self.assertEqual((l.questions_count, l.marks, l.mixed_marks), (3, 19, True))
        self.assertEqual(len(g.slots), 9)
        self.assertEqual(len(l.slots), 3)
        self.assertEqual(l.subsections, [])

    def test_parts_slots_count_as_cbq(self):
        _, l = self._wos()
        cats = [sg._fine_category(qt["type"]) for qt in l.question_types]
        self.assertEqual(cats, ["cbq", "cbq", "la"])    # extract + open-choice group + LA

    def test_slot_prompt_block(self):
        g, l = self._wos()
        pg, pl = sg.build_section_prompt(g), sg.build_section_prompt(l)
        self.assertIn("PER-QUESTION SPECIFICATION", pg)
        self.assertIn("Homophones", pg)                          # topics reach the LLM
        self.assertNotIn("QUESTION-POSITION BLUEPRINT", pl)      # superseded for slot sections
        self.assertIn("INTERNAL CHOICE", pl)
        self.assertIn("attempt any 5", pl.lower())
        self.assertIn('"source_text"', pl)
        # No blanket LA OR-rule: only slot-flagged questions get or_alternative
        self.assertIn('Do NOT add "or_alternative" to any other question', pl)

    def test_or_gating_in_validation(self):
        _, l = self._wos()
        qs = [
            {"type": "CBQ", "subtype": "source_based", "marks": 5, "text": "Read the extract " * 10,
             "source_text": "x" * 100, "competency_type": "application",
             "sub_questions": [{"text": "a", "marks": 1}] * 5},
            {"type": "CBQ", "subtype": "standard", "marks": 10, "text": "Attempt any 5 " * 5,
             "competency_type": "constructed",
             "sub_questions": [{"text": "b", "marks": 2}] * 6},   # 12 provided vs 10 attempted
            {"type": "LA", "marks": 4, "text": "Discuss the theme of the poem in detail.",
             "competency_type": "constructed", "answer_explanation": "points",
             "or_alternative": "Describe the character of the mongoose."},
        ]
        errors = sg.validate_section_output({"questions": qs}, l)
        self.assertEqual(errors, [])
        # internal-choice slot without or_alternative must fail
        del qs[2]["or_alternative"]
        errors = sg.validate_section_output({"questions": qs}, l)
        self.assertTrue(any("or_alternative" in e for e in errors))
        # open-choice slot: a sum that matches NEITHER attempted nor provided fails
        qs[2]["or_alternative"] = "alt"
        qs[1]["sub_questions"] = [{"text": "b", "marks": 2}] * 4
        errors = sg.validate_section_output({"questions": qs}, l)
        self.assertTrue(any("sub_question marks sum" in e for e in errors))


class SlotRenderTest(TestCase):
    def test_regroup_skips_slot_sections(self):
        sec_info = {"question_slots": [{"qnum": 1}], "subsections": [
            {"name": "SA", "question_types": ["SA"], "marks": 10, "questions_count": 5,
             "marks_per_question": 2},
        ]}
        qs = [{"type": "CBQ", "marks": 5}, {"type": "SA", "marks": 10}, {"type": "LA", "marks": 4}]
        groups = sg_gen._regroup_section(list(qs), sec_info)
        self.assertEqual(groups, [(None, qs)])           # authored order, marks untouched

    def test_blueprint_dict_passes_slots(self):
        secs = psx.normalize_slots(_slot_sections())
        bp = sg_gen.pattern_sections_to_blueprint_dict(ExamPattern(name="p", sections=secs))
        self.assertEqual(len(bp["Grammar"]["question_slots"]), 9)


class SlotRepairGuardTest(TestCase):
    """The repair round must never be accepted when it deletes question slots or
    lowers slot marks to force the teacher's declared totals to match (observed in
    production: Q19/Q20 dropped and a 4m LA cut to 3m). repair_preserves_slots is
    the deterministic guard in generate_pattern_task."""

    def _orig(self):
        return psx.normalize_slots(_slot_sections())

    def test_rejects_deleted_slots(self):
        import copy
        orig = self._orig()
        mutilated = copy.deepcopy(orig)
        mutilated[0]["question_slots"] = mutilated[0]["question_slots"][:7]  # drop Q8, Q9
        self.assertFalse(psx.repair_preserves_slots(orig, mutilated))

    def test_rejects_lowered_slot_marks(self):
        import copy
        orig = self._orig()
        devalued = copy.deepcopy(orig)
        devalued[1]["question_slots"][2]["marks"] = 3     # LA 4m -> 3m
        self.assertFalse(psx.repair_preserves_slots(orig, devalued))

    def test_accepts_section_marks_correction(self):
        import copy
        orig = self._orig()
        good = copy.deepcopy(orig)
        good[0]["marks"] = 9                              # totals fixed, slots untouched
        self.assertTrue(psx.repair_preserves_slots(orig, good))

    def test_accepts_added_slots_and_filled_marks(self):
        import copy
        orig = self._orig()
        orig[0]["question_slots"][0]["marks"] = 0         # pass 1 left it blank
        richer = copy.deepcopy(orig)
        richer[0]["question_slots"][0]["marks"] = 1       # repair filled it in
        richer[1]["question_slots"].append({"qnum": 13, "type": "sa", "marks": 2})
        self.assertTrue(psx.repair_preserves_slots(orig, richer))


class SlotEditRederiveTest(TestCase):
    """PUT /api/patterns/{id}/ with edited slots must re-derive the aggregates and
    refresh structure warnings server-side (ExamPatternViewSet.perform_update) —
    the frontend slot editor sends slots only, never recomputed totals."""

    def test_put_rederives_aggregates_and_warnings(self):
        import copy
        from rest_framework.test import APIClient
        user = User.objects.create_user("slotedit", "s@x.com", "pw")
        secs = psx.normalize_slots(_slot_sections())
        secs[0]["marks"] = 9
        psx.derive_aggregates_from_slots(secs)
        p = ExamPattern.objects.create(name="se", sections=secs, created_by=user)

        api = APIClient()
        api.force_authenticate(user)
        edited = copy.deepcopy(p.sections)
        edited[0]["question_slots"][0]["marks"] = 2      # Grammar Q1: 1m -> 2m
        r = api.put(f"/api/patterns/{p.id}/", {
            "name": "se", "class_name": "6", "subject": "English",
            "description": "", "ai_prompt": "", "sections": edited,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        p.refresh_from_db()
        g = p.sections[0]
        self.assertEqual(g["marks"], 10)                  # re-derived from edited slots
        self.assertEqual(g["questions_count"], 9)
        self.assertNotIn("marks_per_question", g)         # now mixed (2m + 1m×8)
        self.assertEqual(p.total_marks, 29)               # 10 + 19, recomputed
        # slot sum (10) no longer matches the stale section 'marks' we sent (9)?
        # No — derive overwrote it; but the section-marks warning must NOT appear:
        self.assertFalse(any("_structure_warnings" in s and
                             any("declares" in w for w in s["_structure_warnings"])
                             for s in p.sections))

