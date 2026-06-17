'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft, Plus, Trash2, BookOpen, GraduationCap, Layers, Wand2, Info,
  AlertCircle, CheckCircle, FileText, Settings, MessageSquare, Layout, Type,
  RefreshCw, Sparkles, Edit3,
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';
import { subjectOptions } from '@/lib/subjects';

// ─── Static data ─────────────────────────────────────────────────────────────

const classOptions = Array.from({ length: 12 }, (_, i) => ({
  value: String(i + 1),
  label: `Class ${i + 1}`,
}));

const EXAM_NAME_OPTIONS = [
  { value: 'unit_test', label: 'Unit Test' },
  { value: 'pt1',       label: 'PT-1  —  Periodic Test 1' },
  { value: 'pt2',       label: 'PT-2  —  Periodic Test 2' },
  { value: 'pt3',       label: 'PT-3  —  Periodic Test 3' },
  { value: 'half_yearly', label: 'Half-Yearly Exam' },
  { value: 'pre_board',   label: 'Pre-Board Exam' },
  { value: 'annual',      label: 'Annual Exam' },
  { value: 'board',       label: 'Board Exam Pattern' },
  { value: 'custom',      label: 'Custom Name...' },
];

const EXAM_DISPLAY_NAMES = {
  unit_test:   'Unit Test',
  pt1:         'PT-1 (Periodic Test 1)',
  pt2:         'PT-2 (Periodic Test 2)',
  pt3:         'PT-3 (Periodic Test 3)',
  half_yearly: 'Half-Yearly Exam',
  pre_board:   'Pre-Board Exam',
  annual:      'Annual Exam',
  board:       'Board Exam Pattern',
};

const EXAM_HINTS = {
  unit_test:   '20 marks · ~40 min · chapter-level · school assessment',
  pt1:         '20 marks · 1 hr · ~25% syllabus · PT best-2-of-3 counted',
  pt2:         '20 marks · 1 hr · ~50% syllabus · PT best-2-of-3 counted',
  pt3:         '20 marks · 1 hr · ~75% syllabus · PT best-2-of-3 counted',
  half_yearly: '80 marks · 3 hr · first-half syllabus · board-style sections',
  pre_board:   '80 marks · 3 hr · full syllabus · board paper practice',
  annual:      '80 marks · 3 hr · full syllabus · school final exam',
  board:       'Official CBSE 2024-25 board paper — auto-loaded from research data',
  custom:      'Type your own pattern name',
};

// Board-style exam types that load from official CBSE data
const BOARD_PATTERN_TYPES = new Set(['board', 'half_yearly', 'pre_board', 'annual']);

// Built-in 20-mark default for PT / unit-test
const PT_DEFAULT_RAW = [
  { name: 'A', type: 'Multiple Choice Questions',     count: 10, marks_each: 1, total: 10, notes: '' },
  { name: 'B', type: 'Short Answer',                  count: 4,  marks_each: 2, total: 8,  notes: '50-80 words each' },
  { name: 'C', type: 'Long Answer',                   count: 1,  marks_each: 4, total: 4,  notes: '100-120 words' },
];

