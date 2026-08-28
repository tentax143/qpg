// Shared rules for describing and ordering an ExamPattern in the UI.

// Only the OFFICIAL sample papers are class-banded. CBSE publishes one paper per subject per
// stage and schools work towards it across the stage, so the Class 10 English paper is the model
// for classes 1-10 and the Class 12 one for 11-12 — the band lives in `class_min`/`class_max`.
//
// A pattern a teacher imported from their own PDF (`pattern_source === 'imported'`) is NOT banded:
// they uploaded it for one class and it should say so. Treating those as "any class" was wrong and
// is what made a freshly imported Class 10 paper claim it served every class.
export function isOfficialSamplePaper(pattern) {
  return Boolean(pattern) && pattern.pattern_source === 'cbse_sqp';
}

/** True when this pattern's structure is meant for `className`. Mirrors ExamPattern.serves_class. */
export function servesClass(pattern, className) {
  const n = parseInt(String(className || '').split('-')[0], 10);
  if (!Number.isFinite(n)) return false;
  if (pattern.class_min && pattern.class_max) {
    return n >= pattern.class_min && n <= pattern.class_max;
  }
  return parseInt(String(pattern.class_name || '').split('-')[0], 10) === n;
}

// Subjects that are the same thing under different names across stages and streams. Without this,
// a Class 6 "English" teacher would not match "English Language & Literature" — the actual name of
// the paper their syllabus builds towards — and would see no sample paper at all.
const SUBJECT_FAMILIES = {
  english: [
    'english', 'english core', 'english elective',
    'english language & literature', 'english language and literature',
  ],
  mathematics: [
    'maths', 'mathematics', 'mathematics standard', 'mathematics basic', 'applied mathematics',
  ],
};

const FAMILY_BY_SUBJECT = Object.entries(SUBJECT_FAMILIES).reduce((acc, [family, names]) => {
  names.forEach((n) => { acc[n] = family; });
  return acc;
}, {});

/** Normalise a subject to its family, so "English Core" and "English" compare equal.
 *  Subjects with no family (Physics, Science, History…) are their own — deliberately: a Class 11
 *  Physics teacher must not be handed the combined Class 10 Science paper. */
export function subjectFamily(subject) {
  const key = String(subject || '').trim().toLowerCase().replace(/\s+/g, ' ');
  return FAMILY_BY_SUBJECT[key] || key;
}

export function sameSubject(a, b) {
  const fa = subjectFamily(a);
  return Boolean(fa) && fa === subjectFamily(b);
}

/** Short scope line: "Classes 1-10 · English" for an official paper, "Class 10 · Biology" else. */
export function patternScope(pattern) {
  if (!pattern) return '';
  const cls = pattern.class_label
    || (isOfficialSamplePaper(pattern) && pattern.class_min && pattern.class_max
      ? `Classes ${pattern.class_min}-${pattern.class_max}`
      : `Class ${pattern.class_name}`);
  return [cls, pattern.subject].filter(Boolean).join(' · ');
}

// ─── Ordering in the generate-page picker ────────────────────────────────────────────
//
// Class and subject are chosen before this list opens, so it is ranked against both:
//
//   0  the official sample paper for this subject that covers this class  <- what they want
//   1  a pattern for this subject AND this class
//   2  a pattern for this subject, another class
//   3  the official paper for this subject from the OTHER stage
//   4  an official paper covering this class, another subject
//   5  an official paper from the other stage, another subject
//   6  another subject, right class
//   7  everything else
//
// 4 and 5 are split deliberately. Class is picked before subject on the generate page, so there
// is a window where className is set and subject is not — and without the split every official
// paper landed in one bucket and sorted alphabetically, putting Accountancy (11-12) above Science
// (1-10) for a Class 10 teacher. The papers that actually cover the chosen class come first.
//
// Subject still outranks band: a Class 10 Biology teacher wants their own Biology pattern before
// the Class 10 Science paper, however well-banded the latter is.
//
// Ties break on name so the order is stable between renders rather than jumping around.
export function rankPattern(pattern, { subject, className } = {}) {
  const subjectMatch = sameSubject(pattern.subject, subject);
  const classMatch = Boolean(className) && pattern.class_name === className;
  const official = isOfficialSamplePaper(pattern);
  const inBand = servesClass(pattern, className);

  if (official && subjectMatch && inBand) return 0;
  if (subjectMatch && classMatch) return 1;
  if (subjectMatch && !official) return 2;
  if (official && subjectMatch) return 3;
  if (official && inBand) return 4;
  if (official) return 5;
  if (classMatch) return 6;
  return 7;
}

/** Sort a copy of `patterns` into picker order. Does not mutate the input. */
export function sortPatternsForPicker(patterns, selection) {
  return [...patterns].sort((a, b) => {
    const diff = rankPattern(a, selection) - rankPattern(b, selection);
    return diff !== 0 ? diff : String(a.name || '').localeCompare(String(b.name || ''));
  });
}

