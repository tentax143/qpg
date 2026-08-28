'use client';

import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import {
  Plus, Trash2, Edit, Layers, Info, BookOpen, RefreshCw,
  GraduationCap, AlertCircle, FileText, Eye,
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

// Blueprints are now a per-pattern unit plan: the pattern sets the structure, the blueprint says
// which unit each question is drawn from. Rows are therefore grouped BY PATTERN — that grouping is
// the clearest statement of the relationship, and the old flat list of "templates" and "blueprints"
// (two abandoned structure-style concepts) is gone.

export default function BlueprintsPage() {
  const [blueprints, setBlueprints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => { fetchData(); }, []);

  async function fetchData() {
    try {
      setLoading(true);
      setError(null);
      const res = await apiClient.get('/blueprints/');
      const rows = res.data?.results || (Array.isArray(res.data) ? res.data : []);
      setBlueprints(rows);
    } catch (err) {
      console.error('Failed to load blueprints', err);
      setError('Could not load blueprints. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this blueprint? The pattern it plans is not affected.')) return;
    try {
      await apiClient.delete(`/blueprints/${id}/`);
      setSuccess('Blueprint deleted.');
      fetchData();
    } catch {
      setError('Could not delete that blueprint.');
    }
  }

  // Blueprints that predate the per-pattern model carry no pattern and no unit map — their old
  // payload described a structure, which is the pattern's job now. Surfaced separately rather than
  // hidden, so a school can see what to clean up.
  const { grouped, legacy } = useMemo(() => {
    const g = new Map();
    const l = [];
    for (const bp of blueprints) {
      if (!bp.pattern_id) { l.push(bp); continue; }
      const key = bp.pattern_id;
      if (!g.has(key)) {
        g.set(key, {
          patternId: key,
          patternName: bp.pattern_name || `Pattern #${key}`,
          totalMarks: bp.pattern_total_marks,
          classSubject: `Class ${bp.class_name} ${bp.subject}`,
          items: [],
        });
      }
      g.get(key).items.push(bp);
    }
    return { grouped: [...g.values()], legacy: l };
  }, [blueprints]);

  return (
    <div className="w-full py-2 mb-20 px-4">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white shadow-sm border border-gray-100 rounded-xl flex items-center justify-center">
            <Layers className="text-cyan-600" size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight">Blueprints</h1>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">
              Which unit each question of a pattern comes from
            </p>
          </div>
        </div>
        <Link href="/blueprints/plan"
              className="flex items-center gap-2 bg-cyan-600 text-white px-6 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-cyan-200 hover:bg-cyan-700 transition-all active:scale-95">
          <Plus size={16} /> New Blueprint
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}

      <div className="mb-6 p-4 bg-cyan-50 border border-cyan-100 rounded-2xl flex gap-3">
        <Info className="text-cyan-600 shrink-0 mt-0.5" size={18} />
        <p className="text-xs font-semibold text-cyan-900 leading-relaxed">
          A <strong>pattern</strong> sets the paper&apos;s structure — sections, question numbers,
          types, marks. A <strong>blueprint</strong> layers the syllabus on top: pin any question to
          the unit it must be set from. Attach one when you generate, and those questions come from
          exactly those units; everything you leave on Auto is distributed for you by CBSE mark
          weight. One pattern can have several blueprints — same structure, different units each term.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center gap-3 p-6 bg-white rounded-2xl border border-gray-100">
          <RefreshCw className="animate-spin text-cyan-600" size={18} />
          <span className="text-xs font-black text-gray-500 uppercase tracking-wider">Loading…</span>
        </div>
      ) : grouped.length === 0 && legacy.length === 0 ? (
        <div className="p-10 bg-white rounded-2xl border border-gray-100 text-center">
          <BookOpen className="mx-auto text-gray-200 mb-4" size={44} />
          <h3 className="text-lg font-black text-gray-900 mb-1">No blueprints yet</h3>
          <p className="text-sm text-gray-500 font-semibold mb-6 max-w-lg mx-auto">
            Blueprints are optional. Without one, QPG spreads questions across the chapters you tick
            at generation time. Create one when you need a specific question to come from a specific
            unit.
          </p>
          <Link href="/blueprints/plan"
                className="inline-flex items-center gap-2 bg-cyan-600 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-wider shadow-xl shadow-cyan-200 hover:bg-cyan-700 transition-all active:scale-95">
            <Plus size={16} /> Create your first blueprint
          </Link>
        </div>
      ) : (
        <>
          {grouped.map(group => (
            <div key={group.patternId} className="bg-white rounded-2xl border border-gray-100 shadow-sm mb-5 overflow-hidden">
              <div className="px-6 py-4 bg-gray-50/70 border-b border-gray-100 flex flex-wrap items-center gap-3">
                <GraduationCap className="text-gray-400 shrink-0" size={16} />
                <h3 className="font-black text-gray-900 text-sm flex-1 min-w-[12rem]">
                  {group.patternName}
                </h3>
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-wider">
                  {group.classSubject}{group.totalMarks ? ` · ${group.totalMarks}M` : ''}
                </span>
                <Link href={`/blueprints/plan?pattern=${group.patternId}`}
                      className="text-[10px] font-black text-cyan-700 uppercase tracking-wider hover:underline">
                  + Add another
                </Link>
              </div>
              <div className="divide-y divide-gray-50">
                {group.items.map(bp => (
                  <div key={bp.id} className="px-6 py-4 flex flex-wrap items-center gap-4">
                    <div className="flex-1 min-w-[14rem]">
                      <Link href={`/blueprints/${bp.id}`}
                            className="font-black text-gray-800 text-sm hover:text-cyan-700 hover:underline">
                        {bp.name || `Blueprint #${bp.id}`}
                      </Link>
                      <p className="text-[11px] font-bold text-gray-400 mt-0.5 truncate"
                         title={(bp.units_used || []).join(', ')}>
                        {(bp.units_used || []).length
                          ? (bp.units_used || []).join(' · ')
                          : 'No units assigned'}
                      </p>
                    </div>
                    <span className={`px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-wider ${
                      bp.mapped_questions
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-amber-50 text-amber-700'}`}>
                      {bp.mapped_questions
                        ? `${bp.mapped_questions} question${bp.mapped_questions === 1 ? '' : 's'} pinned`
                        : 'Nothing pinned'}
                    </span>
                    <div className="flex items-center gap-2">
                      <Link href={`/blueprints/${bp.id}`}
                            className="p-2.5 rounded-xl text-gray-400 hover:bg-gray-100 hover:text-gray-700 transition-all"
                            title="View the full plan">
                        <Eye size={16} />
                      </Link>
                      <Link href={`/blueprints/plan?id=${bp.id}`}
                            className="p-2.5 rounded-xl text-gray-400 hover:bg-cyan-50 hover:text-cyan-600 transition-all"
                            title="Edit">
                        <Edit size={16} />
                      </Link>
                      <button onClick={() => handleDelete(bp.id)}
                              className="p-2.5 rounded-xl text-gray-400 hover:bg-red-50 hover:text-red-600 transition-all"
                              title="Delete">
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {legacy.length > 0 && (
            <div className="bg-white rounded-2xl border border-amber-200 shadow-sm overflow-hidden">
              <div className="px-6 py-4 bg-amber-50 border-b border-amber-100 flex items-center gap-3">
                <AlertCircle className="text-amber-600 shrink-0" size={16} />
                <h3 className="font-black text-amber-900 text-sm flex-1">
                  Old blueprints ({legacy.length})
                </h3>
              </div>
              <div className="px-6 py-4">
                <p className="text-xs font-semibold text-gray-500 leading-relaxed mb-4">
                  These were made before blueprints were tied to a pattern. They describe a paper
                  structure, which is now an <Link href="/patterns" className="underline font-black">Exam
                  Pattern</Link>&apos;s job, and they are not used when generating. Delete them, or
                  create a new blueprint against the pattern you actually use.
                </p>
                <div className="divide-y divide-gray-50">
                  {legacy.map(bp => (
                    <div key={bp.id} className="py-3 flex flex-wrap items-center gap-4">
                      <FileText className="text-gray-300 shrink-0" size={16} />
                      <Link href={`/blueprints/${bp.id}`}
                            className="flex-1 min-w-[12rem] text-sm font-bold text-gray-600 hover:text-gray-900 hover:underline">
                        {bp.name || bp.code || `Blueprint #${bp.id}`}
                      </Link>
                      <span className="text-[11px] font-black text-gray-400 uppercase tracking-wider">
                        Class {bp.class_name} {bp.subject}
                      </span>
                      <button onClick={() => handleDelete(bp.id)}
                              className="p-2.5 rounded-xl text-gray-400 hover:bg-red-50 hover:text-red-600 transition-all"
                              title="Delete">
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
