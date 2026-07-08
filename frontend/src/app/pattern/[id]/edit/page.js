'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft, Save, RefreshCw, Layers,
  Settings, Info, Calculator, FileText, BookOpen,
  GraduationCap, Hash, MessageCircle, Edit,
  ListOrdered, AlertTriangle
} from 'lucide-react';
import apiClient from '@/lib/api';
import { subjectOptions } from '@/lib/subjects';
import CustomSelect from '@/components/CustomSelect';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

// Canonical slot types (core/pattern_structure.py SLOT_TYPE_LABEL)
const SLOT_TYPE_LABELS = {
  mcq: 'MCQ', ar: 'Assertion-Reason', fill_blank: 'Fill in the blank',
  true_false: 'True/False', matching: 'Matching', one_word: 'One-word answer',
  error_correction: 'Error correction', rewrite: 'Rewrite the sentence',
  punctuation: 'Punctuation', vsa: 'Very Short Answer', sa: 'Short Answer',
  la: 'Long Answer', writing: 'Writing', cbq: 'Case-Based',
  extract: 'Extract-Based', map: 'Map-Based',
};

export default function EditPatternPage() {
  const { id } = useParams();
  const router = useRouter();
  const [pattern, setPattern] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const [formData, setFormData] = useState({
    name: '',
    class_name: '',
    subject: '',
    description: '',
    ai_prompt: ''
  });
  // Editable copy of sections for slot-authored patterns (question_slots).
  const [sections, setSections] = useState([]);
  const hasSlots = sections.some(s => s?.question_slots?.length > 0);

  useEffect(() => {
    fetchPattern();
  }, [id]);

  const fetchPattern = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/patterns/${id}/`);
      setPattern(res.data);
      setFormData({
        name: res.data.name || '',
        class_name: res.data.class_name || '',
        subject: res.data.subject || '',
        description: res.data.description || '',
        ai_prompt: res.data.ai_prompt || ''
      });
      setSections(JSON.parse(JSON.stringify(res.data.sections || [])));
    } catch (err) {
      setError('Failed to load pattern data');
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const updateSlot = (sIdx, slotIdx, field, value) => {
    setSections(prev => {
      const next = JSON.parse(JSON.stringify(prev));
      const slot = next[sIdx]?.question_slots?.[slotIdx];
      if (slot) {
        if (value === '' || value === null) delete slot[field];
        else slot[field] = value;
      }
      return next;
    });
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
        // Slot-authored patterns send the edited sections too; the server
        // re-validates the slots and re-derives counts/marks/question_types.
        const payload = hasSlots ? { ...formData, sections } : formData;
        await apiClient.put(`/patterns/${id}/`, payload);
        setSuccess('Pattern updated successfully!');
        fetchPattern(); // Refresh
        setTimeout(() => router.push(`/patterns`), 1500);
    } catch (err) {
        setError(err.response?.data?.detail || 'Failed to update pattern');
    } finally {
        setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    if (!formData.ai_prompt) {
        setError('Please provide a prompt to regenerate the pattern.');
        return;
    }
    setRegenerating(true);
    setError(null);
    setSuccess(null);
    try {
        // Regeneration runs async on a Celery worker (mirrors initial pattern generation).
        // Bounce straight back to the patterns list, which shows this pattern as "Regenerating"
        // until the task completes — staying here would just show a stale/blanked-out pattern.
        await apiClient.post(`/patterns/${id}/regenerate/`, {
            ai_prompt: formData.ai_prompt
        });
        router.push('/patterns');
    } catch (err) {
        setError(err.response?.data?.error || 'Failed to regenerate pattern');
        setRegenerating(false);
    }
  };

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <RefreshCw className="w-10 h-10 text-blue-600 animate-spin" />
        <p className="text-gray-500 font-black uppercase tracking-widest text-[10px]">Loading Pattern Data...</p>
      </div>
    </div>
  );
  
  if (!pattern) return <div className="p-10 text-center text-gray-400 font-bold uppercase tracking-widest">Pattern not found</div>;

  return (
    <div className="max-w-6xl mx-auto py-8 mb-20 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-10 bg-white p-6 rounded-[30px] border border-gray-100 shadow-sm relative overflow-hidden group">
        <div className="absolute top-0 right-0 w-32 h-32 bg-blue-50/50 rounded-full translate-x-12 -translate-y-12"></div>
        <div className="flex items-center gap-4 relative z-10">
          <div className="w-12 h-12 bg-blue-600 text-white rounded-2xl flex items-center justify-center shadow-lg shadow-blue-200">
            <Edit size={24} />
          </div>
          <div>
            <div className="flex items-center gap-3">
               <h1 className="text-2xl font-black text-gray-900 tracking-tight uppercase">Edit Pattern: {pattern.name}</h1>
               {pattern.pattern_source === 'ai_generated' && (
                 <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[8px] font-black uppercase tracking-widest rounded-md border border-blue-100">AI Generated</span>
               )}
            </div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Manage your exam structure and settings</p>
          </div>
        </div>
        <button onClick={() => router.back()} className="relative z-10 text-[10px] font-black text-gray-400 hover:text-gray-900 transition-colors flex items-center gap-2 uppercase tracking-[0.2em] bg-gray-50 px-4 py-2 rounded-xl border border-gray-100">
          <ArrowLeft size={14} />
          Back
        </button>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleUpdate} className="space-y-6">
        {/* Basic Information Section */}
        <section className="bg-white rounded-[40px] shadow-sm border border-gray-100 overflow-hidden">
          <div className="p-8 border-b border-gray-50 bg-gray-50/30">
            <div className="flex items-center gap-3 text-blue-600">
              <Info size={18} />
              <h2 className="text-xs font-black uppercase tracking-widest">Basic Information</h2>
            </div>
          </div>
          
          <div className="p-8 space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] flex items-center gap-2">
                  <FileText size={14} className="text-blue-500" /> Pattern Name
                </label>
                <input 
                  name="name" value={formData.name} onChange={handleChange}
                  className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-black text-gray-900 focus:bg-white focus:border-[#1e293b] focus:ring-4 focus:ring-[#1e293b]/5 transition-all outline-none"
                  required
                />
              </div>
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] flex items-center gap-2">
                  <GraduationCap size={14} className="text-blue-500" /> Class
                </label>
                <input 
                  name="class_name" value={formData.class_name} onChange={handleChange}
                  className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-black text-gray-900 focus:bg-white focus:border-[#1e293b] focus:ring-4 focus:ring-[#1e293b]/5 transition-all outline-none"
                  required
                />
              </div>
              <CustomSelect
                label="Subject"
                icon={BookOpen}
                value={formData.subject}
                onChange={(val) => handleChange({ target: { name: 'subject', value: val } })}
                options={subjectOptions}
                placeholder="Select Subject"
                className="space-y-3"
              />
            </div>

            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] flex items-center gap-2">
                <MessageCircle size={14} className="text-blue-500" /> Description
              </label>
              <textarea 
                name="description" value={formData.description} onChange={handleChange}
                className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-[#1e293b] focus:ring-4 focus:ring-[#1e293b]/5 transition-all outline-none min-h-[120px] resize-none"
                placeholder="Optional description of this pattern..."
              />
            </div>
          </div>
        </section>

        {/* Sections Display */}
        <section className="bg-white rounded-[40px] shadow-sm border border-gray-100 overflow-hidden text-gray-900">
          <div className="p-8 border-b border-gray-50 bg-gray-50/30 flex items-center justify-between">
            <div className="flex items-center gap-3 text-blue-600">
              <Layers size={18} />
              <h2 className="text-xs font-black uppercase tracking-widest">Sections (Read-Only - View Only)</h2>
            </div>
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest italic hidden md:block">
               {hasSlots ? 'Totals auto-derived from the per-question structure below'
                 : pattern.pattern_source === 'ai_generated' ? 'AI-generated patterns are immutable' : 'Modify this by creating a new pattern'}
            </p>
          </div>
          
          <div className="p-8">
            <div className="bg-blue-50/50 border border-blue-100 p-6 rounded-3xl mb-8 flex items-start gap-4">
               <div className="w-10 h-10 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center shrink-0">
                  <Info size={20} />
               </div>
               <div>
                  <p className="font-black text-blue-900 uppercase text-[10px] tracking-widest mb-1">Important Note</p>
                  <p className="text-xs font-bold text-blue-600/80 leading-relaxed uppercase">
                    {hasSlots
                      ? 'Section totals are derived automatically from the per-question structure. Edit individual questions in the editor below — counts and marks update on save.'
                      : 'Sections are read-only. The pattern structure cannot be edited after creation to maintain data integrity. To modify the structure, please create a new pattern instead.'}
                  </p>
               </div>
            </div>

            <div className="space-y-4">
              {pattern.sections?.map((section, idx) => (
                <div key={idx} className="bg-white border border-gray-100 p-6 rounded-3xl flex items-center justify-between shadow-sm group hover:border-blue-200 transition-all">
                  <div className="flex items-center gap-6">
                    <div>
                      <p className="font-black text-gray-900 uppercase text-xs tracking-tight mb-1">{section.name || `Section ${section.id}`}</p>
                      <div className="flex items-center gap-3">
                         <span className="text-[10px] font-black text-gray-400 uppercase">{section.questions_count} Questions</span>
                         <span className="w-1 h-1 bg-gray-300 rounded-full"></span>
                         <span className="text-[10px] font-black text-gray-400 uppercase">{section.marks} Marks Total</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                     <span className="px-3 py-1 bg-gray-50 text-gray-400 text-[10px] font-black uppercase rounded-lg border border-gray-100 group-hover:bg-blue-50 group-hover:text-blue-600 group-hover:border-blue-100 transition-all">
                        {section.marks}M
                     </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Per-Question Structure Editor (slot-authored patterns) */}
        {hasSlots && (
          <section className="bg-white rounded-[40px] shadow-sm border border-gray-100 overflow-hidden text-gray-900">
            <div className="p-8 border-b border-gray-50 bg-gray-50/30 flex items-center justify-between">
              <div className="flex items-center gap-3 text-teal-600">
                <ListOrdered size={18} />
                <h2 className="text-xs font-black uppercase tracking-widest">Per-Question Structure (Editable)</h2>
              </div>
              <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest italic hidden md:block">
                Type, topic, format, marks and choice per question
              </p>
            </div>

            <div className="p-8 space-y-8">
              {sections.map((section, sIdx) => (
                section?.question_slots?.length > 0 && (
                  <div key={sIdx} className="space-y-3">
                    <p className="font-black text-gray-900 uppercase text-xs tracking-tight">
                      {section.name || `Section ${sIdx + 1}`}
                    </p>

                    {section._structure_warnings?.length > 0 && (
                      <div className="bg-amber-50/70 border border-amber-200 rounded-2xl p-4 flex items-start gap-3">
                        <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
                        <ul className="space-y-1">
                          {section._structure_warnings.map((w, wi) => (
                            <li key={wi} className="text-xs font-bold text-amber-800/80 leading-relaxed">{w}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="rounded-2xl overflow-hidden border border-gray-100 overflow-x-auto">
                      <table className="w-full text-xs min-w-[640px]">
                        <thead>
                          <tr className="bg-gray-50 border-b border-gray-100">
                            <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px] w-12">Q#</th>
                            <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Type</th>
                            <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Topic</th>
                            <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Format</th>
                            <th className="text-center px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px] w-20">Marks</th>
                            <th className="text-left px-3 py-2 font-black text-gray-400 uppercase tracking-wider text-[9px]">Choice</th>
                          </tr>
                        </thead>
                        <tbody>
                          {section.question_slots.map((slot, slotIdx) => (
                            <tr key={slotIdx} className="border-t border-gray-50 bg-white">
                              <td className="px-3 py-2 font-mono text-[10px] font-bold text-gray-700">Q{slot.qnum}</td>
                              <td className="px-3 py-2">
                                <select
                                  value={slot.type || ''}
                                  onChange={(e) => updateSlot(sIdx, slotIdx, 'type', e.target.value)}
                                  className="w-full bg-gray-50/50 border border-gray-100 rounded-lg px-2 py-1.5 font-bold text-gray-900 outline-none focus:border-[#1e293b]"
                                >
                                  {Object.entries(SLOT_TYPE_LABELS).map(([val, label]) => (
                                    <option key={val} value={val}>{label}</option>
                                  ))}
                                </select>
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  value={slot.topic || ''} placeholder="—"
                                  onChange={(e) => updateSlot(sIdx, slotIdx, 'topic', e.target.value)}
                                  className="w-full bg-gray-50/50 border border-gray-100 rounded-lg px-2 py-1.5 font-bold text-gray-900 outline-none focus:border-[#1e293b]"
                                />
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  value={slot.format || ''} placeholder="—"
                                  onChange={(e) => updateSlot(sIdx, slotIdx, 'format', e.target.value)}
                                  className="w-full bg-gray-50/50 border border-gray-100 rounded-lg px-2 py-1.5 font-bold text-gray-900 outline-none focus:border-[#1e293b]"
                                />
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  type="number" min="0.5" step="0.5" value={slot.marks ?? ''}
                                  onChange={(e) => updateSlot(sIdx, slotIdx, 'marks', e.target.value === '' ? '' : Number(e.target.value))}
                                  className="w-full bg-gray-50/50 border border-gray-100 rounded-lg px-2 py-1.5 font-black text-blue-700 text-center outline-none focus:border-[#1e293b]"
                                />
                              </td>
                              <td className="px-3 py-2">
                                <div className="flex items-center gap-2">
                                  <select
                                    value={slot.choice || 'none'}
                                    onChange={(e) => updateSlot(sIdx, slotIdx, 'choice', e.target.value === 'none' ? '' : e.target.value)}
                                    disabled={slot.parts?.length > 0}
                                    className="bg-gray-50/50 border border-gray-100 rounded-lg px-2 py-1.5 font-bold text-gray-900 outline-none focus:border-[#1e293b] disabled:opacity-60"
                                  >
                                    <option value="none">None</option>
                                    <option value="internal">Internal (OR)</option>
                                    {slot.parts?.length > 0 && <option value="open">Open (any N)</option>}
                                  </select>
                                  {slot.parts?.length > 0 && (
                                    <span className="px-1.5 py-0.5 bg-indigo-50 text-indigo-700 text-[9px] font-black uppercase rounded border border-indigo-100 whitespace-nowrap">
                                      {slot.choice === 'open' && slot.attempt
                                        ? `Any ${slot.attempt} of ${slot.parts.length}`
                                        : `${slot.parts.length} Parts`}
                                    </span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )
              ))}
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                Question numbers and sub-parts are fixed at pattern creation — regenerate from the prompt to restructure.
              </p>
            </div>
          </section>
        )}

        {/* Statistics Grid */}
        <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="bg-white p-8 rounded-[40px] border border-gray-100 shadow-sm flex flex-col items-center justify-center text-center">
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">Total Marks</p>
            <div className="flex items-baseline gap-1">
              <p className="text-4xl font-black text-gray-900">{pattern.total_marks}</p>
              <span className="text-[10px] font-black text-gray-400">PTS</span>
            </div>
          </div>
          <div className="bg-white p-8 rounded-[40px] border border-gray-100 shadow-sm flex flex-col items-center justify-center text-center">
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">Total Questions</p>
            <div className="flex items-baseline gap-1">
              <p className="text-4xl font-black text-gray-900">{pattern.total_questions}</p>
              <span className="text-[10px] font-black text-gray-400">QTY</span>
            </div>
          </div>
          <div className="bg-white p-8 rounded-[40px] border border-gray-100 shadow-sm flex flex-col items-center justify-center text-center">
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">Sections</p>
            <div className="flex items-baseline gap-1">
              <p className="text-4xl font-black text-gray-900">{pattern.sections?.length || 0}</p>
              <span className="text-[10px] font-black text-gray-400">QTY</span>
            </div>
          </div>
          <div className="bg-white p-8 rounded-[40px] border border-gray-100 shadow-sm flex flex-col items-center justify-center text-center">
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">Pattern Source</p>
            <span className={`px-4 py-2 ${pattern.pattern_source === 'ai_generated' ? 'bg-blue-50 text-blue-600 border-blue-100' : 'bg-gray-50 text-gray-600 border-gray-100'} text-[10px] font-black uppercase rounded-2xl border`}>
                {pattern.pattern_source === 'ai_generated' ? 'AI Generated' : 'Manual'}
            </span>
          </div>
        </section>

        {/* AI Prompt / Teacher Input (only for AI generated) */}
        {pattern.pattern_source === 'ai_generated' && (
           <section className="bg-white rounded-[40px] shadow-sm border-2 border-blue-100 overflow-hidden relative">
              <div className="absolute top-0 right-0 w-48 h-48 bg-blue-50/50 rounded-full translate-x-24 -translate-y-24"></div>
              
              <div className="p-8 border-b border-blue-50 bg-blue-50/20">
                <div className="flex items-center gap-3 text-blue-600">
                  <h2 className="text-xs font-black uppercase tracking-widest">Teacher Input (Editable)</h2>
                </div>
              </div>

              <div className="p-8">
                 <textarea 
                    name="ai_prompt" value={formData.ai_prompt} onChange={handleChange}
                    className="w-full px-8 py-6 bg-gray-50 border border-gray-100 rounded-[30px] font-bold text-gray-900 focus:bg-white focus:border-[#1e293b] focus:ring-4 focus:ring-[#1e293b]/5 transition-all outline-none min-h-[150px] resize-none shadow-inner"
                    placeholder="Describe your pattern here..."
                 />
                 
                 <div className="mt-8 p-6 bg-blue-50/50 border border-blue-100 rounded-3xl flex flex-col md:flex-row items-center justify-between gap-6">
                    <div className="flex items-center gap-3">
                       <div className="w-10 h-10 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center shrink-0 animate-pulse">
                          <Info size={18} />
                       </div>
                       <p className="text-[10px] font-black text-blue-800 uppercase tracking-widest leading-relaxed">
                         Tip: Edit the prompt above and click "Regenerate Pattern" to update the structure with new sections, instructions, and constraints.
                       </p>
                    </div>
                    <button 
                      type="button" onClick={handleRegenerate} disabled={regenerating}
                      className="w-full md:w-auto px-8 py-4 bg-blue-600 text-white rounded-2xl font-black text-xs uppercase tracking-widest hover:bg-blue-700 transition-all active:scale-95 flex items-center justify-center gap-2 shadow-xl shadow-blue-200"
                    >
                      {regenerating ? <RefreshCw className="animate-spin" size={16} /> : <RefreshCw size={16} />}
                      Regenerate Pattern from Edited Prompt
                    </button>
                 </div>
              </div>
           </section>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-6 pt-10">
           <button 
              type="button" onClick={() => router.push('/patterns')}
              className="px-10 py-5 text-xs font-black text-gray-400 uppercase tracking-[0.2em] hover:text-gray-900 transition-colors"
           >
              Cancel
           </button>
           <button 
              type="submit" disabled={saving}
              className="px-12 py-5 bg-[#1e293b] text-white rounded-3xl font-black text-xs uppercase tracking-[0.2em] hover:bg-blue-600 transition-all flex items-center gap-3 shadow-2xl shadow-gray-200 hover:shadow-blue-200 hover:-translate-y-1 active:translate-y-0 disabled:opacity-50"
           >
              {saving ? <RefreshCw className="animate-spin" size={18} /> : <Save size={18} />}
              Save Changes
           </button>
        </div>
      </form>
    </div>
  );
}
