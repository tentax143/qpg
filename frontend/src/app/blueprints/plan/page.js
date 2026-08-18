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
        const res = await apiClient.get('/patterns/');
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

  const loadScaffold = useCallback(async (id) => {
    setLoadingScaffold(true);
    setError(null);
    try {
      const res = await apiClient.get(`/patterns/${id}/blueprint-scaffold/`);
      setScaffold(res.data);
    } catch {
      setError('Could not load that pattern’s questions.');
      setScaffold(null);
    } finally {
      setLoadingScaffold(false);
    }
  }, []);

  useEffect(() => {
    if (patternId) loadScaffold(patternId);
    else setScaffold(null);
  }, [patternId, loadScaffold]);

  const patternOptions = useMemo(() => patterns.map(p => ({
    value: String(p.id),
    label: `${p.name} — Class ${p.class_name} ${p.subject} (${p.total_marks}M)`,
  })), [patterns]);

  // Memoised so the `|| []` fallback isn't a fresh array on every render, which would make
  // unitOptions recompute (and re-render every one of a 38-question paper's dropdowns) each time.
  const units = useMemo(() => scaffold?.units || [], [scaffold]);
  const unitOptions = useMemo(
    () => [{ value: NO_UNIT, label: 'Auto — let QPG choose' }, ...units.map(u => ({ value: u, label: u }))],
    [units]);

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
      name: name.trim() || `${scaffold?.pattern?.name || 'Blueprint'} — unit plan`,
      pattern_id: Number(patternId),
      class_name: scaffold?.pattern?.class_name || '',
      subject: scaffold?.pattern?.subject || '',
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

        {/* No uploaded material means there are no units to choose from, and a blueprint would be
            unfillable. Say that plainly instead of showing empty dropdowns. */}
        {scaffold && units.length === 0 && (
          <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
            <AlertCircle className="text-amber-600 shrink-0 mt-0.5" size={18} />
            <p className="text-xs font-semibold text-amber-900 leading-relaxed">
              No units found for <strong>Class {scaffold.pattern.class_name} {scaffold.pattern.subject}</strong>.
              A blueprint assigns questions to units from your uploaded material, so upload the
              textbook or notes for this subject first —{' '}
              <Link href="/materials/upload" className="underline font-black">go to Materials</Link>.
            </p>
          </div>
        )}

        {scaffold && units.length > 0 && scaffold.sections.map((sec) => {
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
                              {units.map(u => <option key={u} value={u}>{u}</option>)}
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

        {scaffold && units.length > 0 && (
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