// ─── Rendering a slot-authored pattern as editable text ──────────────────────────────
//
// The official sample papers are stored per printed question (`question_slots`), which is what
// makes a generated paper a faithful replica. But the Create Pattern page's AI box takes plain
// text a teacher can edit, and the old renderer only understood the legacy aggregate shape — a
// slot-authored pattern came out as empty section headings.
//
// The output is written to be read BOTH ways: a teacher edits it in the textarea, and the pattern
// generator parses it back (`api/ai_service.generate_pattern_via_api`). So the phrasing follows
// what the slot schema prompt already expects — "Q1-12: MCQ — 1 mark each", ranges expanded per
// question, choices and sub-parts spelled out.

const SLOT_TYPE_LABELS = {
  mcq: 'MCQ', ar: 'Assertion-Reason', fill_blank: 'Fill in the blank', true_false: 'True/False',
  matching: 'Matching', one_word: 'One-word answer', error_correction: 'Error correction',
  rewrite: 'Rewrite the sentence', punctuation: 'Punctuation', vsa: 'Very Short Answer',
  sa: 'Short Answer', la: 'Long Answer', writing: 'Writing', cbq: 'Case-Based',
  extract: 'Extract-Based', map: 'Map-Based',
};

const slotLabel = (t) => SLOT_TYPE_LABELS[t] || t || 'Question';
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** A slot is only safe to fold into a range if it carries nothing question-specific. */
function isPlainSlot(slot) {
  return !slot.parts?.length && !slot.topic && !slot.format
    && !slot.condition && (!slot.choice || slot.choice === 'none');
}

function describeSlot(slot) {
  const bits = [`${slotLabel(slot.type)} — ${plural(slot.marks, 'mark')}`];
  if (slot.topic) bits.push(`topic: ${slot.topic}`);
  if (slot.format) bits.push(slot.format);
  if (slot.source === 'unseen') bits.push('unseen passage');
  if (slot.source === 'general') bits.push('general knowledge, not from the textbook');
  if (slot.choice === 'internal') bits.push('internal choice (OR)');
  if (slot.choice === 'open' && slot.attempt) {
    bits.push(`attempt any ${slot.attempt} of ${slot.parts?.length ?? '?'} parts`);
  }
  if (slot.parts?.length) {
    bits.push('parts: ' + slot.parts
      .map((p) => `${p.label || '?'} ${slotLabel(p.type)} ${p.marks}m`).join(', '));
  }
  if (slot.condition) bits.push(slot.condition);
  return bits.join(' | ');
}

/** Render one slot-authored pattern as the editable text the AI box starts from. */
export function slotPatternToText(pattern, { subject, className, examName } = {}) {
  const lines = [
    `${String(subject || pattern.subject || '').toUpperCase()} — CLASS ${className || pattern.class_name} — ${String(examName || pattern.name || '').toUpperCase()}`,
    `Total Marks: ${pattern.total_marks} | Questions: ${pattern.total_questions}`,
  ];
  if (isOfficialSamplePaper(pattern)) {
    lines.push(`Based on the official CBSE sample paper (${patternScope(pattern)}).`);
  }
  lines.push('');

  for (const section of pattern.sections || []) {
    const slots = (section.question_slots || []).filter(Boolean);
    lines.push(`${section.name || 'Section'} — ${plural(section.marks ?? 0, 'mark')}`);

    for (const instruction of (section.instructions || [])) lines.push(`  ${instruction}`);
    if (section.passage_instruction) lines.push(`  ${section.passage_instruction}`);
    if (section.extract_instruction) lines.push(`  ${section.extract_instruction}`);

    // Fold consecutive identical questions into "Q1-12: MCQ — 1 mark each" so a 38-question
    // paper is a dozen readable lines rather than 38 near-identical ones. Anything with a topic,
    // choice or sub-parts is printed on its own, because that detail is what a teacher edits.
    let i = 0;
    while (i < slots.length) {
      const slot = slots[i];
      if (!isPlainSlot(slot)) {
        lines.push(`  Q${slot.qnum}: ${describeSlot(slot)}`);
        i += 1;
        continue;
      }
      let j = i;
      while (j + 1 < slots.length && isPlainSlot(slots[j + 1])
             && slots[j + 1].type === slot.type && slots[j + 1].marks === slot.marks) {
        j += 1;
      }
      const range = i === j ? `Q${slot.qnum}` : `Q${slot.qnum}-${slots[j].qnum}`;
      const each = i === j ? plural(slot.marks, 'mark') : `${plural(slot.marks, 'mark')} each`;
      lines.push(`  ${range}: ${slotLabel(slot.type)} — ${each}`);
      i = j + 1;
    }

    const limits = Object.entries(section.constraints || {})
      .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
    if (limits.length) lines.push(`  (${limits.join('; ')})`);
    lines.push('');
  }

  lines.push('--- Edit the sections above as needed, then Generate. You can change question');
  lines.push('--- counts, marks and types, or add conditions like:');
  lines.push('--- "Section A: 4 questions must be Assertion-Reason, 2 questions diagram-based"');
  return lines.join('\n');
}

/** True when this pattern stores its questions individually (and so can be rendered above). */
export function hasQuestionSlots(pattern) {
  return Boolean(pattern?.sections?.some((s) => s?.question_slots?.length));
}

/** The muted second column in the picker — what this pattern is for, and how big it is. */
export function patternOptionMeta(pattern) {
  if (!pattern) return '';
  const size = pattern.total_marks ? `${pattern.total_marks}M` : '';
  return [patternScope(pattern), size].filter(Boolean).join(' · ');
}
