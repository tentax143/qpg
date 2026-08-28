'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Save, Layers, BookOpen, Info, AlertCircle, CheckCircle2,
  Wand2, RefreshCw, GraduationCap, Hash,
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';
import {
  sortPatternsForPicker, patternOptionMeta, isOfficialSamplePaper, sameSubject,
} from '@/lib/patterns';

// A blueprint answers "where does each question come from". The structure — how many questions,
// what type, what marks — is the PATTERN's job and is read-only here. Keeping that split visible
// in the UI is the whole point: the previous blueprint pages let teachers re-declare the structure,
// which is why nobody could tell the two concepts apart.

const NO_UNIT = '';

export default function BuildBlueprintPage() {
  const router = useRouter();

  const [patterns, setPatterns] = useState([]);
  const [patternId, setPatternId] = useState('');
  const [scaffold, setScaffold] = useState(null);
  const [name, setName] = useState('');
  const [blueprintId, setBlueprintId] = useState(null);   // set when editing an existing one

  // The class and subject whose MATERIAL the units come from. Usually the pattern's own, but the
  // official sample papers cover a whole stage (Classes 1-10 / 11-12) and carry the source class,
  // so a Class 6 teacher planning the Classes 1-10 paper has to say which class they mean —
  // otherwise the builder offered them Class 10 chapters and saved a Class 10 blueprint.
  const [cls, setCls] = useState('');
  const [subj, setSubj] = useState('');
  const [subjects, setSubjects] = useState([]);

  // { [sectionId]: { questions: {qnum: unit}, units: [unit] } }
  const [assign, setAssign] = useState({});

  const [loadingPatterns, setLoadingPatterns] = useState(true);
  const [loadingScaffold, setLoadingScaffold] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Deep links: ?pattern=<id> preselects, ?id=<blueprintId> edits an existing plan.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = q.get('pattern');
    const b = q.get('id');
    if (p) setPatternId(p);
    if (b) setBlueprintId(b);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        // include_official: the official CBSE sample papers are excluded from /patterns/ by
        // default (they would bury a school's own handful of rows). Without them here, the one
        // pattern most teachers now generate from could not be planned at all — which is why
        // the generate page's blueprint dropdown came up empty.
        const res = await apiClient.get('/patterns/?page_size=200&include_official=1');
        const rows = res.data?.results || (Array.isArray(res.data) ? res.data : []);
        setPatterns(rows);
      } catch {
        setError('Could not load your patterns.');
      } finally {
        setLoadingPatterns(false);
      }
    })();
  }, []);

  // Load an existing blueprint being edited, then let the scaffold effect fill in the structure.
  useEffect(() => {
    if (!blueprintId) return;
    (async () => {
      try {
        const res = await apiClient.get(`/blueprints/${blueprintId}/`);
        const bp = res.data;
        setName(bp.name || '');
        if (bp.pattern_id) setPatternId(String(bp.pattern_id));
        if (bp.class_name) setCls(String(bp.class_name));
        if (bp.subject) setSubj(bp.subject);
        const next = {};
        for (const entry of (bp.unit_map?.sections || [])) {
          if (!entry?.section_id) continue;
          next[entry.section_id] = {
            questions: { ...(entry.questions || {}) },
            units: [...(entry.units || [])],
          };
        }
        setAssign(next);
      } catch {
        setError('Could not load that blueprint.');
      }
    })();
  }, [blueprintId]);

  const loadScaffold = useCallback(async (id, forClass, forSubject) => {
    setLoadingScaffold(true);
    setError(null);
    try {
      // class_name/subject decide which material's units come back — the pattern's structure is
      // the same either way.
      const qs = new URLSearchParams();
      if (forClass) qs.set('class_name', forClass);
      if (forSubject) qs.set('subject', forSubject);
      const res = await apiClient.get(
        `/patterns/${id}/blueprint-scaffold/${qs.toString() ? `?${qs}` : ''}`);
      setScaffold(res.data);
    } catch {
      setError('Could not load that pattern’s questions.');
      setScaffold(null);
    } finally {
      setLoadingScaffold(false);
    }
  }, []);

  useEffect(() => {
    if (patternId) loadScaffold(patternId, cls, subj);
    else setScaffold(null);
  }, [patternId, cls, subj, loadScaffold]);

  const selectedPattern = useMemo(
    () => patterns.find(p => String(p.id) === String(patternId)) || null,
    [patterns, patternId]);

  // Default the class and subject from the pattern the moment it is chosen. A banded sample paper
  // has no single class, so that one is left for the teacher to pick.
  useEffect(() => {
    if (!selectedPattern || blueprintId) return;
    const { class_min: lo, class_max: hi } = selectedPattern;
    if (lo && hi) setCls(lo !== hi ? '' : String(lo));
    else setCls(String(selectedPattern.class_name || ''));
    setSubj(selectedPattern.subject || '');
  }, [selectedPattern, blueprintId]);

  // Subjects that actually have material for the chosen class. The pattern's own name is kept as
  // an option even when nothing is uploaded under it, so the selection is never silently changed.
  useEffect(() => {
    if (!cls) { setSubjects([]); return; }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get(
          `/get_subjects_for_class/?class_name=${encodeURIComponent(cls)}`);
        if (!cancelled) setSubjects(res.data?.subjects || []);
      } catch {
        if (!cancelled) setSubjects([]);
      }
    })();
    return () => { cancelled = true; };
  }, [cls]);

  // A sample paper is titled with the name CBSE prints on it — "English Language & Literature",
  // "Mathematics Standard" — while the material is filed under the timetable name. Left as-is the
  // builder found no units and told the teacher to upload material they had already uploaded, so
  // fall back to the same-family subject that DOES have material. Never while editing: the saved
  // blueprint's own subject is the teacher's answer and must not be quietly rewritten.
  useEffect(() => {
    if (blueprintId || !subj || !subjects.length) return;
    if (subjects.some(x => x.toLowerCase() === subj.toLowerCase())) return;
    const family = subjects.find(x => sameSubject(x, subj));
    if (family) setSubj(family);
  }, [subjects, subj, blueprintId]);

  const patternOptions = useMemo(
    () => sortPatternsForPicker(patterns, { subject: subj, className: cls }).map(p => ({
      value: String(p.id),
      label: p.name,
      meta: patternOptionMeta(p),
      ...(isOfficialSamplePaper(p) ? { badge: 'SQP' } : {}),
    })), [patterns, subj, cls]);

  const classOptions = useMemo(() => {
    const { class_min: lo, class_max: hi, class_name: cn } = selectedPattern || {};
    if (lo && hi && hi >= lo) {
      return Array.from({ length: hi - lo + 1 }, (_, i) => ({
        value: String(lo + i), label: `Class ${lo + i}`,
      }));
    }
    return cn ? [{ value: String(cn), label: `Class ${cn}` }] : [];
  }, [selectedPattern]);

  const subjectOptions = useMemo(() => {
    const seen = new Set();
    const out = [];
    for (const nameOrSubject of [...(subj ? [subj] : []), ...subjects]) {
      const key = nameOrSubject.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ value: nameOrSubject, label: nameOrSubject });
    }
    return out;
  }, [subj, subjects]);

  // Memoised so the `|| []` fallback isn't a fresh array on every render, which would make
  // unitOptions recompute (and re-render every one of a 38-question paper's dropdowns) each time.
  const units = useMemo(() => scaffold?.units || [], [scaffold]);

  // Every unit the saved map already pins. A unit can be pinned and yet absent from `units` — the
  // material was deleted or its unit renamed after the blueprint was written. Dropping those from
  // the dropdown made the question render as "Auto" while the pin was still saved, so the page
  // showed one plan and generation applied another.
  const pinnedUnits = useMemo(() => {
    const out = new Set();
    for (const sec of Object.values(assign)) {
      for (const u of Object.values(sec.questions || {})) if (u) out.add(u);
      for (const u of (sec.units || [])) if (u) out.add(u);
    }
    return [...out];
  }, [assign]);

  const unitChoices = useMemo(() => {
    const known = new Set(units);
    return [...units, ...pinnedUnits.filter(u => !known.has(u))];
  }, [units, pinnedUnits]);

  const missingMaterial = useMemo(() => {
    const known = new Set(units);
    return pinnedUnits.filter(u => !known.has(u));
  }, [units, pinnedUnits]);

  const unitLabel = useCallback(
    (u) => (units.includes(u) ? u : `${u} — no material uploaded`), [units]);

  const unitOptions = useMemo(
    () => [{ value: NO_UNIT, label: 'Auto — let QPG choose' },
           ...unitChoices.map(u => ({ value: u, label: unitLabel(u) }))],
    [unitChoices, unitLabel]);

  function setQuestionUnit(sectionId, qnum, unit) {
    setAssign(prev => {
      const sec = prev[sectionId] || { questions: {}, units: [] };
      const questions = { ...sec.questions };
      if (unit) questions[qnum] = unit; else delete questions[qnum];
      return { ...prev, [sectionId]: { ...sec, questions } };
    });
  }

  // "Apply to every question in this section" — the bulk action that makes a 38-question board
  // paper practical to plan. Writes each question individually rather than a section-wide default,
  // so the teacher can then adjust any single one without losing the rest.
  function applyToSection(sectionId, unit, questions) {
    setAssign(prev => {
      const sec = prev[sectionId] || { questions: {}, units: [] };
      const next = { ...sec.questions };
      for (const q of questions) {
        if (!q.unit_applicable) continue;
        if (unit) next[q.qnum] = unit; else delete next[q.qnum];
      }
      return { ...prev, [sectionId]: { ...sec, questions: next } };
    });
  }

  // Sections that print no individual question numbers (legacy aggregate-only patterns) can only
  // be planned as a whole, so they get a section-level unit list instead.
  function setSectionUnits(sectionId, unit) {
    setAssign(prev => {
      const sec = prev[sectionId] || { questions: {}, units: [] };
      return { ...prev, [sectionId]: { ...sec, units: unit ? [unit] : [] } };
    });
  }

  const mappedCount = useMemo(() => Object.values(assign)
    .reduce((n, s) => n + Object.keys(s.questions || {}).length, 0), [assign]);
  const sectionLevelCount = useMemo(() => Object.values(assign)
    .filter(s => (s.units || []).length).length, [assign]);

  async function handleSave(e) {
    e.preventDefault();
    if (!patternId) { setError('Choose a pattern first.'); return; }
    if (!cls) { setError('Choose which class this blueprint is for.'); return; }
    if (!subj) { setError('Choose the subject whose units this blueprint uses.'); return; }
    if (!mappedCount && !sectionLevelCount) {
      setError('Assign a unit to at least one question — an empty blueprint would change nothing.');
      return;
    }

    const sections = Object.entries(assign)
      .map(([section_id, s]) => ({
        section_id,
        ...(Object.keys(s.questions || {}).length ? { questions: s.questions } : {}),
        ...((s.units || []).length ? { units: s.units } : {}),
      }))
      .filter(s => s.questions || s.units);

    const payload = {
      name: name.trim()
        || `${scaffold?.pattern?.name || 'Blueprint'} — Class ${cls} ${subj} unit plan`,
      pattern_id: Number(patternId),
      // The class and subject the UNITS belong to — not the pattern's own. The generate page
      // offers a blueprint by these, so a sample paper's source class (10 or 12) would have made
      // a Class 6 plan invisible to the Class 6 teacher who wrote it.
      class_name: cls,
      subject: subj,
      unit_map: { sections },
    };

    setSaving(true);
    setError(null);
    try {
      if (blueprintId) await apiClient.patch(`/blueprints/${blueprintId}/`, payload);
      else await apiClient.post('/blueprints/', payload);
      setSuccess('Blueprint saved! Redirecting…');
      setTimeout(() => router.push('/blueprints'), 1200);
    } catch (err) {
      setError(err.response?.data?.pattern_id?.[0]
        || err.response?.data?.detail
        || 'Could not save the blueprint.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="w-full py-2 mb-20 px-4">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white shadow-sm border border-gray-100 rounded-xl flex items-center justify-center">
            <Layers className="text-cyan-600" size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">
              {blueprintId ? 'Edit Blueprint' : 'Create Blueprint'}
            </h1>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
              Choose which unit each question comes from
            </p>
          </div>
        </div>
        <Link href="/blueprints"
              className="px-5 py-3 bg-gray-100 text-gray-600 rounded-xl font-black text-xs uppercase tracking-wider hover:bg-gray-200 transition-all flex items-center gap-2">
          <ArrowLeft size={16} /> Back
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}

      <div className="mb-6 p-4 bg-cyan-50 border border-cyan-100 rounded-2xl flex gap-3">
        <Info className="text-cyan-600 shrink-0 mt-0.5" size={18} />
        <p className="text-xs font-semibold text-cyan-900 leading-relaxed">
          The <strong>pattern</strong> already decides the structure — how many questions, their type
          and marks. A <strong>blueprint</strong> adds the syllabus: which unit each of those questions
          is set from. Leave a question on <strong>Auto</strong> and QPG picks a unit for it, weighted
          by CBSE marks. You only need to pin the ones you care about.
        </p>
      </div>

      <form onSubmit={handleSave}>
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
          <div className="grid md:grid-cols-2 gap-5">
            <CustomSelect
              label="Pattern"
              icon={GraduationCap}
              options={patternOptions}
              value={patternId}
              onChange={(v) => { setPatternId(v); setAssign({}); }}
              placeholder={loadingPatterns ? 'Loading patterns…' : 'Choose the pattern to plan'}
              disabled={loadingPatterns || Boolean(blueprintId)}
            />
            <div>
              <label className="block text-[11px] font-black text-gray-500 uppercase tracking-wider mb-2">
                Blueprint name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Half-Yearly — first-half units"
                className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm font-semibold text-gray-800 focus:outline-none focus:ring-2 focus:ring-cyan-400"
              />
            </div>
          </div>

          {/* Which class's and subject's units to plan with. Prefilled from the pattern; a sample
              paper covers a whole stage, so there the class is a real choice and the units depend
              on it entirely. */}
          {selectedPattern && (
            <div className="grid md:grid-cols-2 gap-5 mt-5">
              <CustomSelect
                label="Class"
                icon={GraduationCap}
                options={classOptions}
                value={cls}
                onChange={(v) => { setCls(v); setAssign({}); }}
                placeholder="Which class is this for?"
                disabled={classOptions.length <= 1}
              />
              <CustomSelect
                label="Subject"
                icon={BookOpen}
                options={subjectOptions}
                value={subj}
                onChange={(v) => { setSubj(v); setAssign({}); }}
                placeholder={cls ? 'Choose the subject' : 'Pick a class first'}
                disabled={!cls}
              />
            </div>
          )}

          {selectedPattern && classOptions.length > 1 && !cls && (
            <p className="mt-4 text-xs font-semibold text-cyan-800 bg-cyan-50 border border-cyan-100 rounded-xl px-4 py-3">
              <strong>{selectedPattern.name}</strong> is the sample paper for{' '}
              {selectedPattern.class_label || `Classes ${selectedPattern.class_min}-${selectedPattern.class_max}`}.
              Pick the class you are setting the paper for — the units come from that class’s
              uploaded material.
            </p>
          )}

          {scaffold && (
            <div className="mt-5 flex flex-wrap items-center gap-3 text-[11px] font-black uppercase tracking-wider">
              <span className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-full">
                {scaffold.pattern.total_questions} questions · {scaffold.pattern.total_marks}M
              </span>
              <span className="px-3 py-1.5 bg-emerald-50 text-emerald-700 rounded-full">
                {mappedCount} pinned
              </span>
              {sectionLevelCount > 0 && (
                <span className="px-3 py-1.5 bg-blue-50 text-blue-700 rounded-full">
                  {sectionLevelCount} section-wide
                </span>
              )}
              <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-full">
                {units.length} unit{units.length === 1 ? '' : 's'} available
                {cls && subj ? ` · Class ${cls} ${subj}` : ''}
              </span>
            </div>
          )}
        </div>

        {loadingScaffold && (
          <div className="flex items-center gap-3 p-6 bg-white rounded-2xl border border-gray-100">
            <RefreshCw className="animate-spin text-cyan-600" size={18} />
            <span className="text-xs font-black text-gray-500 uppercase tracking-wider">
              Loading the pattern’s questions…
            </span>
          </div>
        )}

        {/* No uploaded material means there are no units to choose from, and a NEW blueprint would
            be unfillable. Say that plainly instead of showing empty dropdowns — but never lock an
            EXISTING blueprint out of being edited: its own pinned units stay selectable below, so
            a teacher can still read the plan, change it and save. */}
        {scaffold && cls && subj && units.length === 0 && (
          <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
            <AlertCircle className="text-amber-600 shrink-0 mt-0.5" size={18} />
            <p className="text-xs font-semibold text-amber-900 leading-relaxed">
              No units found for <strong>Class {scaffold.pattern.class_name} {scaffold.pattern.subject}</strong>.
              A blueprint assigns questions to units from your uploaded material, so upload the
              textbook or notes for this subject first —{' '}
              <Link href="/materials/upload" className="underline font-black">go to Materials</Link>.
              {unitChoices.length > 0 && ' The units this blueprint already uses are still listed '
                + 'below so you can edit it in the meantime.'}
            </p>
          </div>
        )}

        {/* A pin whose material has since gone: still applied at generation time, but the question
            will be written without textbook grounding. The worker logs this; the teacher should
            see it while they can still change it. */}
        {scaffold && units.length > 0 && missingMaterial.length > 0 && (
          <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
            <AlertCircle className="text-amber-600 shrink-0 mt-0.5" size={18} />
            <p className="text-xs font-semibold text-amber-900 leading-relaxed">
              No uploaded material for <strong>{missingMaterial.join(', ')}</strong>. Questions
              pinned there will be written from the model’s own knowledge —{' '}
              <Link href="/materials/upload" className="underline font-black">upload the material</Link>{' '}
              or pick a different unit for them.
            </p>
          </div>
        )}

        {scaffold && cls && subj && unitChoices.length > 0 && scaffold.sections.map((sec) => {
          const secAssign = assign[sec.section_id] || { questions: {}, units: [] };
          const assignable = sec.questions.filter(q => q.unit_applicable);
          return (
            <div key={sec.section_id} className="bg-white rounded-2xl border border-gray-100 shadow-sm mb-5 overflow-hidden">
              <div className="px-6 py-4 bg-gray-50/70 border-b border-gray-100 flex flex-wrap items-center gap-3">
                <span className="px-2.5 py-1 bg-gray-900 text-white rounded-lg text-[10px] font-black tracking-widest">
                  {sec.section_id}
                </span>
                <h3 className="font-black text-gray-900 text-sm flex-1 min-w-[12rem]">{sec.name}</h3>
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-wider">
                  {sec.questions.length || sec.questions_count} Q · {sec.marks}M
                </span>
              </div>

              <div className="p-6">
                {sec.section_level_only ? (
                  <>
                    <p className="text-xs font-semibold text-gray-500 mb-3 leading-relaxed">
                      This section does not list individual question numbers, so it can only be
                      planned as a whole. Every question in it will be drawn from the unit you pick.
                    </p>
                    <div className="max-w-md">
                      <CustomSelect
                        options={unitOptions}
                        value={(secAssign.units || [])[0] || NO_UNIT}
                        onChange={(v) => setSectionUnits(sec.section_id, v)}
                        placeholder="Auto — let QPG choose"
                        icon={BookOpen}
                      />
                    </div>
                  </>
                ) : (
                  <>
                    {assignable.length > 1 && (
                      <div className="flex flex-wrap items-center gap-3 mb-5 pb-5 border-b border-gray-50">
                        <span className="text-[11px] font-black text-gray-500 uppercase tracking-wider flex items-center gap-2">
                          <Wand2 size={14} /> Apply to all {assignable.length} questions
                        </span>
                        <div className="w-72">
                          <CustomSelect
                            options={unitOptions}
                            value={NO_UNIT}
                            onChange={(v) => applyToSection(sec.section_id, v, sec.questions)}
                            placeholder="Pick a unit for the whole section"
                            icon={BookOpen}
                          />
                        </div>
                      </div>
                    )}

                    <div className="grid gap-2.5">
                      {sec.questions.map((q) => (
                        <div key={q.qnum} className="flex flex-wrap items-center gap-3">
                          <span className="w-14 shrink-0 flex items-center gap-1 text-xs font-black text-gray-700">
                            <Hash size={12} className="text-gray-300" />{q.qnum}
                          </span>
                          <span className="w-44 shrink-0 text-[11px] font-bold text-gray-500 truncate"
                                title={`${q.type_label}${q.topic ? ` — ${q.topic}` : ''}`}>
                            {q.type_label}
                            {q.choice === 'internal' && (
                              <span className="ml-1 text-amber-600">(or)</span>
                            )}
                          </span>
                          <span className="w-12 shrink-0 text-[11px] font-black text-gray-400">
                            {q.marks}M
                          </span>

                          {q.unit_applicable ? (
                            <select
                              value={secAssign.questions?.[q.qnum] || NO_UNIT}
                              onChange={(e) => setQuestionUnit(sec.section_id, q.qnum, e.target.value)}
                              className={`flex-1 min-w-[14rem] px-3 py-2 rounded-xl text-xs font-bold border focus:outline-none focus:ring-2 focus:ring-cyan-400 ${
                                secAssign.questions?.[q.qnum]
                                  ? 'bg-cyan-50 border-cyan-200 text-cyan-900'
                                  : 'bg-gray-50 border-gray-200 text-gray-500'
                              }`}
                            >
                              <option value={NO_UNIT}>Auto — let QPG choose</option>
                              {unitChoices.map(u => (
                                <option key={u} value={u}>{unitLabel(u)}</option>
                              ))}
                            </select>
                          ) : (
                            /* An unseen passage or general-knowledge question is deliberately NOT
                               from a chapter — the pattern says so — so pinning a unit to it would
                               contradict the pattern. */
                            <span className="flex-1 min-w-[14rem] px-3 py-2 rounded-xl text-[11px] font-bold bg-gray-50 border border-dashed border-gray-200 text-gray-400">
                              Not from a unit — the pattern sets this question as
                              {' '}{q.type === 'cbq' ? 'an unseen passage' : 'general knowledge'}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          );
        })}

        {scaffold && cls && subj && unitChoices.length > 0 && (
          <div className="flex flex-col md:flex-row items-center justify-end gap-4 pt-8 border-t border-gray-100">
            <Link href="/blueprints"
                  className="w-full md:w-auto px-8 py-4 bg-gray-100 text-gray-600 rounded-2xl font-black text-xs uppercase tracking-widest hover:bg-gray-200 transition-all text-center">
              Cancel
            </Link>
            <button
              type="submit"
              disabled={saving}
              className="w-full md:w-auto px-10 py-4 bg-cyan-600 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-cyan-200 hover:bg-cyan-700 transition-all flex items-center justify-center gap-3 active:scale-95 disabled:opacity-50"
            >
              {saving
                ? <><div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Saving…</>
                : <><Save size={18} /> {blueprintId ? 'Update Blueprint' : 'Save Blueprint'}</>}
            </button>
          </div>
        )}
      </form>

      {scaffold && mappedCount > 0 && (
        <div className="mt-6 p-4 bg-emerald-50 border border-emerald-100 rounded-2xl flex gap-3">
          <CheckCircle2 className="text-emerald-600 shrink-0 mt-0.5" size={18} />
          <p className="text-xs font-semibold text-emerald-900 leading-relaxed">
            {mappedCount} question{mappedCount === 1 ? '' : 's'} pinned. Attach this blueprint when
            you generate a paper from <strong>{scaffold.pattern.name}</strong> and those questions
            will be set from exactly these units — the rest are chosen automatically.
          </p>
        </div>
      )}
    </div>
  );
}
