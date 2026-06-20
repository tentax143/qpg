'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { 
  ArrowLeft, Edit, Trash2, PenTool, Calendar, 
  User, Hash, Zap, BookOpen, Layers, 
  ChevronRight, ChevronDown, ChevronUp, Code,
  Settings, Info, ShieldCheck, Download, Plus,
  Clock, GraduationCap, CheckCircle, FileText
} from 'lucide-react';
import apiClient from '@/lib/api';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function PatternDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const [pattern, setPattern] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [showJson, setShowJson] = useState(false);
  const [expandedSections, setExpandedSections] = useState({});

  useEffect(() => {
    fetchPattern();
  }, [id]);

  const fetchPattern = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/patterns/${id}/`);
      setPattern(res.data);
    } catch (err) {
      setError('Failed to load pattern details');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this pattern?')) return;
    try {
      await apiClient.delete(`/patterns/${id}/`);
      router.push('/patterns');
    } catch (err) {
      setError('Failed to delete pattern');
    }
  };

  const toggleSection = (idx) => {
    setExpandedSections(prev => ({
      ...prev,
      [idx]: !prev[idx]
    }));
  };

  if (loading) return <LoadingSpinner message="Loading pattern details..." />;
  if (!pattern) return <div className="p-10 text-center text-gray-400 font-bold uppercase tracking-widest">Pattern not found</div>;

  return (
    <div className="w-full relative py-2 mb-20 px-4">
      {/* Breadcrumbs / Back */}
      <div className="flex items-center justify-between mb-8">
        <button 
          onClick={() => router.back()}
          className="flex items-center gap-2 text-gray-500 hover:text-gray-900 font-bold transition-all text-sm group"
        >
          <ArrowLeft size={18} className="group-hover:-translate-x-1 transition-transform" />
          Back to Patterns
        </button>
        <div className="flex items-center gap-2 text-[10px] font-black text-gray-400 uppercase tracking-widest">
          <Link href="/dashboard" className="hover:text-blue-600 transition-colors">Dashboard</Link>
          <ChevronRight size={10} />
          <Link href="/patterns" className="hover:text-blue-600 transition-colors">Patterns</Link>
          <ChevronRight size={10} />
          <span className="text-gray-900">View Pattern</span>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Header Card */}
      <div className="bg-white rounded-[40px] shadow-sm border border-gray-100 p-8 mb-8 relative overflow-hidden group">
        <div className="absolute top-0 right-0 w-64 h-64 bg-blue-50/50 rounded-full translate-x-24 -translate-y-24 group-hover:scale-110 transition-transform duration-700"></div>
        
        <div className="relative z-10">
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 mb-8">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h1 className="text-3xl font-black text-gray-900 tracking-tight uppercase">{pattern.name}</h1>
                {pattern.pattern_source === 'ai_generated' && (
                  <span className="px-3 py-1 bg-emerald-50 text-emerald-600 text-[10px] font-black uppercase tracking-widest rounded-full flex items-center gap-1.5 border border-emerald-100">
                    AI Generated
                  </span>
                )}
              </div>
              <p className="text-gray-400 font-bold text-sm uppercase tracking-tight">
                {pattern.pattern_source === 'ai_generated' ? 'AI-generated pattern' : 'Manually created pattern'} for Class {pattern.class_name} {pattern.subject}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 md:gap-8">
            <div className="flex items-center gap-2">
              <GraduationCap size={16} className="text-gray-400" />
              <span className="text-xs font-black text-gray-500 uppercase tracking-widest">Class:</span>
              <span className="text-sm font-black text-gray-900">{pattern.class_name || '—'}</span>
            </div>
            <div className="flex items-center gap-2">
              <BookOpen size={16} className="text-gray-400" />
              <span className="text-xs font-black text-gray-500 uppercase tracking-widest">Subject:</span>
              <span className="text-sm font-black text-gray-900 uppercase">{pattern.subject || '—'}</span>
            </div>
            <div className="flex items-center gap-2">
              <Zap size={16} className="text-emerald-500" />
              <span className="text-xs font-black text-gray-500 uppercase tracking-widest">Total Marks:</span>
              <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 text-xs font-black rounded-lg border border-emerald-100">{pattern.total_marks || 0}</span>
            </div>
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-blue-500" />
              <span className="text-xs font-black text-gray-500 uppercase tracking-widest">Total Questions:</span>
              <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs font-black rounded-lg border border-blue-100">{pattern.total_questions || 0}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Main Content Area */}
        <div className="lg:col-span-3 space-y-8">
          
          {/* Pattern Sections */}
          <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-50 bg-white/50 flex items-center gap-3">
              <Layers className="text-blue-600" size={20} />
              <h2 className="text-lg font-black text-gray-900 uppercase tracking-tight">Pattern Sections</h2>
            </div>
            <div className="p-8 space-y-4">
              {pattern.sections && pattern.sections.map((section, idx) => {
                const isCompound = Boolean(section.subject);
                return (
                <div key={idx} className="border border-gray-100 rounded-3xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
                  <button
                    onClick={() => toggleSection(idx)}
                    className="w-full flex items-center justify-between p-6 bg-white text-left group"
                  >
                    <div className="flex items-center gap-4">
                      <span className="inline-flex items-center justify-center w-10 h-10 bg-blue-600 text-white rounded-2xl font-black text-sm shrink-0">
                        {section.name || idx + 1}
                      </span>
                      <div>
                        {isCompound ? (
                          <p className="text-base font-black text-gray-900 tracking-tight">
                            § {section.name} — {section.subject}
                          </p>
                        ) : (
                          <p className="text-blue-600 font-black text-base uppercase tracking-tight">
                            {section.title || section.name || `Section ${idx + 1}`}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-1">
                          <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[9px] font-black uppercase rounded-full border border-blue-100">{section.marks}M</span>
                          <span className="px-2 py-0.5 bg-indigo-50 text-indigo-600 text-[9px] font-black uppercase rounded-full border border-indigo-100">
                            {section.questions ?? section.questions_count ?? '?'}Q
                          </span>
                          {isCompound && section.hots > 0 && (
                            <span className="px-2 py-0.5 bg-amber-50 text-amber-700 text-[9px] font-black uppercase rounded-full border border-amber-100">{section.hots} HOTS</span>
                          )}
                          {isCompound && section.cbq > 0 && (
                            <span className="px-2 py-0.5 bg-purple-50 text-purple-700 text-[9px] font-black uppercase rounded-full border border-purple-100">{section.cbq} CBQ</span>
                          )}
                          {section.internal_choice && (
                            <span className="px-2 py-0.5 bg-emerald-50 text-emerald-700 text-[9px] font-black uppercase rounded-full border border-emerald-100">
                              Choice{section.choices ? ` (${section.choices})` : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    {expandedSections[idx] ? <ChevronUp size={20} className="text-gray-400" /> : <ChevronDown size={20} className="text-gray-400 group-hover:text-blue-600" />}
                  </button>

                  {expandedSections[idx] && (
                    <div className="px-8 pb-8 pt-2 bg-slate-50/30">
                      <div className="space-y-6">

                        {/* Compound subject: question-type breakdown table */}
                        {isCompound ? (
                          <div className="space-y-3">
                            {/* Notes */}
                            {section.notes && (
                              <p className="text-xs text-gray-500 leading-relaxed bg-white rounded-2xl px-4 py-3 border border-gray-100">
                                {section.notes}
                              </p>
                            )}
                            {/* Question types mini-table */}
                            {section.question_types?.length > 0 && (
                              <div className="rounded-2xl overflow-hidden border border-gray-100">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="bg-gray-50 border-b border-gray-100">
                                      <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Q Range</th>
                                      <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Type</th>
                                      <th className="text-center px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Count</th>
                                      <th className="text-center px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Each</th>
                                      <th className="text-center px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Total</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {section.question_types.map((qt, qi) => (
                                      <tr key={qi} className="border-t border-gray-50 hover:bg-blue-50/30 transition-colors">
                                        <td className="px-3 py-2 font-mono text-[10px] font-bold text-gray-700">{qt.range || `${qt.count}Q`}</td>
                                        <td className="px-3 py-2 text-gray-700">{qt.type}</td>
                                        <td className="px-3 py-2 text-center font-bold text-gray-700">{qt.count}</td>
                                        <td className="px-3 py-2 text-center font-bold text-gray-700">{qt.marks_each}M</td>
                                        <td className="px-3 py-2 text-center font-black text-blue-700">{qt.total ?? qt.count * qt.marks_each}M</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        ) : (
                        /* Traditional section: existing metadata layout */
                        <div className="flex flex-wrap items-center gap-12 border-b border-gray-100 pb-6">
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <Zap size={14} className="text-gray-400" />
                              <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Marks per Question:</p>
                            </div>
                            <p className="text-sm font-black text-gray-900">{section.marks_per_question || 1}</p>
                          </div>
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <Layers size={14} className="text-gray-400" />
                              <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Question Types:</p>
                            </div>
                            <div className="flex gap-2">
                              {section.question_types ? (
                                Array.isArray(section.question_types) ? section.question_types.map((t, i) => (
                                  <span key={i} className="text-sm font-black text-gray-900">{typeof t === 'string' ? t : t.type}{i < section.question_types.length - 1 ? ',' : ''}</span>
                                )) : <span className="text-sm font-black text-gray-900">{section.question_types}</span>
                              ) : <span className="text-sm font-black text-gray-900">Mixed</span>}
                            </div>
                          </div>
                        </div>
                        )}

                        {/* Instructions */}
                        {(section.instructions || section.special_instructions || section.passage_instruction || section.extract_instruction || section.passage_config?.enabled) && (
                          <div className="space-y-3">
                            <div className="flex items-center gap-2">
                              <ShieldCheck size={16} className="text-blue-500" />
                              <h4 className="text-[11px] font-black text-gray-900 uppercase tracking-wider">Instructions & Guidelines:</h4>
                            </div>
                            <div className="p-4 bg-blue-50/50 rounded-2xl border border-blue-100/50 space-y-3">
                              {(section.instructions || section.special_instructions) && (
                                <div className="space-y-2">
                                  {Array.isArray(section.instructions || section.special_instructions) ? (section.instructions || section.special_instructions).map((inst, i) => (
                                    <p key={i} className="text-sm font-medium text-gray-700 leading-relaxed italic border-l-2 border-blue-200 pl-3">
                                      {inst}
                                    </p>
                                  )) : (
                                    <p className="text-sm font-medium text-gray-700 leading-relaxed italic border-l-2 border-blue-200 pl-3">
                                      {section.instructions || section.special_instructions}
                                    </p>
                                  )}
                                </div>
                              )}
                              
                              {section.passage_config?.enabled && (
                                <div className="flex flex-col gap-2 bg-white/50 p-4 rounded-xl border border-blue-100 shadow-sm">
                                  <div className="flex items-center gap-2 mb-1">
                                    <BookOpen size={16} className="text-blue-600" />
                                    <span className="text-[10px] font-black text-blue-900 uppercase">Passage Configuration</span>
                                  </div>
                                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                                    <div className="bg-white/80 p-2 rounded-lg border border-blue-50">
                                      <p className="text-[8px] font-black text-blue-400 uppercase">Type</p>
                                      <p className="text-xs font-bold text-blue-900 uppercase">{section.passage_config.type || 'General'}</p>
                                    </div>
                                    <div className="bg-white/80 p-2 rounded-lg border border-blue-50">
                                      <p className="text-[8px] font-black text-blue-400 uppercase">Word Range</p>
                                      <p className="text-xs font-bold text-blue-900">{section.passage_config.word_min} - {section.passage_config.word_max}</p>
                                    </div>
                                    {section.passage_config.topics && section.passage_config.topics.length > 0 && (
                                      <div className="col-span-2 bg-white/80 p-2 rounded-lg border border-blue-50">
                                        <p className="text-[8px] font-black text-blue-400 uppercase">Topics</p>
                                        <p className="text-xs font-bold text-blue-900">{section.passage_config.topics.join(', ')}</p>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}

                              {section.passage_instruction && (
                                <div className="flex items-start gap-3 bg-white/50 p-3 rounded-xl border border-blue-100 italic">
                                  <BookOpen size={14} className="text-blue-600 mt-1 shrink-0" />
                                  <p className="text-xs font-bold text-blue-900 leading-tight">{section.passage_instruction}</p>
                                </div>
                              )}
                              {section.extract_instruction && (
                                <div className="flex items-start gap-3 bg-white/50 p-3 rounded-xl border border-indigo-100 italic">
                                  <FileText size={14} className="text-indigo-600 mt-1 shrink-0" />
                                  <p className="text-xs font-bold text-indigo-900 leading-tight">{section.extract_instruction}</p>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Question Distribution (Alternative Schema) */}
                        {section.question_distribution && section.question_distribution.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center gap-2 text-gray-400">
                              <Layers size={16} />
                              <h4 className="text-[11px] font-black uppercase tracking-wider">Question Breakdown:</h4>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                              {section.question_distribution.map((qd, i) => (
                                <div key={i} className="flex items-center justify-between p-4 bg-white border border-gray-100 rounded-2xl shadow-sm hover:border-blue-200 transition-colors">
                                  <div>
                                    <p className="text-xs font-black text-gray-900 uppercase">{qd.type}</p>
                                    <p className="text-[9px] font-bold text-gray-400 uppercase tracking-tight">Difficulty: {qd.difficulty || 'Mixed'}</p>
                                  </div>
                                  <div className="text-right">
                                    <p className="text-xs font-black text-blue-600">{qd.marks_each}m × {qd.count}</p>
                                    <p className="text-[9px] font-bold text-gray-400 uppercase tracking-tight">Total: {qd.total_marks || (qd.marks_each * qd.count)}m</p>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Constraints */}
                        {section.constraints && (
                          <div className="space-y-3">
                            <div className="flex items-center gap-2">
                              <Settings size={16} className="text-amber-500" />
                              <h4 className="text-[11px] font-black text-gray-900 uppercase tracking-wider">Constraints:</h4>
                            </div>
                            <div className="flex flex-wrap gap-3">
                              {typeof section.constraints === 'object' && !Array.isArray(section.constraints) ? (
                                Object.entries(section.constraints).map(([key, value], i) => (
                                  <div key={i} className="px-3 py-2 bg-amber-50 border border-amber-100 rounded-xl">
                                    <span className="text-[9px] font-black text-amber-400 uppercase tracking-tighter block mb-0.5">{key.replace('_', ' ')}</span>
                                    <span className="text-xs font-bold text-amber-700">
                                      {typeof value === 'object' ? JSON.stringify(value) : value}
                                    </span>
                                  </div>
                                ))
                              ) : Array.isArray(section.constraints) ? (
                                section.constraints.map((c, i) => (
                                  <span key={i} className="px-3 py-1 bg-amber-50 text-amber-600 text-[10px] font-black uppercase rounded-lg border border-amber-100">{c}</span>
                                ))
                              ) : (
                                <p className="text-xs font-bold text-amber-700 bg-amber-50 p-3 rounded-xl w-full border border-amber-100">{section.constraints}</p>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Subsections if they exist */}
                        {section.subsections && section.subsections.length > 0 && (
                          <div className="space-y-3">
                            <div className="flex items-center gap-2 text-gray-400">
                              <Plus size={16} />
                              <h4 className="text-[11px] font-black uppercase tracking-wider">Subsections:</h4>
                            </div>
                            <div className="space-y-3">
                              {section.subsections.map((subsec, sidx) => (
                                <div key={sidx} className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
                                  <div className="flex items-center justify-between p-4 border-b border-gray-50">
                                    <span className="text-sm font-black text-gray-800">{subsec.name}</span>
                                    <div className="flex items-center gap-3">
                                      <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 text-[10px] font-black rounded border border-emerald-100">{subsec.marks} marks</span>
                                      <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-black rounded border border-blue-100">{subsec.questions_count} Q</span>
                                    </div>
                                  </div>
                                  {subsec.extract_instruction && (
                                    <div className="p-3 bg-indigo-50/30 flex items-start gap-3">
                                      <FileText size={12} className="text-indigo-400 mt-1 shrink-0" />
                                      <p className="text-[10px] font-bold text-indigo-700 leading-tight">{subsec.extract_instruction}</p>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Question Range (traditional sections only) */}
                        {!isCompound && (
                          <div className="flex items-center gap-2 pt-4 border-t border-gray-50">
                            <Clock size={14} className="text-gray-300" />
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                              Covers Questions {section.start_q || '—'} to {section.end_q || '—'}
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
              })}
            </div>
          </div>

          {/* Teacher Input / Prompt */}
          {pattern.ai_prompt && (
            <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
              <div className="p-6 border-b border-gray-50 bg-white/50 flex items-center gap-3">
                <h2 className="text-lg font-black text-gray-900 uppercase tracking-tight">Original Teacher Input (AI Generated)</h2>
              </div>
              <div className="p-8">
                <div className="p-6 bg-gray-50 rounded-2xl border border-gray-200/50">
                  <p className="text-gray-600 font-medium leading-relaxed whitespace-pre-wrap italic">
                    {pattern.ai_prompt}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* RAW JSON Collapsible */}
          <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
            <button 
              onClick={() => setShowJson(!showJson)}
              className="w-full p-6 border-b border-gray-50 bg-white/50 flex items-center justify-between group"
            >
              <div className="flex items-center gap-3">
                <Code className="text-gray-400" size={20} />
                <h2 className="text-lg font-black text-gray-900 uppercase tracking-tight">Raw JSON Structure</h2>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">{showJson ? 'Hide' : 'Toggle'}</span>
                {showJson ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </button>
            {showJson && (
              <div className="p-8 bg-[#0f172a]">
                <pre className="text-blue-400 font-mono text-xs overflow-x-auto custom-scrollbar leading-relaxed">
                  {JSON.stringify(pattern.sections, null, 2)}
                </pre>
              </div>
            )}
          </div>

        </div>

        {/* Sidebar Actions/Details */}
        <div className="space-y-8">
          
          <div className="flex justify-end">
            <Link href="/patterns" className="text-xs font-bold text-gray-400 hover:text-gray-900 flex items-center gap-2 transition-colors">
              <ArrowLeft size={14} />
              Back to Patterns
            </Link>
          </div>

          {/* Actions */}
          <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-50 flex items-center gap-3 bg-gray-50/30">
              <Settings size={18} className="text-blue-600" />
              <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Actions</h3>
            </div>
            <div className="p-6 space-y-3">
              <Link
                href={`/pattern/${pattern.id}/edit`}
                className="w-full py-4 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-[0.2em] flex items-center justify-center gap-3 hover:bg-blue-600 transition-all shadow-xl shadow-blue-500/10"
              >
                <Edit size={16} />
                Edit Pattern
              </Link>
              <Link
                href={`/generator?pattern=${pattern.id}`}
                className="w-full py-4 bg-emerald-600 text-white rounded-2xl font-black text-xs uppercase tracking-[0.2em] flex items-center justify-center gap-3 hover:bg-emerald-700 transition-all shadow-xl shadow-emerald-500/10"
              >
                <PenTool size={16} />
                Generate Paper
              </Link>
              <button
                onClick={handleDelete}
                className="w-full py-4 bg-red-50 text-red-600 rounded-2xl font-black text-xs uppercase tracking-[0.2em] flex items-center justify-center gap-3 hover:bg-red-600 hover:text-white transition-all"
              >
                <Trash2 size={16} />
                Delete
              </button>
            </div>
          </div>

          {/* Details */}
          <div className="bg-white rounded-[32px] shadow-sm border border-gray-100 overflow-hidden">
            <div className="p-6 border-b border-gray-50 flex items-center gap-3 bg-gray-50/30">
              <Info size={18} className="text-blue-600" />
              <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Details</h3>
            </div>
            <div className="p-6 space-y-6">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Created By:</span>
                <span className="text-xs font-bold text-gray-900">{pattern.created_by?.username || 'System'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Created At:</span>
                <span className="text-xs font-bold text-gray-900">
                  {new Date(pattern.created_at).toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' })}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Updated At:</span>
                <span className="text-xs font-bold text-gray-900">
                  {new Date(pattern.updated_at).toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' })}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Pattern ID:</span>
                <span className="text-xs font-bold text-gray-900">#{pattern.id}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Source:</span>
                <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded-full ${
                  pattern.pattern_source === 'ai_generated' ? 'bg-emerald-50 text-emerald-600' : 'bg-blue-50 text-blue-600'
                }`}>
                  {pattern.pattern_source === 'ai_generated' ? 'AI Generated' : 'Manual'}
                </span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
