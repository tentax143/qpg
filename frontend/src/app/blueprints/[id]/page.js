'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Edit, Trash2, Layers, Info, AlertTriangle, GraduationCap,
  Hash, PenTool, Calendar, User, BookOpen, CheckCircle2, FileText,
} from 'lucide-react';
import apiClient from '@/lib/api';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

// Read-only view of one blueprint: every printed question of its pattern, next to the unit it is
// pinned to. The editor could already show this, but only as 38 dropdowns — and only when the
// class+subject still had uploaded material. A teacher checking "what did I set for the
// half-yearly?" needs to read the plan, not re-open a form that can save over it.

export default function BlueprintDetailPage() {
  const { id } = useParams();
  const router = useRouter();

  const [blueprint, setBlueprint] = useState(null);
  const [scaffold, setScaffold] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get(`/blueprints/${id}/`);
      setBlueprint(res.data);
      if (res.data?.pattern_id) {
        // The pattern supplies the question numbers this map is addressed by. If it has since
        // been deleted or is unreachable, still show the raw plan rather than an error page.
        try {
          const sc = await apiClient.get(`/patterns/${res.data.pattern_id}/blueprint-scaffold/`);
          setScaffold(sc.data);
        } catch {
          setScaffold(null);
        }
      }
    } catch (err) {
      setError(err.response?.status === 404
        ? 'That blueprint no longer exists.'
        : 'Could not load this blueprint.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete() {
    if (!confirm('Delete this blueprint? The pattern it plans is not affected, and papers already '
                 + 'generated with it keep their questions.')) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/blueprints/${id}/`);
      setSuccess('Blueprint deleted. Returning to the list…');
      setTimeout(() => router.push('/blueprints'), 1000);
    } catch {
      setError('Could not delete that blueprint.');
      setDeleting(false);
    }
  }

  // {section_id: {questions: {qnum: unit}, units: [unit]}} — read straight off the saved map so
  // the page shows exactly what generation will apply, malformed entries included.
  const mapBySection = useMemo(() => {
    const out = {};
    for (const entry of (blueprint?.unit_map?.sections || [])) {
      if (!entry?.section_id) continue;
      out[entry.section_id] = {
        questions: entry.questions || {},
        units: entry.units || [],
      };
    }
    return out;
  }, [blueprint]);

  const stats = useMemo(() => {
    let pinned = 0;
    let sectionWide = 0;
    for (const sec of Object.values(mapBySection)) {
      pinned += Object.keys(sec.questions || {}).length;
      if ((sec.units || []).length) sectionWide += 1;
    }
    const printed = (scaffold?.sections || [])
      .reduce((n, s) => n + s.questions.filter(q => q.unit_applicable).length, 0);
    return { pinned, sectionWide, printed, auto: Math.max(printed - pinned, 0) };
  }, [mapBySection, scaffold]);

  // A pinned unit with no uploaded material still generates, but ungrounded — the worker logs the
  // same warning. Saying it here is the only chance a teacher gets to fix it before the paper.
  const unitsWithoutMaterial = useMemo(() => {
    if (!scaffold || !(scaffold.units || []).length) return [];
    const known = new Set(scaffold.units);
    return (blueprint?.units_used || []).filter(u => !known.has(u));
  }, [scaffold, blueprint]);

  if (loading) return <LoadingSpinner message="Loading blueprint…" />;

  if (!blueprint) {
    return (
      <div className="w-full py-2 px-4">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} />}
        <Link href="/blueprints"
              className="inline-flex items-center gap-2 px-5 py-3 bg-gray-100 text-gray-600 rounded-xl font-black text-xs uppercase tracking-wider hover:bg-gray-200 transition-all">
          <ArrowLeft size={16} /> Back to blueprints
        </Link>
      </div>
    );
  }

  const isLegacy = !blueprint.pattern_id;

  return (
    <div className="w-full py-2 mb-20 px-4">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white shadow-sm border border-gray-100 rounded-xl flex items-center justify-center">
            <Layers className="text-cyan-600" size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">
              {blueprint.name || `Blueprint #${blueprint.id}`}
            </h1>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
              {blueprint.pattern_name || 'No pattern — old blueprint'}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/blueprints"
                className="px-5 py-3 bg-gray-100 text-gray-600 rounded-xl font-black text-xs uppercase tracking-wider hover:bg-gray-200 transition-all flex items-center gap-2">
            <ArrowLeft size={16} /> Back
          </Link>
          {!isLegacy && (
            <>
              <Link href={`/generator?pattern=${blueprint.pattern_id}&blueprint=exam_${blueprint.id}`}
                    className="px-5 py-3 bg-emerald-600 text-white rounded-xl font-black text-xs uppercase tracking-wider hover:bg-emerald-700 transition-all flex items-center gap-2 shadow-lg shadow-emerald-100">
                <PenTool size={16} /> Generate with this
              </Link>
              <Link href={`/blueprints/plan?id=${blueprint.id}`}
                    className="px-5 py-3 bg-cyan-600 text-white rounded-xl font-black text-xs uppercase tracking-wider hover:bg-cyan-700 transition-all flex items-center gap-2 shadow-lg shadow-cyan-100">
                <Edit size={16} /> Edit
              </Link>
            </>
          )}
          <button onClick={handleDelete} disabled={deleting}
                  className="px-5 py-3 bg-red-50 text-red-600 rounded-xl font-black text-xs uppercase tracking-wider hover:bg-red-100 transition-all flex items-center gap-2 disabled:opacity-50">
            <Trash2 size={16} /> {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}

      {/* ── Facts ─────────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-6">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          <Fact icon={GraduationCap} label="Class & subject"
                value={`Class ${blueprint.class_name || '—'} · ${blueprint.subject || '—'}`} />
          <Fact icon={FileText} label="Pattern"
                value={blueprint.pattern_name || 'None'}
                href={blueprint.pattern_id ? `/pattern/${blueprint.pattern_id}` : null} />
          <Fact icon={User} label="Created by"
                value={blueprint.created_by?.username || 'Unknown'} />
          <Fact icon={Calendar} label="Last updated"
                value={blueprint.updated_at
                  ? new Date(blueprint.updated_at).toLocaleDateString('en-IN',
                    { day: 'numeric', month: 'short', year: 'numeric' })
                  : '—'} />
        </div>

        {!isLegacy && (
          <div className="mt-5 pt-5 border-t border-gray-50 flex flex-wrap items-center gap-3 text-[11px] font-black uppercase tracking-wider">
            <span className="px-3 py-1.5 bg-cyan-50 text-cyan-700 rounded-full">
              {stats.pinned} question{stats.pinned === 1 ? '' : 's'} pinned
            </span>
            {stats.sectionWide > 0 && (
              <span className="px-3 py-1.5 bg-blue-50 text-blue-700 rounded-full">
                {stats.sectionWide} section-wide
              </span>
            )}
            {scaffold && (
              <span className="px-3 py-1.5 bg-gray-100 text-gray-500 rounded-full">
                {stats.auto} left on auto
              </span>
            )}
            <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-full">
              {(blueprint.units_used || []).length} unit
              {(blueprint.units_used || []).length === 1 ? '' : 's'} used
            </span>
          </div>
        )}
      </div>

      {isLegacy && (
        <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
          <AlertTriangle className="text-amber-600 shrink-0 mt-0.5" size={18} />
          <div className="text-xs font-semibold text-amber-900 leading-relaxed">
            <p className="mb-2">
              This blueprint was made before blueprints were tied to a pattern. It describes a paper
              structure, which is an{' '}
              <Link href="/patterns" className="underline font-black">Exam Pattern</Link>&apos;s job,
              so it is <strong>not used when generating</strong>.
            </p>
            <p>
              Delete it, or <Link href="/blueprints/plan" className="underline font-black">create a
              new blueprint</Link> against the pattern you actually generate from.
            </p>
          </div>
        </div>
      )}

      {!isLegacy && !scaffold && (
        <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
          <AlertTriangle className="text-amber-600 shrink-0 mt-0.5" size={18} />
          <p className="text-xs font-semibold text-amber-900 leading-relaxed">
            The pattern this blueprint plans could not be loaded — it may have been deleted. The
            saved plan is shown below by question number, but it will not apply to any paper.
          </p>
        </div>
      )}

      {unitsWithoutMaterial.length > 0 && (
        <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3 mb-6">
          <AlertTriangle className="text-amber-600 shrink-0 mt-0.5" size={18} />
          <p className="text-xs font-semibold text-amber-900 leading-relaxed">
            No uploaded material for{' '}
            <strong>{unitsWithoutMaterial.join(', ')}</strong>. Questions pinned to those units will
            be written from the model&apos;s own knowledge with no textbook grounding —{' '}
            <Link href="/materials/upload" className="underline font-black">upload the material</Link>{' '}
            or re-pin those questions.
          </p>
        </div>
      )}

      {/* ── The plan ──────────────────────────────────────────────────────── */}
      {scaffold ? (
        scaffold.sections.map((sec) => {
          const secMap = mapBySection[sec.section_id] || { questions: {}, units: [] };
          const sectionUnits = secMap.units || [];
          const pinnedHere = Object.keys(secMap.questions || {}).length;
          return (
            <div key={sec.section_id}
                 className="bg-white rounded-2xl border border-gray-100 shadow-sm mb-5 overflow-hidden">
              <div className="px-6 py-4 bg-gray-50/70 border-b border-gray-100 flex flex-wrap items-center gap-3">
                <span className="px-2.5 py-1 bg-gray-900 text-white rounded-lg text-[10px] font-black tracking-widest">
                  {sec.section_id}
                </span>
                <h3 className="font-black text-gray-900 text-sm flex-1 min-w-[12rem]">{sec.name}</h3>
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-wider">
                  {sec.questions.length || sec.questions_count} Q · {sec.marks}M
                </span>
                <span className={`px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-wider ${
                  pinnedHere || sectionUnits.length
                    ? 'bg-cyan-50 text-cyan-700'
                    : 'bg-gray-100 text-gray-400'}`}>
                  {sectionUnits.length
                    ? 'Whole section'
                    : pinnedHere ? `${pinnedHere} pinned` : 'All auto'}
                </span>
              </div>

              <div className="p-6">
                {sectionUnits.length > 0 && (
                  <div className="mb-5 p-4 bg-blue-50 border border-blue-100 rounded-xl flex items-center gap-3">
                    <BookOpen className="text-blue-600 shrink-0" size={16} />
                    <p className="text-xs font-bold text-blue-900">
                      Every question in this section is drawn from{' '}
                      <strong>{sectionUnits.join(', ')}</strong>.
                    </p>
                  </div>
                )}

                {sec.section_level_only ? (
                  !sectionUnits.length && (
                    <p className="text-xs font-semibold text-gray-400">
                      This section prints no individual question numbers and has no unit set, so it
                      is distributed automatically.
                    </p>
                  )
                ) : (
                  <div className="grid gap-2">
                    {sec.questions.map((q) => {
                      const unit = secMap.questions?.[q.qnum] || secMap.questions?.[String(q.qnum)];
                      return (
                        <div key={q.qnum}
                             className="flex flex-wrap items-center gap-3 py-1.5 border-b border-gray-50 last:border-0">
                          <span className="w-14 shrink-0 flex items-center gap-1 text-xs font-black text-gray-700">
                            <Hash size={12} className="text-gray-300" />{q.qnum}
                          </span>
                          <span className="w-44 shrink-0 text-[11px] font-bold text-gray-500 truncate"
                                title={`${q.type_label}${q.topic ? ` — ${q.topic}` : ''}`}>
                            {q.type_label}
                            {q.choice === 'internal' && <span className="ml-1 text-amber-600">(or)</span>}
                          </span>
                          <span className="w-12 shrink-0 text-[11px] font-black text-gray-400">
                            {q.marks}M
                          </span>
                          {!q.unit_applicable ? (
                            <span className="flex-1 min-w-[14rem] text-[11px] font-bold text-gray-400">
                              Not from a unit — {q.type === 'cbq' ? 'unseen passage' : 'general knowledge'}
                            </span>
                          ) : unit ? (
                            <span className="flex-1 min-w-[14rem] px-3 py-1.5 rounded-lg text-xs font-bold bg-cyan-50 text-cyan-900 border border-cyan-200 truncate"
                                  title={unit}>
                              {unit}
                            </span>
                          ) : sectionUnits.length ? (
                            <span className="flex-1 min-w-[14rem] px-3 py-1.5 rounded-lg text-xs font-bold bg-blue-50/60 text-blue-800 border border-blue-100 truncate">
                              {sectionUnits.join(', ')} <span className="text-blue-400">(section-wide)</span>
                            </span>
                          ) : (
                            <span className="flex-1 min-w-[14rem] px-3 py-1.5 text-[11px] font-bold text-gray-400">
                              Auto — QPG chooses, weighted by CBSE marks
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
        })
      ) : (
        // No pattern to lay the map over: list what was saved so it is at least readable.
        Object.keys(mapBySection).length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6 mb-5">
            <h3 className="font-black text-gray-900 text-sm mb-4">Saved plan</h3>
            {Object.entries(mapBySection).map(([sectionId, sec]) => (
              <div key={sectionId} className="mb-4 last:mb-0">
                <p className="text-[11px] font-black text-gray-500 uppercase tracking-wider mb-2">
                  {sectionId}
                </p>
                {(sec.units || []).length > 0 && (
                  <p className="text-xs font-bold text-blue-800 mb-2">
                    Whole section: {sec.units.join(', ')}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {Object.entries(sec.questions || {}).map(([qnum, unit]) => (
                    <span key={qnum}
                          className="px-3 py-1.5 rounded-lg text-[11px] font-bold bg-gray-50 border border-gray-200 text-gray-700">
                      Q{qnum} → {unit}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )
      )}

      {!isLegacy && stats.pinned > 0 && (
        <div className="p-4 bg-emerald-50 border border-emerald-100 rounded-2xl flex gap-3">
          <CheckCircle2 className="text-emerald-600 shrink-0 mt-0.5" size={18} />
          <p className="text-xs font-semibold text-emerald-900 leading-relaxed">
            Attach this blueprint on the generate page and those {stats.pinned} question
            {stats.pinned === 1 ? '' : 's'} will be set from exactly these units. Everything on
            Auto is distributed for you by CBSE mark weight.
          </p>
        </div>
      )}

      {!isLegacy && stats.pinned === 0 && stats.sectionWide === 0 && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-2xl flex gap-3">
          <Info className="text-amber-600 shrink-0 mt-0.5" size={18} />
          <p className="text-xs font-semibold text-amber-900 leading-relaxed">
            Nothing is pinned, so this blueprint would change nothing — the generate page does not
            offer it. <Link href={`/blueprints/plan?id=${blueprint.id}`} className="underline font-black">
            Pin some questions</Link> or delete it.
          </p>
        </div>
      )}
    </div>
  );
}

function Fact({ icon: Icon, label, value, href }) {
  const body = (
    <p className="text-sm font-black text-gray-800 truncate" title={value}>{value}</p>
  );
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 text-[10px] font-black text-gray-400 uppercase tracking-wider mb-1">
        <Icon size={12} /> {label}
      </p>
      {href ? <Link href={href} className="hover:underline">{body}</Link> : body}
    </div>
  );
}
