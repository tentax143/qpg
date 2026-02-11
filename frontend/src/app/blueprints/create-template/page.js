'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { 
  Plus, Trash2, ArrowLeft, Save, 
  BookOpen, GraduationCap, Layers,
  CheckCircle, Settings, HelpCircle, Layout,
  Info, Lightbulb, Beaker, Calculator, FileText, RefreshCw,
  ChevronRight, AlignLeft, Type, Hash, ListChecks, FileInput
} from 'lucide-react';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

const QUESTION_TYPES = [
  { value: 'MCQ', label: 'Multiple Choice (MCQ)' },
  { value: 'VSA', label: 'Very Short Answer (VSA)' },
  { value: 'SA1', label: 'Short Answer I (SA1)' },
  { value: 'SA2', label: 'Short Answer II (SA2)' },
  { value: 'LA', label: 'Long Answer (LA)' },
  { value: 'CASE', label: 'Case Based' },
  { value: 'UNSEEN PASSAGE', label: 'Unseen Passage' },
  { value: 'GRAMMAR', label: 'Grammar' },
  { value: 'WRITING', label: 'Writing' }
];

export default function CreateBlueprintTemplatePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
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
        .map((s, i) => ({ ...s, name: String.fromCharCode(65 + i) })); // Re-sequence A, B, C
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
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        return {
          ...section,
          subsections: [
            ...(section.subsections || []),
            { name: '', marks: 0, question_types: [] }
          ]
        };
      });
      return { ...prev, sections: newSections };
    });
  };

  const removeSubsection = (sIdx, subIdx) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        return {
          ...section,
          subsections: section.subsections.filter((_, i) => i !== subIdx)
        };
      });
      return { ...prev, sections: newSections };
    });
  };

  const handleSubsectionChange = (sIdx, subIdx, field, value) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        const newSubsections = section.subsections.map((sub, sIdx) => {
          if (sIdx !== subIdx) return sub;
          return {
            ...sub,
            [field]: field === 'marks' ? parseInt(value) || 0 : value
          };
        });
        return { ...section, subsections: newSubsections };
      });
      return { ...prev, sections: newSections };
    });
  };

  const addQuestionTypeRow = (sIdx, subIdx) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        const newSubsections = section.subsections.map((sub, sIdx2) => {
          if (sIdx2 !== subIdx) return sub;
          return {
            ...sub,
            question_types: [...(sub.question_types || []), '']
          };
        });
        return { ...section, subsections: newSubsections };
      });
      return { ...prev, sections: newSections };
    });
  };

  const removeQuestionTypeRow = (sIdx, subIdx, qIdx) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        const newSubsections = section.subsections.map((sub, sIdx2) => {
          if (sIdx2 !== subIdx) return sub;
          return {
            ...sub,
            question_types: sub.question_types.filter((_, i) => i !== qIdx)
          };
        });
        return { ...section, subsections: newSubsections };
      });
      return { ...prev, sections: newSections };
    });
  };

  const handleQuestionTypeChange = (sIdx, subIdx, qIdx, value) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, idx) => {
        if (idx !== sIdx) return section;
        const newSubsections = section.subsections.map((sub, sIdx2) => {
          if (sIdx2 !== subIdx) return sub;
          const newQuestionTypes = [...sub.question_types];
          newQuestionTypes[qIdx] = value;
          return { ...sub, question_types: newQuestionTypes };
        });
        return { ...section, subsections: newSubsections };
      });
      return { ...prev, sections: newSections };
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (formData.sections.length === 0) {
        throw new Error('Please add at least one section to the blueprint.');
      }

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

      await apiClient.post('/templates/', payload);
      setSuccess('Blueprint template created successfully!');
      setTimeout(() => router.push('/blueprints'), 1500);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to create template');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full relative py-2 mb-20 px-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
        <div className="flex items-center gap-5">
          <div className="w-16 h-16 bg-white/80 backdrop-blur-md shadow-2xl shadow-blue-500/10 border border-white/50 rounded-[28px] flex items-center justify-center group transform hover:rotate-6 transition-all duration-500">
            <Layout size={32} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight">Paper Architecture</h1>
            <p className="text-gray-500 font-bold flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
              Create dynamic blueprint templates
            </p>
          </div>
        </div>
        <Link href="/blueprints" className="bg-white/80 backdrop-blur-sm text-gray-400 hover:text-blue-600 px-6 py-3 rounded-2xl font-black text-[10px] uppercase tracking-widest transition-all border border-gray-100 flex items-center gap-2 hover:shadow-lg hover:-translate-y-0.5 active:scale-95 group">
          <ArrowLeft size={14} className="group-hover:-translate-x-1 transition-transform" />
          Back to List
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="space-y-12">
        {/* Basic Info */}
        <div className="relative z-30 bg-white/80 backdrop-blur-xl rounded-[40px] shadow-2xl shadow-blue-500/5 border border-white/20 p-10 group transition-all duration-500 hover:shadow-blue-500/10">
           <h2 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-10 flex items-center gap-2">
            <Info size={14} className="text-blue-500" />
            Template Metadata
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Template Name</label>
              <div className="relative group/input">
                <div className="absolute left-5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within/input:text-blue-500 transition-colors">
                  <FileText size={18} />
                </div>
                <input 
                  type="text" name="name" value={formData.name} onChange={handleInputChange}
                  className="w-full pl-14 pr-6 py-4.5 bg-gray-50/50 border border-gray-100 rounded-[22px] font-bold text-gray-900 focus:bg-white focus:border-blue-600 transition-all outline-none shadow-sm group-hover/input:shadow-md"
                  placeholder="Annual Exam 2024"
                  required
                />
              </div>
            </div>
            
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Grade / Class</label>
              <CustomSelect
                icon={GraduationCap}
                value={formData.class_name}
                onChange={(val) => setFormData(prev => ({ ...prev, class_name: val }))}
                options={['6', '7', '8', '9', '10', '11', '12'].map(c => ({ label: `Class ${c}`, value: c }))}
                placeholder="Select Class"
              />
            </div>

            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Subject</label>
              <CustomSelect
                icon={BookOpen}
                value={formData.subject}
                onChange={(val) => setFormData(prev => ({ ...prev, subject: val }))}
                options={['English', 'Mathematics', 'Science', 'Social Science', 'Physics', 'Chemistry', 'Biology'].map(s => ({ label: s, value: s }))}
                placeholder="Select Subject"
              />
            </div>
          </div>
        </div>

        {/* Blueprint Structure Builder */}
        <div className="space-y-8">
           <div className="flex items-center justify-between px-4">
            <h2 className="text-[#1e293b] font-black uppercase tracking-widest text-sm flex items-center gap-3">
              <Layers size={20} className="text-blue-600 animate-pulse" />
              Blueprint Structure
            </h2>
            <button 
               type="button" onClick={addSection}
               className="bg-gray-900 text-white px-8 py-3.5 rounded-2xl font-black text-[10px] uppercase tracking-[0.1em] flex items-center gap-2 hover:bg-black transition-all shadow-xl shadow-gray-200 hover:-translate-y-1 active:scale-95"
             >
               <Plus size={16} />
               Add New Section
             </button>
          </div>

           {formData.sections.length === 0 && (
             <div className="bg-white/80 backdrop-blur-md rounded-[32px] border-2 border-dashed border-gray-100 p-20 text-center group cursor-pointer hover:border-blue-200 transition-all" onClick={addSection}>
                <div className="w-16 h-16 bg-gray-50 rounded-2xl flex items-center justify-center mx-auto mb-4 group-hover:scale-110 transition-transform">
                  <AlignLeft size={32} className="text-gray-300" />
                </div>
                <p className="text-gray-400 font-bold uppercase tracking-widest text-xs">No sections added yet.<br/><span className="text-blue-500">Click to add your first section</span></p>
             </div>
           )}

           <div className="space-y-10">
            {formData.sections.map((section, sIdx) => (
              <div key={sIdx} className="bg-white/80 backdrop-blur-xl border border-white/20 rounded-[48px] shadow-2xl shadow-blue-900/5 relative group transition-all duration-500 hover:shadow-blue-500/10" style={{ zIndex: formData.sections.length - sIdx }}>
                {/* Section Header */}
                <div className="bg-gradient-to-r from-gray-50/50 to-white/50 px-10 py-10 border-b border-gray-50/50 flex flex-col gap-8 rounded-t-[48px]">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-6">
                      <div className="w-14 h-14 bg-blue-600 text-white rounded-[22px] flex items-center justify-center font-black text-xl shadow-xl shadow-blue-200 animate-in zoom-in-50 duration-500">
                        {section.name}
                      </div>
                      <div>
                        <h3 className="text-xs font-black text-blue-600 uppercase tracking-[0.2em] mb-1">Section {section.name}</h3>
                        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Main Categorization</p>
                      </div>
                    </div>
                    <button 
                      type="button" onClick={() => removeSection(sIdx)}
                      className="w-12 h-12 bg-red-50 text-red-400 rounded-2xl flex items-center justify-center hover:bg-red-500 hover:text-white transition-all shadow-sm group/del active:scale-95"
                      title="Remove Section"
                    >
                      <Trash2 size={20} className="group-hover:rotate-12 transition-transform" />
                    </button>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
                    <div className="lg:col-span-9 space-y-3">
                       <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Section Title</label>
                       <div className="relative group/input">
                         <div className="absolute left-5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within/input:text-blue-500 transition-colors">
                           <Type size={18} />
                         </div>
                         <input 
                          value={section.title} onChange={(e) => handleSectionChange(sIdx, 'title', e.target.value)}
                          className="w-full pl-14 pr-6 py-4 bg-white border border-gray-100 rounded-2xl font-bold text-gray-900 outline-none focus:border-blue-600 transition-all shadow-sm"
                          placeholder="READING SKILL"
                         />
                       </div>
                    </div>
                    <div className="lg:col-span-3 space-y-3">
                       <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Total Marks</label>
                       <div className="relative group/input">
                         <div className="absolute left-5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within/input:text-blue-500 transition-colors">
                           <Hash size={18} />
                         </div>
                         <input 
                          type="number" value={section.marks} onChange={(e) => handleSectionChange(sIdx, 'marks', e.target.value)}
                          className="w-full pl-14 pr-6 py-4 bg-white border border-gray-100 rounded-2xl font-bold text-gray-900 outline-none focus:border-blue-600 transition-all shadow-sm"
                         />
                       </div>
                    </div>
                  </div>

                  <button 
                    type="button" onClick={() => addSubsection(sIdx)}
                    className="flex items-center gap-2 text-[10px] font-black text-blue-600 uppercase tracking-widest hover:bg-white px-6 py-3 rounded-2xl transition-all self-start border border-dashed border-blue-200 hover:border-blue-600 hover:shadow-lg active:scale-95"
                  >
                    <Plus size={16} />
                    Define Subsection
                  </button>
                </div>

                {/* Subsections */}
                <div className="p-10 space-y-10 bg-gray-50/20 rounded-b-[48px]">
                  {section.subsections?.map((sub, subIdx) => (
                    <div key={subIdx} className="bg-white/60 backdrop-blur-md border border-white rounded-[32px] p-8 shadow-sm relative group/sub transition-all hover:bg-white hover:shadow-xl" style={{ zIndex: (section.subsections?.length || 0) - subIdx }}>
                       <button 
                        type="button" onClick={() => removeSubsection(sIdx, subIdx)}
                        className="absolute top-6 right-6 text-gray-300 hover:text-red-500 hover:bg-red-50 p-2 rounded-xl transition-all"
                       >
                         <Trash2 size={18} />
                       </button>

                       <div className="grid grid-cols-1 md:grid-cols-12 gap-8 mb-10">
                          <div className="md:col-span-9 space-y-3">
                            <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest ml-1">Subsection Heading</label>
                            <input 
                              value={sub.name} onChange={(e) => handleSubsectionChange(sIdx, subIdx, 'name', e.target.value)}
                              className="w-full px-6 py-3.5 bg-white/80 border border-gray-100 rounded-[20px] font-bold text-sm outline-none focus:border-blue-600 transition-all"
                              placeholder="Passage Interpretation"
                            />
                          </div>
                          <div className="md:col-span-3 space-y-3">
                            <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest ml-1">Sub-Marks</label>
                            <input 
                              type="number" value={sub.marks} onChange={(e) => handleSubsectionChange(sIdx, subIdx, 'marks', e.target.value)}
                              className="w-full px-6 py-3.5 bg-white/80 border border-gray-100 rounded-[20px] font-bold text-sm outline-none focus:border-blue-600 transition-all"
                            />
                          </div>
                       </div>

                       <div className="space-y-4 pl-6 border-l-2 border-blue-100/50">
                          <h4 className="text-[9px] font-black text-blue-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                            <ListChecks size={12} />
                            Included Question Types
                          </h4>
                          <div className="grid grid-cols-1 gap-4">
                            {sub.question_types?.map((qRow, qIdx) => (
                              <div key={qIdx} className="flex items-center gap-4 animate-in fade-in-0 slide-in-from-left-2 relative" style={{ zIndex: (sub.question_types?.length || 0) - qIdx }}>
                                <div className="flex-1">
                                  <CustomSelect
                                    value={qRow}
                                    onChange={(val) => handleQuestionTypeChange(sIdx, subIdx, qIdx, val)}
                                    options={QUESTION_TYPES}
                                    placeholder="Select Question Type"
                                    icon={Type}
                                  />
                                </div>
                                <button 
                                  type="button" onClick={() => removeQuestionTypeRow(sIdx, subIdx, qIdx)}
                                  className="w-12 h-12 bg-red-50/50 text-red-500 rounded-[18px] flex items-center justify-center hover:bg-red-500 hover:text-white transition-all shadow-sm active:scale-95"
                                >
                                  <Trash2 size={18} />
                                </button>
                              </div>
                            ))}
                          </div>
                          <button 
                            type="button" onClick={() => addQuestionTypeRow(sIdx, subIdx)}
                            className="flex items-center gap-2 text-[10px] font-black text-blue-600 uppercase tracking-[0.1em] hover:text-blue-800 transition-all pt-4 px-2 translate-y-2"
                          >
                            <Plus size={16} />
                            Add Type
                          </button>
                       </div>
                    </div>
                  ))}
                  
                  {(!section.subsections || section.subsections.length === 0) && (
                    <div className="py-10 text-center">
                      <p className="text-[10px] font-black text-gray-300 uppercase tracking-widest">No subsections defined for this section</p>
                    </div>
                  )}
                </div>
              </div>
            ))}
           </div>
        </div>

        {/* Submit Actions */}
        <div className="flex justify-end items-center gap-6 pt-16 sticky bottom-4 z-20">
          <button 
            type="button" onClick={() => router.push('/blueprints')}
            className="px-8 py-4 bg-white/80 backdrop-blur-md border border-gray-200 text-xs font-black text-gray-500 uppercase tracking-widest rounded-[22px] hover:bg-gray-50 hover:text-gray-900 transition-all shadow-xl hover:shadow-gray-200"
          >
            Discard Changes
          </button>
          <button 
            type="submit" disabled={loading}
            className="bg-blue-600 text-white px-12 py-4.5 rounded-[22px] font-black text-xs uppercase tracking-[0.2em] shadow-2xl shadow-blue-500/20 hover:bg-blue-700 transition-all flex items-center gap-3 hover:-translate-y-1 active:scale-95"
          >
            {loading ? <RefreshCw className="animate-spin" /> : <Save size={20} />}
            Finalize Template
          </button>
        </div>
      </form>
    </div>
  );
}