const QUESTION_TYPE_OPTIONS = [
  { label: 'MCQ',                   value: 'MCQ' },
  { label: 'Assertion-Reason',      value: 'Assertion-Reason' },
  { label: 'Very Short Answer',     value: 'Very Short Answer' },
  { label: 'Short Answer',          value: 'Short Answer' },
  { label: 'Long Answer',           value: 'Long Answer' },
  { label: 'Case Study',            value: 'Case Study' },
  { label: 'Reading Comprehension', value: 'Reading Comprehension' },
  { label: 'Writing',               value: 'Writing' },
  { label: 'Grammar',               value: 'Grammar' },
  { label: 'Literature',            value: 'Literature' },
  { label: 'Map Work',              value: 'Map Work' },
  { label: 'Mixed',                 value: 'Mixed' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function inferQType(typeStr = '') {
  const t = typeStr.toLowerCase();
  if (t.includes('mcq') || t.includes('multiple choice')) return 'MCQ';
  if (t.includes('assertion'))                             return 'Assertion-Reason';
  if (t.includes('case'))                                  return 'Case Study';
  if (t.includes('very short') || t.includes('vsa'))       return 'Very Short Answer';
  if (t.includes('long'))                                  return 'Long Answer';
  if (t.includes('short'))                                 return 'Short Answer';
  if (t.includes('reading') || t.includes('unseen') || t.includes('passage')) return 'Reading Comprehension';
  if (t.includes('writing') || t.includes('creative'))    return 'Writing';
  if (t.includes('grammar'))                               return 'Grammar';
  if (t.includes('literature'))                            return 'Literature';
  if (t.includes('map'))                                   return 'Map Work';
  return 'Mixed';
}

function rawToEditorSection(s, idx) {
  const rawName = s.name || '';
  const letterMatch = rawName.match(/^([A-Z])/i);
  const id = letterMatch ? letterMatch[1].toUpperCase() : String.fromCharCode(65 + idx);

  const count     = typeof s.count === 'number' ? s.count : (s.sub ? s.sub.length : 1);
  const total     = typeof s.total === 'number' ? s.total : count;
  const marksEach = typeof s.marks_each === 'number'
    ? s.marks_each
    : (count > 0 ? Math.round((total / count) * 10) / 10 : 1);

  let notes = s.notes || '';
  if (!notes && s.sub) {
    notes = s.sub.slice(0, 4).map(q => q.type?.slice(0, 45)).filter(Boolean).join('; ');
  }
  if (s.internal_choice && s.choices && !notes.includes(s.choices)) {
    notes = [notes, s.choices].filter(Boolean).join(' | ');
  }

  return {
    id,
    name:               `Section ${id}`,
    questions_count:    count,
    marks_per_question: marksEach,
    marks:              total,
    question_type:      inferQType(s.type || s.title || ''),
    instructions:       notes,
  };
}

// Convert CBSE pattern data into editable plain text for the AI textarea
function patternToText(rawPattern, examKey, subj, cls) {
  const examName = EXAM_DISPLAY_NAMES[examKey] || examKey;
  const totalMarks = rawPattern.theory_marks || rawPattern.marks_theory || 80;
  const duration   = rawPattern.duration_minutes || 180;
  const totalQ     = rawPattern.total_questions || '';
  const lines = [
    `${subj.toUpperCase()} — CLASS ${cls} — ${examName.toUpperCase()}`,
    `Total Marks: ${totalMarks} | Duration: ${duration} minutes${totalQ ? ` | Questions: ${totalQ}` : ''}`,
    '',
  ];

  for (const s of (rawPattern.sections || [])) {
    const rawName  = (s.name || '').split(/[—–\-]/)[0].trim();
    const type     = s.type || s.title || '';
    const count    = typeof s.count === 'number' ? s.count : (s.sub ? s.sub.length : null);
    const mEach    = typeof s.marks_each === 'number' ? s.marks_each : null;
    const total    = typeof s.total === 'number' ? s.total : null;

    lines.push(`Section ${rawName} — ${type}`);

    if (count !== null && mEach !== null && total !== null) {
      lines.push(`${count} question${count !== 1 ? 's' : ''} × ${mEach} mark${mEach !== 1 ? 's' : ''} each = ${total} marks`);
    } else if (total !== null) {
      lines.push(`Total: ${total} marks`);
      if (s.sub) {
        for (const sub of s.sub) {
          const q  = sub.q   ? `${sub.q}: ` : '';
          const t  = sub.type ? sub.type.slice(0, 60) : '';
          const m  = sub.marks ? ` (${sub.marks} marks)` : '';
          lines.push(`  ${q}${t}${m}`);
        }
      }
    }

    const extras = [];
    if (s.notes)    extras.push(s.notes);
    if (s.choices)  extras.push(s.choices);
    if (s.internal_choice && !s.choices) extras.push('Internal choice available');
    if (extras.length) lines.push(extras.join(' | '));
    lines.push('');
  }

  lines.push('--- Edit sections above as needed. You can add conditions, e.g.:');
  lines.push('--- "Section A: 4 questions must be Assertion-Reason, 2 questions diagram-based"');

  return lines.join('\n');
}

// Generate text for PT / unit-test (no CBSE official pattern, 20 marks)
function ptDefaultToText(examKey, subj, cls) {
  const examName = EXAM_DISPLAY_NAMES[examKey] || examKey;
  return [
    `${subj.toUpperCase()} — CLASS ${cls} — ${examName.toUpperCase()}`,
    'Total Marks: 20 | Duration: 60 minutes',
    '',
    'Section A — Multiple Choice Questions',
    '10 questions × 1 mark each = 10 marks',
    '',
    'Section B — Short Answer',
    '4 questions × 2 marks each = 8 marks',
    '50-80 words each',
    '',
    'Section C — Long Answer',
    '1 question × 4 marks = 4 marks',
    '100-120 words',
    '',
    '--- Edit sections above as needed. You can add conditions, e.g.:',
    '--- "Section A: 2 questions must be Assertion-Reason, include 1 diagram-based"',
  ].join('\n');
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function CreatePatternPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState('manual');
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const [success, setSuccess]     = useState(null);

  const [className, setClassName]     = useState('');
  const [subject, setSubject]         = useState('');
  const [patternKey, setPatternKey]   = useState('');   // exam type key
  const [customName, setCustomName]   = useState('');   // free-text when key==='custom'
  const [description, setDescription] = useState('');

  const [sections, setSections]           = useState([]);
  const [aiPrompt, setAiPrompt]           = useState('');
  const [loadingPattern, setLoadingPattern] = useState(false);
  const [loadedFrom, setLoadedFrom]         = useState(null); // 'cbse_official' | 'pt_default' | null
  const [loadError, setLoadError]           = useState(null);

  // AI generation polling
  const [generating, setGenerating]   = useState(false);  // true while Celery task is running
  const [genPatternId, setGenPatternId] = useState(null); // id to poll

  // Compute the final pattern name for the payload
  const finalName = patternKey === 'custom' ? customName : (EXAM_DISPLAY_NAMES[patternKey] || '');

  // Auto-load when all three fields are set
  useEffect(() => {
    if (!patternKey || patternKey === 'custom') return;
    if (!className || !subject) return;
    loadPattern(patternKey, subject, className);
  }, [patternKey, className, subject]);

  async function loadPattern(key, subj, cls) {
    setLoadError(null);
    setLoadedFrom(null);

    // PT / unit-test — use built-in 20-mark defaults
    if (!BOARD_PATTERN_TYPES.has(key)) {
      // Manual tab: fill section cards
      setSections(PT_DEFAULT_RAW.map((s, i) => rawToEditorSection(s, i)));
      // AI tab: fill textarea with readable text
      setAiPrompt(ptDefaultToText(key, subj, cls));
      setLoadedFrom('pt_default');
      return;
    }

    // Board-style — fetch official CBSE pattern
    try {
      setLoadingPattern(true);
      const res = await apiClient.get(
        `/cbse/pattern/?subject=${encodeURIComponent(subj)}&class=${encodeURIComponent(cls)}`
      );
      const rawPat      = res.data?.pattern || {};
      const rawSections = rawPat.sections   || [];
      if (rawSections.length === 0) {
        setLoadError(`No official CBSE pattern found for ${subj} Class ${cls}. Add sections manually.`);
        setSections([]);
        setAiPrompt('');
      } else {
        // Manual tab: fill section cards
        setSections(rawSections.map((s, i) => rawToEditorSection(s, i)));
        // AI tab: fill textarea with readable text
        setAiPrompt(patternToText(rawPat, key, subj, cls));
        setLoadedFrom('cbse_official');
      }
    } catch (err) {
      if (err.response?.status === 404) {
        setLoadError(`No official CBSE pattern found for ${subj} Class ${cls}. Add sections manually.`);
      } else {
        setLoadError('Could not load pattern. Check your connection.');
      }
      setSections([]);
      setAiPrompt('');
    } finally {
      setLoadingPattern(false);
    }
  }

  function handlePatternKeyChange(val) {
    setPatternKey(val);
    setLoadedFrom(null);
    setLoadError(null);
    setSections([]);
    if (val !== 'custom') setCustomName('');
  }

  // Section editor helpers
  function addSection() {
    const id = String.fromCharCode(65 + sections.length);
    setSections(prev => [...prev, {
      id,
      name:              `Section ${id}`,
      questions_count:   1,
      marks_per_question: 1,
      marks:             1,
      question_type:     'MCQ',
      instructions:      '',
    }]);
  }

  function updateSection(idx, field, value) {
    setSections(prev => {
      const next = prev.map((s, i) => i === idx ? { ...s, [field]: value } : s);
      if (field === 'questions_count' || field === 'marks_per_question') {
        const qc  = field === 'questions_count'   ? (parseInt(value)   || 0) : (parseInt(next[idx].questions_count)   || 0);
        const mpq = field === 'marks_per_question' ? (parseFloat(value) || 0) : (parseFloat(next[idx].marks_per_question) || 0);
        next[idx] = { ...next[idx], marks: qc * mpq };
      }
      return next;
    });
  }

  function removeSection(idx) {
    setSections(prev => prev.filter((_, i) => i !== idx));
  }

  // Poll pattern status until done or failed
  useEffect(() => {
    if (!genPatternId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await apiClient.get(`/patterns/${genPatternId}/`);
        const pat = res.data;
        if (pat.status === 'done') {
          if (!cancelled) {
            setGenerating(false);
            setGenPatternId(null);
            setSuccess('Pattern generated! Redirecting…');
            setTimeout(() => router.push('/patterns'), 1500);
          }
        } else if (pat.status === 'failed') {
          if (!cancelled) {
            setGenerating(false);
            setGenPatternId(null);
            setError('AI generation failed. Edit the prompt and try again.');
          }
        } else {
          // still queued / generating — check again in 3 seconds
          if (!cancelled) setTimeout(poll, 3000);
        }
      } catch {
        if (!cancelled) {
          setGenerating(false);
          setGenPatternId(null);
          setError('Could not check generation status. Check your connection.');
        }
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [genPatternId]);

  // Submit
  async function handleSubmit(e) {
    e.preventDefault();
    if (!finalName.trim()) { setError('Pattern name is required'); return; }
    if (!className)        { setError('Class is required'); return; }
    if (!subject)          { setError('Subject is required'); return; }

    setLoading(true);
    setError(null);

    try {
      if (activeTab === 'manual') {
        if (sections.length === 0) throw new Error('Add at least one section');
        const payload = {
          name: finalName, class_name: className, subject, description,
          sections,
          total_marks:     sections.reduce((s, r) => s + (r.marks || 0), 0),
          total_questions: sections.reduce((s, r) => s + (parseInt(r.questions_count) || 0), 0),
          pattern_source:  'manual',
        };
        await apiClient.post('/patterns/', payload);
        setSuccess('Pattern created successfully!');
        setTimeout(() => router.push('/patterns'), 1500);
      } else {
        // AI tab — dispatch Celery task, then poll
        if (!aiPrompt.trim()) throw new Error('Add a pattern description before generating');
        const res = await apiClient.post('/patterns/generate_from_ai/', {
          name: finalName, class_name: className, subject, description,
          teacher_input: aiPrompt,
        });
        // 202 Accepted — start polling
        setGenerating(true);
        setGenPatternId(res.data.id);
        setLoading(false);
        return; // don't fall through to the finally setLoading(false)
      }
    } catch (err) {
      setError(err.message || err.response?.data?.error || err.response?.data?.detail || 'Failed to create pattern');
    } finally {
      setLoading(false);
    }
  }

  const totalMarks     = sections.reduce((s, r) => s + (r.marks || 0), 0);
  const totalQuestions = sections.reduce((s, r) => s + (parseInt(r.questions_count) || 0), 0);

  return (
    <div className="w-full relative py-2 mb-20 px-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white shadow-sm border border-gray-100 rounded-xl flex items-center justify-center">
            <Plus className="text-blue-600" size={20} />
          </div>
          <h1 className="text-2xl font-black text-gray-900 tracking-tight">Create Exam Pattern</h1>
        </div>
        <button onClick={() => router.back()} className="text-xs font-bold text-gray-400 hover:text-gray-900 transition-colors flex items-center gap-2">
          <ArrowLeft size={14} />
          Back to Patterns
        </button>
      </div>

      {error   && <ErrorAlert   message={error}   onClose={() => setError(null)}   className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">

        {/* ── Tabs ── */}
        <div className="p-6 border-b border-gray-50 bg-white/50 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Settings className="text-blue-600" size={20} />
            <h2 className="text-lg font-black text-gray-900 uppercase tracking-tight">Create New Exam Pattern</h2>
          </div>
          <div className="flex bg-gray-100 p-1 rounded-2xl">
            {[{ key: 'manual', icon: Layout, label: 'Manual Pattern' }, { key: 'ai', icon: Wand2, label: 'AI Pattern' }].map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                  activeTab === t.key ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                <t.icon size={14} />
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-8">

          {/* ── Step 1: Basic Info ── */}
          <div className="mb-12">
            <div className="flex items-center gap-2 mb-6">
              <Info size={16} className="text-blue-500" />
              <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Step 1: Basic Information</h3>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">

              {/* Class */}
              <CustomSelect
                label="Class"
                icon={GraduationCap}
                value={className}
                onChange={setClassName}
                options={classOptions}
                placeholder="Select Class"
                className="space-y-2"
              />

              {/* Subject */}
              <CustomSelect
                label="Subject"
                icon={BookOpen}
                value={subject}
                onChange={setSubject}
                options={subjectOptions}
                placeholder="Select Subject"
                className="space-y-2"
              />

              {/* Pattern Name */}
              <div className="space-y-2">
                <CustomSelect
                  label="Pattern Name"
                  icon={FileText}
                  value={patternKey}
                  onChange={handlePatternKeyChange}
                  options={EXAM_NAME_OPTIONS}
                  placeholder="Select exam type"
                  className="space-y-2"
                />
                {patternKey && patternKey !== 'custom' && (
                  <p className="text-[9px] text-blue-500 font-bold ml-1 uppercase tracking-wide">
                    {EXAM_HINTS[patternKey]}
                  </p>
                )}
                {/* Custom name input */}
                {patternKey === 'custom' && (
                  <div className="mt-2">
                    <div className="relative">
                      <Edit3 size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                      <input
                        type="text"
                        required
                        value={customName}
                        onChange={e => setCustomName(e.target.value)}
                        placeholder="e.g. Revision Test — Optics"
                        className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none font-bold text-sm shadow-sm text-gray-900"
                      />
                    </div>
                    <p className="text-[9px] text-gray-400 font-bold ml-1 mt-1">
                      {EXAM_HINTS.custom}
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Optional description */}
            <div className="mt-6 space-y-2">
              <label className="flex items-center gap-2 text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] ml-1">
                <MessageSquare size={12} />
                Description (optional)
              </label>
              <input
                type="text"
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="e.g. Half-yearly for Class 10 covering Ch 1–6"
                className="w-full px-5 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none font-bold text-sm shadow-sm text-gray-900"
              />
            </div>
          </div>

          {/* ── Step 2 ── */}
          {activeTab === 'manual' ? (
            <div className="mb-12">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Layers size={16} className="text-blue-500" />
                  <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Step 2: Pattern Structure</h3>
                </div>
                <div className="flex items-center gap-3">
                  {/* Reload button when class+subject+preset are all set */}
                  {patternKey && patternKey !== 'custom' && className && subject && (
                    <button
                      type="button"
                      onClick={() => loadPattern(patternKey, subject, className)}
                      disabled={loadingPattern}
                      className="flex items-center gap-2 px-4 py-2.5 bg-blue-50 border border-blue-100 text-blue-600 rounded-xl font-black text-xs uppercase tracking-widest hover:bg-blue-100 transition-all disabled:opacity-50"
                    >
                      <RefreshCw size={13} className={loadingPattern ? 'animate-spin' : ''} />
                      Reload Pattern
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={addSection}
                    className="flex items-center gap-2 px-6 py-3 bg-white border border-gray-100 text-blue-600 rounded-xl font-black text-xs uppercase tracking-widest hover:bg-blue-50 transition-all shadow-sm"
                  >
                    <Plus size={16} />
                    Add Section
                  </button>
                </div>
              </div>

              {/* Status banners */}
              {loadingPattern && (
                <div className="mb-6 flex items-center gap-3 p-4 bg-blue-50 rounded-2xl border border-blue-100">
                  <RefreshCw size={16} className="text-blue-500 animate-spin" />
                  <span className="text-xs font-black text-blue-600 uppercase tracking-wide">
                    Loading official CBSE pattern for {subject} Class {className}…
                  </span>
                </div>
              )}

              {!loadingPattern && loadedFrom === 'cbse_official' && (
                <div className="mb-6 flex items-center gap-3 p-4 bg-emerald-50 rounded-2xl border border-emerald-100">
                  <Sparkles size={16} className="text-emerald-500" />
                  <div className="flex-1">
                    <span className="text-xs font-black text-emerald-700 uppercase tracking-wide">
                      Loaded from official CBSE 2024-25 board pattern
                    </span>
                    <span className="text-[10px] text-emerald-600 font-bold ml-2">— edit sections as needed</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => { setSections([]); setLoadedFrom(null); }}
                    className="text-[10px] font-black text-emerald-600 hover:text-emerald-800 uppercase tracking-wide"
                  >
                    Clear
                  </button>
                </div>
              )}

              {!loadingPattern && loadedFrom === 'pt_default' && (
                <div className="mb-6 flex items-center gap-3 p-4 bg-amber-50 rounded-2xl border border-amber-100">
                  <Info size={16} className="text-amber-500" />
                  <div className="flex-1">
                    <span className="text-xs font-black text-amber-700 uppercase tracking-wide">
                      Default 20-mark PT structure loaded
                    </span>
                    <span className="text-[10px] text-amber-600 font-bold ml-2">— customise sections for your syllabus</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => { setSections([]); setLoadedFrom(null); }}
                    className="text-[10px] font-black text-amber-600 hover:text-amber-800 uppercase tracking-wide"
                  >
                    Clear
                  </button>
                </div>
              )}

              {!loadingPattern && loadError && (
                <div className="mb-6 flex items-center gap-3 p-4 bg-gray-50 rounded-2xl border border-gray-200">
                  <AlertCircle size={16} className="text-gray-400" />
                  <span className="text-xs font-bold text-gray-500">{loadError}</span>
                </div>
              )}

              {/* Totals badge */}
              {sections.length > 0 && (
                <div className="mb-6 flex items-center gap-4 flex-wrap">
                  <div className="flex items-center gap-2 px-4 py-2 bg-blue-50 rounded-xl border border-blue-100">
                    <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">Total Marks</span>
                    <span className="text-sm font-black text-blue-700">{totalMarks}</span>
                  </div>
                  <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 rounded-xl border border-gray-200">
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Total Questions</span>
                    <span className="text-sm font-black text-gray-700">{totalQuestions}</span>
                  </div>
                  <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 rounded-xl border border-gray-200">
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Sections</span>
                    <span className="text-sm font-black text-gray-700">{sections.length}</span>
                  </div>
                </div>
              )}

              {/* Sections list */}
              <div className="space-y-4">
                {sections.length === 0 ? (
                  <div className="text-center py-20 bg-gray-50/50 rounded-[40px] border-2 border-dashed border-gray-200 flex flex-col items-center">
                    <div className="w-16 h-16 bg-white rounded-3xl shadow-sm flex items-center justify-center mb-4">
                      <Layout size={32} className="text-gray-300" />
                    </div>
                    {patternKey && patternKey !== 'custom' && (!className || !subject) ? (
                      <p className="text-gray-400 font-bold">Select a class and subject above to auto-load the CBSE pattern.</p>
                    ) : (
                      <p className="text-gray-400 font-bold">No sections yet. Click "Add Section" or select a preset above.</p>
                    )}
                  </div>
                ) : (
                  sections.map((section, idx) => (
                    <div key={idx} className="bg-gray-50/50 rounded-3xl p-6 border border-gray-100 animate-in slide-in-from-bottom-2 duration-300">
                      <div className="flex flex-col gap-5">
                        <div className="flex flex-col lg:flex-row lg:items-start gap-6">

                          {/* Section letter badge */}
                          <div className="flex items-center gap-3 min-w-[80px]">
                            <div className="w-10 h-10 rounded-2xl bg-blue-600 flex items-center justify-center shrink-0">
                              <span className="text-white font-black text-sm">{section.id}</span>
                            </div>
                            <div>
                              <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest">Section</p>
                              <p className="text-xs font-black text-gray-700">{section.id}</p>
                            </div>
                          </div>

                          <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-4">
                            {/* Questions */}
                            <div className="space-y-1">
                              <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Questions</label>
                              <input
                                type="number" min="1"
                                value={section.questions_count}
                                onChange={e => updateSection(idx, 'questions_count', e.target.value)}
                                className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none font-bold text-sm text-gray-900"
                              />
                            </div>

                            {/* Marks/Q */}
                            <div className="space-y-1">
                              <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Marks / Q</label>
                              <input
                                type="number" step="0.5" min="0.5"
                                value={section.marks_per_question}
                                onChange={e => updateSection(idx, 'marks_per_question', e.target.value)}
                                className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none font-bold text-sm text-gray-900"
                              />
                            </div>

                            {/* Total marks (computed) */}
                            <div className="space-y-1">
                              <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Total Marks</label>
                              <div className="w-full px-4 py-2.5 bg-blue-50 text-blue-600 border border-blue-100 rounded-xl font-black text-sm text-center">
                                {section.marks}
                              </div>
                            </div>

                            {/* Question type */}
                            <CustomSelect
                              label="Type"
                              value={section.question_type}
                              onChange={val => updateSection(idx, 'question_type', val)}
                              options={QUESTION_TYPE_OPTIONS}
                              placeholder="Type"
                              className="!space-y-1"
                            />
                          </div>

                          {/* Delete */}
                          <button
                            type="button"
                            onClick={() => removeSection(idx)}
                            className="w-10 h-10 flex items-center justify-center bg-red-50 text-red-500 rounded-2xl hover:bg-red-600 hover:text-white transition-all shrink-0 self-start mt-5"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>

                        {/* Instructions */}
                        <div className="space-y-1">
                          <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1 flex items-center gap-1.5">
                            <MessageSquare size={10} />
                            Notes / Instructions (optional)
                          </label>
                          <input
                            type="text"
                            value={section.instructions || ''}
                            onChange={e => updateSection(idx, 'instructions', e.target.value)}
                            placeholder="e.g. Internal choice in 2 questions, 50-80 words each…"
                            className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none font-bold text-sm text-gray-900"
                          />
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : (
            /* AI tab */
            <div className="mb-12">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <Wand2 size={16} className="text-blue-500" />
                  <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Step 2: Pattern Description</h3>
                </div>
                {patternKey && patternKey !== 'custom' && className && subject && (
                  <button
                    type="button"
                    onClick={() => loadPattern(patternKey, subject, className)}
                    disabled={loadingPattern}
                    className="flex items-center gap-2 px-4 py-2.5 bg-blue-50 border border-blue-100 text-blue-600 rounded-xl font-black text-xs uppercase tracking-widest hover:bg-blue-100 transition-all disabled:opacity-50"
                  >
                    <RefreshCw size={13} className={loadingPattern ? 'animate-spin' : ''} />
                    Reload Pattern
                  </button>
                )}
              </div>

              {/* Loading spinner */}
              {loadingPattern && (
                <div className="mb-4 flex items-center gap-3 p-4 bg-blue-50 rounded-2xl border border-blue-100">
                  <RefreshCw size={16} className="text-blue-500 animate-spin" />
                  <span className="text-xs font-black text-blue-600 uppercase tracking-wide">
                    Loading official CBSE pattern for {subject} Class {className}…
                  </span>
                </div>
              )}

              {/* Loaded banner */}
              {!loadingPattern && loadedFrom === 'cbse_official' && (
                <div className="mb-4 flex items-center gap-3 p-4 bg-emerald-50 rounded-2xl border border-emerald-100">
                  <Sparkles size={16} className="text-emerald-500" />
                  <div className="flex-1">
                    <span className="text-xs font-black text-emerald-700 uppercase tracking-wide">
                      Official CBSE 2024-25 pattern loaded
                    </span>
                    <span className="text-[10px] text-emerald-600 font-bold ml-2">— edit the text below to customise</span>
                  </div>
                  <button type="button" onClick={() => { setAiPrompt(''); setLoadedFrom(null); }}
                    className="text-[10px] font-black text-emerald-600 hover:text-emerald-800 uppercase tracking-wide">
                    Clear
                  </button>
                </div>
              )}

              {!loadingPattern && loadedFrom === 'pt_default' && (
                <div className="mb-4 flex items-center gap-3 p-4 bg-amber-50 rounded-2xl border border-amber-100">
                  <Info size={16} className="text-amber-500" />
                  <div className="flex-1">
                    <span className="text-xs font-black text-amber-700 uppercase tracking-wide">
                      Default 20-mark PT structure loaded
                    </span>
                    <span className="text-[10px] text-amber-600 font-bold ml-2">— edit sections as needed for your syllabus</span>
                  </div>
                  <button type="button" onClick={() => { setAiPrompt(''); setLoadedFrom(null); }}
                    className="text-[10px] font-black text-amber-600 hover:text-amber-800 uppercase tracking-wide">
                    Clear
                  </button>
                </div>
              )}

              {!loadingPattern && loadError && (
                <div className="mb-4 flex items-center gap-3 p-4 bg-gray-50 rounded-2xl border border-gray-200">
                  <AlertCircle size={16} className="text-gray-400" />
                  <span className="text-xs font-bold text-gray-500">{loadError}</span>
                </div>
              )}

              {/* Instructions when no preset chosen yet */}
              {!patternKey && (
                <p className="text-[10px] text-gray-400 font-bold mb-4 uppercase tracking-wide leading-relaxed">
                  Select Class + Subject + Exam Type above — the pattern will auto-fill here for editing.
                  Or type / paste your own pattern below.
                </p>
              )}

              <div className="relative">
                <textarea
                  required
                  rows={loadedFrom ? 16 : 10}
                  value={aiPrompt}
                  onChange={e => setAiPrompt(e.target.value)}
                  placeholder={
                    patternKey && className && subject
                      ? 'Pattern loading…'
                      : 'Select Class, Subject and Exam Type above — the CBSE pattern will auto-fill here.\n\nOr type your own:\nSection A: 20 questions MCQ 1 mark each\nSection B: 5 Short Answer 2 marks each (50-80 words)\nSection C: 3 Long Answer 5 marks each\n\nYou can add conditions like:\n  Section A: 4 questions must be Assertion-Reason, compulsory'
                  }
                  className="w-full px-6 py-5 bg-gray-50/50 border border-gray-200 rounded-[32px] focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none font-mono text-sm leading-relaxed text-gray-900 resize-y"
                />
              </div>

              <div className="mt-4 flex items-start gap-2 text-[10px] font-bold text-gray-400 uppercase tracking-widest pl-2">
                <AlertCircle size={14} className="text-amber-500 mt-0.5 shrink-0" />
                <span>
                  AI will follow this structure exactly. Add conditions inline —
                  e.g. <span className="text-gray-600">"Section A: 4 questions must be Assertion-Reason, compulsory"</span>
                </span>
              </div>
            </div>
          )}

          {/* Celery generation progress bar */}
          {generating && (
            <div className="mb-6 p-5 bg-blue-50 rounded-2xl border border-blue-100">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-5 h-5 border-2 border-blue-400/40 border-t-blue-600 rounded-full animate-spin shrink-0" />
                <span className="text-xs font-black text-blue-700 uppercase tracking-wide">
                  AI is parsing your pattern description…
                </span>
              </div>
              <div className="w-full bg-blue-100 rounded-full h-1.5 overflow-hidden">
                <div className="bg-blue-500 h-full rounded-full animate-pulse" style={{ width: '60%' }} />
              </div>
              <p className="text-[10px] font-bold text-blue-500 mt-2">
                This runs in the background via Celery. You&apos;ll be redirected automatically when done.
              </p>
            </div>
          )}

          {/* ── Actions ── */}
          <div className="flex flex-col md:flex-row items-center justify-end gap-4 pt-10 border-t border-gray-50">
            <button
              type="button"
              onClick={() => router.push('/patterns')}
              className="w-full md:w-auto px-8 py-4 bg-gray-100 text-gray-600 rounded-2xl font-black text-xs uppercase tracking-widest hover:bg-gray-200 transition-all flex items-center justify-center gap-3"
            >
              <ArrowLeft size={16} />
              Back to Patterns
            </button>
            <button
              type="submit"
              disabled={loading || generating || (activeTab === 'manual' && sections.length === 0)}
              className="w-full md:w-auto px-10 py-4 bg-emerald-600 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-2xl shadow-emerald-500/20 hover:bg-emerald-700 transition-all flex items-center justify-center gap-3 active:scale-95 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Submitting…
                </>
              ) : generating ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  {activeTab === 'manual' ? <CheckCircle size={18} /> : <Wand2 size={18} />}
                  {activeTab === 'manual' ? 'Save Pattern' : 'Generate via AI'}
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {/* ── Tips card ── */}
      <div className="mt-12 bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
        <div className="p-6 border-b border-gray-50 bg-white/50 flex items-center gap-3">
          <Type className="text-amber-500" size={20} />
          <h2 className="text-lg font-black text-gray-900 uppercase tracking-tight">How It Works</h2>
        </div>
        <div className="p-10">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
            {[
              { icon: GraduationCap, label: '1. Pick Class & Subject', sub: 'Select from Classes 1-12 and any CBSE subject', color: 'text-blue-500',    bg: 'bg-blue-50' },
              { icon: FileText,      label: '2. Choose Exam Type',     sub: 'PT-1/2/3, Half-Yearly, Board, Annual or Custom', color: 'text-emerald-500', bg: 'bg-emerald-50' },
              { icon: Sparkles,      label: '3. Pattern Auto-Loads',   sub: 'Official CBSE sections fill in automatically',   color: 'text-amber-500',   bg: 'bg-amber-50' },
              { icon: Layout,        label: '4. Edit & Save',          sub: 'Tweak marks, counts or instructions, then save', color: 'text-indigo-500',  bg: 'bg-indigo-50' },
            ].map((tip, i) => (
              <div key={i} className="flex flex-col items-center text-center group">
                <div className={`w-16 h-16 ${tip.bg} ${tip.color} rounded-2xl flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-500`}>
                  <tip.icon size={28} />
                </div>
                <h4 className="font-black text-gray-900 text-sm mb-1">{tip.label}</h4>
                <p className="text-[10px] font-bold text-gray-400 uppercase leading-tight">{tip.sub}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
