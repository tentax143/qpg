'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { 
  Plus, Trash2, ArrowLeft, Save, 
  BookOpen, GraduationCap, Layers,
  CheckCircle, Settings, HelpCircle, Layout, RefreshCw, Info
} from 'lucide-react';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

const QUESTION_TYPES = [
  { id: 'MCQ', label: 'Multiple Choice (MCQ)' },
  { id: 'VSA', label: 'Very Short Answer (VSA)' },
  { id: 'SA1', label: 'Short Answer I (SA1)' },
  { id: 'SA2', label: 'Short Answer II (SA2)' },
  { id: 'LA', label: 'Long Answer (LA)' },
  { id: 'CASE', label: 'Case Based' },
  { id: 'UNSEEN PASSAGE', label: 'Unseen Passage' },
  { id: 'GRAMMAR', label: 'Grammar' },
  { id: 'WRITING', label: 'Writing' }
];

export default function EditBlueprintTemplatePage() {
  const router = useRouter();
  const { id } = useParams();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  const [formData, setFormData] = useState({
    name: '',
    class_name: '',
    subject: '',
    description: '',
    is_default: false,
    sections: []
  });

  useEffect(() => {
    if (id) {
      fetchTemplate();
    }
  }, [id]);

  const fetchTemplate = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/templates/${id}/`);
      const data = res.data;
      
      let sections = [];
      if (data.blueprint && Array.isArray(data.blueprint.sections)) {
        sections = data.blueprint.sections.map(s => ({
          ...s,
          subsections: s.subsections || []
        }));
      }

      setFormData({
        name: data.name || '',
        class_name: data.class_name || '',
        subject: data.subject || '',
        description: data.description || '',
        is_default: data.is_default || false,
        sections: sections
      });
    } catch (err) {
      setError('Failed to load template data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({ 
      ...prev, 
      [name]: type === 'checkbox' ? checked : value 
    }));
  };

  const addSection = () => {
    const letter = String.fromCharCode(65 + formData.sections.length);
    setFormData(prev => ({
      ...prev,
      sections: [
        ...prev.sections,
        {
          name: letter,
          title: '',
          marks: 0,
          subsections: []
        }
      ]
    }));
  };

  const removeSection = (sIdx) => {
    setFormData(prev => {
      const newSections = prev.sections.filter((_, i) => i !== sIdx)
        .map((s, i) => ({ ...s, name: String.fromCharCode(65 + i) }));
      return { ...prev, sections: newSections };
    });
  };

  const handleSectionChange = (sIdx, field, value) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx] = { 
        ...newSections[sIdx], 
        [field]: field === 'marks' ? parseInt(value) || 0 : value 
      };
      return { ...prev, sections: newSections };
    });
  };

  const addSubsection = (sIdx) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections = [
        ...(newSections[sIdx].subsections || []),
        { name: '', marks: 0, question_types: [] }
      ];
      return { ...prev, sections: newSections };
    });
  };

  const removeSubsection = (sIdx, subIdx) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections = newSections[sIdx].subsections.filter((_, i) => i !== subIdx);
      return { ...prev, sections: newSections };
    });
  };

  const handleSubsectionChange = (sIdx, subIdx, field, value) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections[subIdx] = {
        ...newSections[sIdx].subsections[subIdx],
        [field]: field === 'marks' ? parseInt(value) || 0 : value
      };
      return { ...prev, sections: newSections };
    });
  };

  const addQuestionTypeRow = (sIdx, subIdx) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections[subIdx].question_types = [
        ...(newSections[sIdx].subsections[subIdx].question_types || []),
        ''
      ];
      return { ...prev, sections: newSections };
    });
  };

  const removeQuestionTypeRow = (sIdx, subIdx, qIdx) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections[subIdx].question_types = newSections[sIdx].subsections[subIdx].question_types.filter((_, i) => i !== qIdx);
      return { ...prev, sections: newSections };
    });
  };

  const handleQuestionTypeChange = (sIdx, subIdx, qIdx, value) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[sIdx].subsections[subIdx].question_types[qIdx] = value;
      return { ...prev, sections: newSections };
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const payload = {
        name: formData.name,
        class_name: formData.class_name,
        subject: formData.subject,
        description: formData.description,
        is_default: formData.is_default,
        blueprint: {
          sections: formData.sections
        }
      };

      await apiClient.put(`/templates/${id}/`, payload);
      setSuccess('Template updated successfully!');
      setTimeout(() => router.push('/blueprints'), 1500);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to update template');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2 mb-20 px-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-[#1e293b] shadow-xl rounded-2xl flex items-center justify-center">
            <Layout className="text-white" size={24} />
          </div>
          <div>
            <h1 className="text-2xl font-black text-gray-900 tracking-tight uppercase">Blueptint Template Editor</h1>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Structural Design & Distribution</p>
          </div>
        </div>
        <Link href="/blueprints" className="text-xs font-black text-gray-400 hover:text-blue-600 transition-all flex items-center gap-2 uppercase tracking-widest group">
          <ArrowLeft size={14} className="group-hover:-translate-x-1 transition-transform" />
          Back to List
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Basic Info */}
        <div className="glass-card p-8">
           <h2 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-6 flex items-center gap-2">
            <Info size={14} className="text-blue-500" />
            Template Metadata
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Name</label>
              <input 
                type="text" name="name" value={formData.name} onChange={handleInputChange}
                className="w-full px-5 py-3.5 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-600 transition-all outline-none"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Class</label>
              <input 
                type="text" name="class_name" value={formData.class_name} onChange={handleInputChange}
                className="w-full px-5 py-3.5 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-600 transition-all outline-none"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Subject</label>
              <input 
                type="text" name="subject" value={formData.subject} onChange={handleInputChange}
                className="w-full px-5 py-3.5 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-600 transition-all outline-none"
                required
              />
            </div>
          </div>
        </div>

        {/* Blueprint Structure Builder */}
        <div className="space-y-6">
           <div className="flex items-center justify-between px-2">
            <h2 className="text-[#1e293b] font-black uppercase tracking-widest text-sm flex items-center gap-2">
              <Layers size={18} className="text-blue-600" />
              Blueprint Structure
            </h2>
          </div>

          <div className="bg-indigo-50/50 border border-indigo-100 p-4 rounded-2xl flex items-start gap-4 mb-6">
            <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0">
              <Info size={16} className="text-indigo-600" />
            </div>
            <p className="text-[11px] font-bold text-indigo-700 leading-normal tracking-tight uppercase py-1">
              <span className="font-black">Dynamic Blueprint Builder:</span> Add sections, then subsections, then question types. This will create a structured blueprint automatically.
            </p>
          </div>

          <button 
             type="button" onClick={addSection}
             className="bg-white border-2 border-slate-200 text-slate-800 px-6 py-2.5 rounded-xl font-black text-[10px] uppercase tracking-widest flex items-center gap-2 hover:bg-slate-50 transition-all shadow-sm active:scale-95 mb-6"
           >
             <Plus size={16} />
             Add Section
           </button>

           <div className="space-y-8">
            {formData.sections.map((section, sIdx) => (
              <div key={sIdx} className="bg-white border-2 border-blue-600/20 rounded-[32px] overflow-hidden shadow-xl shadow-blue-900/5 relative group">
                {/* Section Header */}
                <div className="bg-white px-8 py-6 border-b border-gray-50 flex flex-col gap-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 bg-blue-600 text-white rounded-full flex items-center justify-center font-black text-sm shadow-lg shadow-blue-200">
                        {section.name}
                      </div>
                      <h3 className="text-xs font-black text-blue-600 uppercase tracking-widest">Section {section.name}</h3>
                    </div>
                    <button 
                      type="button" onClick={() => removeSection(sIdx)}
                      className="w-8 h-8 bg-red-50 text-red-500 rounded-full flex items-center justify-center hover:bg-red-500 hover:text-white transition-all shadow-sm"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
                    <div className="lg:col-span-3 space-y-2">
                       <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Section Title</label>
                       <input 
                        value={section.title} onChange={(e) => handleSectionChange(sIdx, 'title', e.target.value)}
                        className="w-full px-5 py-3 bg-gray-50 border border-gray-100 rounded-xl font-bold text-gray-900 outline-none focus:bg-white focus:border-blue-600 transition-all"
                        placeholder="READING SKILL"
                       />
                    </div>
                    <div className="space-y-2">
                       <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Total Marks</label>
                       <input 
                        type="number" value={section.marks} onChange={(e) => handleSectionChange(sIdx, 'marks', e.target.value)}
                        className="w-full px-5 py-3 bg-gray-50 border border-gray-100 rounded-xl font-bold text-gray-900 outline-none focus:bg-white focus:border-blue-600 transition-all"
                       />
                    </div>
                  </div>

                  <button 
                    type="button" onClick={() => addSubsection(sIdx)}
                    className="flex items-center gap-2 text-[10px] font-black text-blue-600 uppercase tracking-widest hover:bg-blue-50 px-4 py-2 rounded-xl transition-all self-start"
                  >
                    <Plus size={14} />
                    Add Subsection
                  </button>
                </div>

                {/* Subsections */}
                <div className="p-8 space-y-8 bg-gray-50/30">
                  {section.subsections?.map((sub, subIdx) => (
                    <div key={subIdx} className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm relative">
                       <button 
                        type="button" onClick={() => removeSubsection(sIdx, subIdx)}
                        className="absolute top-4 right-4 text-gray-300 hover:text-red-500 hover:bg-red-50 p-1 rounded-lg transition-all"
                       >
                         <Trash2 size={16} />
                       </button>

                       <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
                          <div className="md:col-span-3 space-y-2">
                            <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest">Subsection Name</label>
                            <input 
                              value={sub.name} onChange={(e) => handleSubsectionChange(sIdx, subIdx, 'name', e.target.value)}
                              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-100 rounded-xl font-bold text-xs"
                              placeholder="READING"
                            />
                          </div>
                          <div className="space-y-2">
                            <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest">Subsection Marks</label>
                            <input 
                              type="number" value={sub.marks} onChange={(e) => handleSubsectionChange(sIdx, subIdx, 'marks', e.target.value)}
                              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-100 rounded-xl font-bold text-xs"
                            />
                          </div>
                       </div>

                       <div className="space-y-3 pl-4 border-l-2 border-blue-50">
                          {sub.question_types?.map((qRow, qIdx) => (
                            <div key={qIdx} className="flex items-center gap-3">
                              <div className="flex-1">
                                <input 
                                  value={qRow} onChange={(e) => handleQuestionTypeChange(sIdx, subIdx, qIdx, e.target.value)}
                                  placeholder="Question Type (e.g. MCQ, Short Answer, etc.)"
                                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-100 rounded-xl font-bold text-xs focus:bg-white focus:border-blue-600 transition-all outline-none"
                                />
                              </div>
                              <button 
                                type="button" onClick={() => removeQuestionTypeRow(sIdx, subIdx, qIdx)}
                                className="w-10 h-10 bg-red-50 text-red-500 rounded-xl flex items-center justify-center hover:bg-red-500 hover:text-white transition-all shadow-sm"
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          ))}
                          <button 
                            type="button" onClick={() => addQuestionTypeRow(sIdx, subIdx)}
                            className="flex items-center gap-2 text-[10px] font-black text-blue-500 uppercase tracking-widest hover:text-blue-700 transition-all pt-2"
                          >
                            <Plus size={14} />
                            Add Question Type
                          </button>
                       </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
           </div>
        </div>

        {/* Submit Actions */}
        <div className="flex justify-end gap-6 pt-10 sticky bottom-4 z-20">
          <button 
            type="button" onClick={() => router.push('/blueprints')}
            className="px-10 py-4 bg-white border border-gray-200 text-xs font-black text-gray-400 uppercase tracking-widest rounded-2xl hover:bg-gray-50 hover:text-gray-900 transition-all shadow-xl"
          >
            Discard Changes
          </button>
          <button 
            type="submit" disabled={saving}
            className="bg-blue-600 text-white px-12 py-4 rounded-2xl font-black text-xs uppercase tracking-widest shadow-2xl shadow-blue-200 hover:bg-blue-700 transition-all flex items-center gap-3 active:scale-95"
          >
            {saving ? <RefreshCw className="animate-spin" /> : <Save size={20} />}
            Update Template
          </button>
        </div>
      </form>
    </div>
  );
}

