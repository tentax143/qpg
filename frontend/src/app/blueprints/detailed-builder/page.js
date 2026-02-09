'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { 
  Plus, Trash2, Check, ArrowLeft, Save, 
  Info, FileText, Layers, MessageSquare, 
  ChevronDown, ChevronUp, Zap, Wand2,
  AlertCircle, FileInput, TextCursorInput, RefreshCw,
  BookOpen, GraduationCap, Target, Settings2, Sparkles
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

export default function DetailedBlueprintBuilder() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [validationResult, setValidationResult] = useState(null);
  const [showImportModal, setShowImportModal] = useState(false);
  const [importText, setImportText] = useState('');

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    class_name: '',
    subject: '',
    sections: []
  });

  // Options from API
  const [options, setOptions] = useState({
    classes: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'],
    subjects: ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology', 'History', 'Geography'],
    questionTypes: [
      { name: 'mcq', display_name: 'Multiple Choice Question' },
      { name: 'assertion_reason', display_name: 'Assertion-Reason' },
      { name: 'fill_blanks', display_name: 'Fill in the Blanks' },
      { name: 'true_false', display_name: 'True or False' },
      { name: 'very_short_answer', display_name: 'Very Short Answer' },
      { name: 'short_answer', display_name: 'Short Answer' },
      { name: 'long_answer', display_name: 'Long Answer' },
      { name: 'essay', display_name: 'Essay Type' },
      { name: 'comprehension', display_name: 'Comprehension Based' },
      { name: 'extract_based', display_name: 'Extract Based' },
      { name: 'diagram_based', display_name: 'Diagram Based' },
      { name: 'case_study', display_name: 'Case Study' }
    ],
    questionSources: [
      { name: 'general', display_name: 'General' },
      { name: 'ncert', display_name: 'NCERT Textbook' },
      { name: 'inside_text', display_name: 'Inside Text Questions' },
      { name: 'book_back', display_name: 'Book Back Exercises' },
      { name: 'previous_years', display_name: 'Previous Year Papers' },
      { name: 'application_based', display_name: 'Application Based' }
    ],
    passageTypes: ['narrative', 'descriptive', 'factual', 'discursive', 'persuasive'],
    difficultyLevels: ['easy', 'medium', 'hard']
  });

  const initialized = useRef(false);

  useEffect(() => {
    // Add first section by default only once
    if (!initialized.current && formData.sections.length === 0) {
      initialized.current = true;
      addSection();
    }
  }, []);

  const addSection = () => {
    setFormData(prev => {
      const newSection = {
        name: String.fromCharCode(65 + prev.sections.length),
        title: '',
        marks: 10,
        passage_config: {
          enabled: false,
          word_min: 300,
          word_max: 400,
          type: 'narrative',
          topics: ''
        },
        question_distribution: [],
        special_instructions: '',
        isExpanded: true
      };
      
      return {
        ...prev,
        sections: [...prev.sections, newSection]
      };
    });
  };

  const removeSection = (index) => {
    setFormData(prev => {
      const newSections = prev.sections.filter((_, i) => i !== index);
      // Re-label sections
      return {
        ...prev,
        sections: newSections.map((s, i) => ({
          ...s,
          name: String.fromCharCode(65 + i)
        }))
      };
    });
  };

  const updateSection = (index, field, value) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, i) => {
        if (i !== index) return section;
        return { ...section, [field]: value };
      });
      return { ...prev, sections: newSections };
    });
  };

  const updatePassageConfig = (index, field, value) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, i) => {
        if (i !== index) return section;
        return {
          ...section,
          passage_config: { ...section.passage_config, [field]: value }
        };
      });
      return { ...prev, sections: newSections };
    });
  };

  const addQuestionType = (sectionIndex) => {
    setFormData(prev => {
      const newQuestion = {
        type: '',
        count: 1,
        marks_each: 1,
        source: 'general',
        difficulty: 'medium',
        specific_chapters: ''
      };

      const newSections = prev.sections.map((section, i) => {
        if (i !== sectionIndex) return section;
        return {
          ...section,
          question_distribution: [...section.question_distribution, newQuestion]
        };
      });

      return { ...prev, sections: newSections };
    });
  };

  const updateQuestion = (sectionIndex, questionIndex, field, value) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, i) => {
        if (i !== sectionIndex) return section;
        
        const newDistribution = section.question_distribution.map((q, qIdx) => {
          if (qIdx !== questionIndex) return q;
          return { ...q, [field]: value };
        });

        return { ...section, question_distribution: newDistribution };
      });
      return { ...prev, sections: newSections };
    });
  };

  const removeQuestion = (sectionIndex, questionIndex) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, i) => {
        if (i !== sectionIndex) return section;
        return {
          ...section,
          question_distribution: section.question_distribution.filter((_, qIdx) => qIdx !== questionIndex)
        };
      });
      return { ...prev, sections: newSections };
    });
  };

  const toggleSection = (index) => {
    setFormData(prev => {
      const newSections = prev.sections.map((section, i) => {
        if (i !== index) return section;
        return { ...section, isExpanded: !section.isExpanded };
      });
      return { ...prev, sections: newSections };
    });
  };

  const calculateSummary = () => {
    let totalQuestions = 0;
    let totalMarks = 0;

    formData.sections.forEach(section => {
      totalMarks += parseInt(section.marks) || 0;
      section.question_distribution.forEach(q => {
        totalQuestions += (parseInt(q.count) || 0);
      });
    });

    return {
      totalSections: formData.sections.length,
      totalQuestions,
      totalMarks
    };
  };

  const summary = calculateSummary();

  const validateBlueprint = async () => {
    setValidating(true);
    setValidationResult(null);
    try {
      // Format data for validation
      const blueprint_structure = {
        version: "2.0",
        type: "detailed",
        sections: formData.sections.map(s => ({
          name: s.name,
          title: s.title || `Section ${s.name}`,
          marks: parseInt(s.marks),
          passage_config: s.passage_config.enabled ? {
            ...s.passage_config,
            topics: s.passage_config.topics.split(',').map(t => t.trim()).filter(t => t)
          } : { enabled: false },
          question_distribution: s.question_distribution.map(q => ({
            ...q,
            count: parseInt(q.count),
            marks_each: parseFloat(q.marks_each),
            total_marks: parseInt(q.count) * parseFloat(q.marks_each),
            specific_chapters: q.specific_chapters.split(',').map(c => c.trim()).filter(c => c)
          })),
          special_instructions: s.special_instructions
        }))
      };

      const response = await apiClient.post('/blueprint/validate/', {
        blueprint_structure
      });

      setValidationResult(response.data);
      if (response.data.valid) {
        setSuccess('Blueprint structure is valid!');
      } else {
        setError('Blueprint has validation errors. Please check the summary.');
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Validation failed');
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    if (!formData.name || !formData.class_name || !formData.subject) {
      setError('Please fill in Name, Class, and Subject');
      return;
    }

    setSaving(true);
    try {
      const blueprint_structure = {
        version: "2.0",
        type: "detailed",
        sections: formData.sections.map(s => ({
          name: s.name,
          title: s.title || `Section ${s.name}`,
          marks: parseInt(s.marks),
          passage_config: s.passage_config.enabled ? {
            ...s.passage_config,
            topics: s.passage_config.topics.split(',').map(t => t.trim()).filter(t => t)
          } : { enabled: false },
          question_distribution: s.question_distribution.map(q => ({
            ...q,
            count: parseInt(q.count),
            marks_each: parseFloat(q.marks_each),
            total_marks: parseInt(q.count) * parseFloat(q.marks_each),
            specific_chapters: q.specific_chapters.split(',').map(c => c.trim()).filter(c => c)
          })),
          special_instructions: s.special_instructions
        }))
      };

      const response = await apiClient.post('/blueprint/save-detailed/', {
        name: formData.name,
        class_name: formData.class_name,
        subject: formData.subject,
        blueprint_structure
      });

      setSuccess('Blueprint saved successfully!');
      setTimeout(() => router.push('/blueprints'), 2000);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to save blueprint');
    } finally {
      setSaving(false);
    }
  };

  const loadSample = () => {
    setFormData({
      name: 'Sample Class 6 English Blueprint',
      class_name: '6',
      subject: 'English',
      sections: [
        {
          name: 'A',
          title: 'Reading Comprehension',
          marks: 10,
          passage_config: {
            enabled: true,
            word_min: 300,
            word_max: 400,
            type: 'narrative',
            topics: 'environment, kindness'
          },
          question_distribution: [
            { type: 'mcq', count: 5, marks_each: 1, source: 'general', difficulty: 'medium', specific_chapters: '' },
            { type: 'short_answer', count: 2, marks_each: 2.5, source: 'general', difficulty: 'medium', specific_chapters: '' }
          ],
          special_instructions: 'Focus on vocabulary and inference questions',
          isExpanded: true
        },
        {
          name: 'B',
          title: 'Grammar',
          marks: 10,
          passage_config: { enabled: false, word_min: 300, word_max: 400, type: 'narrative', topics: '' },
          question_distribution: [
            { type: 'fill_blanks', count: 10, marks_each: 1, source: 'general', difficulty: 'easy', specific_chapters: '' }
          ],
          special_instructions: '',
          isExpanded: true
        }
      ]
    });
  };

  const handleImportText = async () => {
    if (!importText) return;
    setLoading(true);
    try {
      const response = await apiClient.post('/blueprint/parse-text/', {
        text: importText,
        class_name: formData.class_name,
        subject: formData.subject
      });

      if (response.data.success) {
        const structure = response.data.blueprint_structure;
        
        // Map the parsed structure to our form state strict matching the Django logic
        const newSections = structure.sections.map((s, i) => {
          // 1. Basic Section Data
          const sectionData = {
            name: String.fromCharCode(65 + i), // Ensure A, B, C... sequence
            title: s.title || '',
            marks: parseInt(s.marks) || 0,
            special_instructions: s.special_instructions || '',
            isExpanded: true,
            passage_config: {
              enabled: false,
              word_min: 300,
              word_max: 400,
              type: 'narrative',
              topics: '' 
            },
            question_distribution: []
          };

          // 2. Passage Configuration
          if (s.passage_config && s.passage_config.enabled) {
            sectionData.passage_config = {
              enabled: true,
              word_min: parseInt(s.passage_config.word_min) || 300,
              word_max: parseInt(s.passage_config.word_max) || 400,
              type: s.passage_config.type || 'narrative',
              topics: Array.isArray(s.passage_config.topics) 
                ? s.passage_config.topics.join(', ') 
                : (s.passage_config.topics || '')
            };
          }

          // 3. Question Distribution
          if (Array.isArray(s.question_distribution)) {
            sectionData.question_distribution = s.question_distribution.map(q => ({
              type: q.type || '',
              count: parseInt(q.count) || 0,
              marks_each: parseFloat(q.marks_each) || 1,
              source: q.source || 'general',
              difficulty: q.difficulty || 'medium',
              specific_chapters: Array.isArray(q.specific_chapters)
                ? q.specific_chapters.join(', ')
                : (q.specific_chapters || '')
            }));
          }

          return sectionData;
        });

        // Update State
        setFormData(prev => ({
          ...prev,
          sections: newSections
        }));
        
        setShowImportModal(false);
        setSuccess('Blueprint imported successfully!');
      }
    } catch (err) {
      setError('Failed to parse text: ' + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen pb-20 px-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-8 mb-12 relative z-[60]">
        <div className="flex items-center gap-5">
           <div className="w-16 h-16 bg-white/80 backdrop-blur-md shadow-2xl shadow-blue-500/10 border border-white/50 rounded-[20px] flex items-center justify-center group-hover:rotate-6 transition-transform duration-500">
             <Settings2 size={32} className="text-blue-600" />
           </div>
           <div>
             <h1 className="text-3xl font-black text-gray-900 tracking-tight">Detailed Builder</h1>
             <p className="text-gray-500 font-medium">Design precision blueprints with AI-ready configuration</p>
           </div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <button 
            onClick={loadSample}
            className="px-6 py-3.5 bg-white text-gray-700 rounded-2xl font-bold text-sm border border-gray-100 shadow-sm hover:shadow-md hover:bg-gray-50 transition-all flex items-center gap-2 active:scale-95"
          >
            <FileInput size={18} /> Load Sample
          </button>
          <button 
            onClick={() => setShowImportModal(true)}
            className="px-6 py-3.5 bg-blue-50 text-blue-700 rounded-2xl font-bold text-sm border border-blue-100 shadow-sm hover:shadow-md hover:bg-blue-100/50 transition-all flex items-center gap-2 active:scale-95"
          >
            <Sparkles size={18} /> Import from Text
          </button>
          <Link href="/blueprints" className="px-6 py-3.5 bg-gray-900 text-white rounded-2xl font-bold text-sm shadow-xl shadow-gray-200 hover:bg-black transition-all flex items-center gap-2 hover:-translate-y-1 active:scale-95">
            <ArrowLeft size={18} />
            Back to List
          </Link>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Basic Info Card */}
      <div className="bg-white/80 backdrop-blur-xl rounded-[40px] shadow-2xl shadow-blue-500/5 border border-white/20 p-10 mb-12 relative z-50 overflow-visible">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
          <div className="space-y-3">
            <label className="text-xs font-bold text-gray-400 uppercase tracking-widest ml-1">Blueprint Name</label>
            <div className="relative group">
              <div className="absolute left-5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-500 transition-colors">
                <FileText size={18} />
              </div>
              <input 
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                placeholder="e.g., Annual Exam 2024"
                className="w-full pl-12 pr-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/5 outline-none transition-all font-bold text-gray-900"
              />
            </div>
          </div>
          
          <CustomSelect
            label="Class"
            icon={GraduationCap}
            value={formData.class_name}
            onChange={(val) => setFormData({...formData, class_name: val})}
            options={options.classes.map(c => ({ label: `Class ${c}`, value: c }))}
            placeholder="Select Class"
          />

          <CustomSelect
            label="Subject"
            icon={BookOpen}
            value={formData.subject}
            onChange={(val) => setFormData({...formData, subject: val})}
            options={options.subjects.map(s => ({ label: s, value: s }))}
            placeholder="Select Subject"
          />
        </div>
      </div>

      <div className="mb-10 flex items-center justify-between px-2">
        <div className="flex items-center gap-3">
          <div className="w-2 h-8 bg-blue-600 rounded-full"></div>
          <h2 className="text-xl font-black text-gray-900 tracking-tight">Paper Sections</h2>
        </div>
        <button 
          onClick={addSection}
          className="bg-gray-900 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-widest flex items-center gap-2 hover:bg-black transition-all hover:-translate-y-1 active:scale-95 shadow-xl shadow-gray-200"
        >
          <Plus size={18} /> Add New Section
        </button>
      </div>

      {/* Sections List */}
      <div className="space-y-6 mb-12">
        {formData.sections.map((section, sIdx) => (
          <div key={sIdx} className={`bg-white rounded-[32px] border ${section.isExpanded ? 'border-gray-100 shadow-xl shadow-gray-200/50' : 'border-gray-100 shadow-sm'} transition-all duration-300 relative focus-within:z-40 overflow-visible`}>
            {/* Section Header */}
            <div className={`p-6 flex items-center justify-between gap-4 cursor-pointer hover:bg-gray-50/50 transition-colors rounded-t-[32px] ${section.isExpanded ? 'bg-gray-50/30 border-b border-gray-50' : ''}`}
                 onClick={() => toggleSection(sIdx)}>
              <div className="flex items-center gap-6">
                <div className="w-10 h-10 bg-[#1e293b] text-white rounded-xl flex items-center justify-center font-black italic shadow-lg shadow-slate-200">
                  {section.name}
                </div>
                <div className="flex flex-col md:flex-row md:items-center gap-3">
                  <input 
                    type="text"
                    value={section.title}
                    onChange={(e) => { e.stopPropagation(); updateSection(sIdx, 'title', e.target.value); }}
                    onClick={(e) => e.stopPropagation()}
                    placeholder="Section Title (e.g., Reading Comprehension)"
                    className="bg-transparent border-none outline-none font-black text-gray-900 uppercase tracking-tight placeholder-gray-300 min-w-[250px]"
                  />
                  <div className="flex items-center gap-2">
                    <span className="px-3 py-1 bg-slate-100 text-[#1e293b] text-[10px] font-black uppercase rounded-full border border-slate-200 flex items-center gap-1.5 focus-within:border-[#1e293b] transition-all">
                      <input 
                        type="number"
                        value={section.marks}
                        onChange={(e) => { e.stopPropagation(); updateSection(sIdx, 'marks', e.target.value); }}
                        onClick={(e) => e.stopPropagation()}
                        className="bg-transparent border-none outline-none w-8 text-center"
                      /> marks
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button 
                  onClick={(e) => { e.stopPropagation(); removeSection(sIdx); }}
                  className="p-2.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-xl transition-all"
                >
                  <Trash2 size={18} />
                </button>
                {section.isExpanded ? <ChevronUp className="text-gray-400" /> : <ChevronDown className="text-gray-400" />}
              </div>
            </div>

            {/* Section Content */}
            {section.isExpanded && (
              <div className="p-8 space-y-8 animate-in slide-in-from-top-2 duration-300">
                {/* Passage Config */}
                <div className="p-6 bg-slate-50/50 rounded-[28px] border border-slate-100">
                  <div className="flex items-center gap-3 mb-6">
                    <input 
                      type="checkbox"
                      id={`passage-${sIdx}`}
                      checked={section.passage_config.enabled}
                      onChange={(e) => updatePassageConfig(sIdx, 'enabled', e.target.checked)}
                      className="w-5 h-5 rounded border-gray-300 text-[#1e293b] focus:ring-[#1e293b]"
                    />
                    <label htmlFor={`passage-${sIdx}`} className="text-xs font-black text-gray-700 uppercase tracking-widest cursor-pointer">
                      Include Passage/Comprehension
                    </label>
                  </div>

                  {section.passage_config.enabled && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-in fade-in duration-300">
                      <div className="space-y-2">
                        <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Word Range</label>
                        <div className="flex items-center gap-2">
                          <input 
                            type="number" 
                            value={section.passage_config.word_min}
                            onChange={(e) => updatePassageConfig(sIdx, 'word_min', e.target.value)}
                            className="w-full px-4 py-2 bg-white border border-gray-100 rounded-xl font-bold text-sm focus:border-[#1e293b] outline-none transition-all"
                            placeholder="Min"
                          />
                          <span className="text-gray-400 font-bold">to</span>
                          <input 
                            type="number" 
                            value={section.passage_config.word_max}
                            onChange={(e) => updatePassageConfig(sIdx, 'word_max', e.target.value)}
                            className="w-full px-4 py-2 bg-white border border-gray-100 rounded-xl font-bold text-sm focus:border-[#1e293b] outline-none transition-all"
                            placeholder="Max"
                          />
                        </div>
                      </div>
                      <div className="space-y-2">
                        <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Type</label>
                        <CustomSelect
                          value={section.passage_config.type}
                          onChange={(val) => updatePassageConfig(sIdx, 'type', val)}
                          options={options.passageTypes.map(pt => ({ label: pt.charAt(0).toUpperCase() + pt.slice(1), value: pt }))}
                          placeholder="Passage Type"
                          noLabel
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest ml-1">Topics</label>
                        <div className="relative group">
                          <input 
                            type="text" 
                            value={section.passage_config.topics}
                            onChange={(e) => updatePassageConfig(sIdx, 'topics', e.target.value)}
                            className="w-full px-4 py-2 bg-white border border-gray-100 rounded-xl font-bold text-sm focus:border-blue-500 outline-none transition-all pl-10"
                            placeholder="e.g. environment, tech"
                          />
                          <Target size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-500 transition-colors" />
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Question Distribution */}
                <div className="space-y-6">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-black text-gray-900 uppercase tracking-widest flex items-center gap-2">
                      <Zap size={14} className="text-amber-500 fill-amber-500" />
                      Question Distribution
                    </h3>
                  </div>

                  <div className="space-y-3">
                    {section.question_distribution.map((q, qIdx) => (
                      <div key={qIdx} className="grid grid-cols-1 md:grid-cols-12 gap-3 p-4 bg-gray-50/50 rounded-2xl border border-gray-100 items-end animate-in zoom-in-95 duration-200">
                        <div className="md:col-span-2 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Type</label>
                          <CustomSelect
                            value={q.type}
                            onChange={(val) => updateQuestion(sIdx, qIdx, 'type', val)}
                            options={options.questionTypes.map(qt => ({ label: qt.display_name, value: qt.name }))}
                            placeholder="Select Type"
                            noLabel
                          />
                        </div>
                        <div className="md:col-span-1 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Count</label>
                          <input 
                            type="number" 
                            min="1"
                            value={q.count}
                            onChange={(e) => updateQuestion(sIdx, qIdx, 'count', e.target.value)}
                            className="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl font-bold text-xs text-center focus:border-[#1e293b] outline-none"
                          />
                        </div>
                        <div className="md:col-span-1 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Marks</label>
                          <input 
                            type="number" 
                            step="0.5"
                            value={q.marks_each}
                            onChange={(e) => updateQuestion(sIdx, qIdx, 'marks_each', e.target.value)}
                            className="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl font-bold text-xs text-center focus:border-[#1e293b] outline-none"
                          />
                        </div>
                        <div className="md:col-span-2 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Source</label>
                          <CustomSelect
                            value={q.source}
                            onChange={(val) => updateQuestion(sIdx, qIdx, 'source', val)}
                            options={options.questionSources.map(qs => ({ label: qs.display_name, value: qs.name }))}
                            placeholder="Select Source"
                            noLabel
                          />
                        </div>
                        <div className="md:col-span-2 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Difficulty</label>
                          <CustomSelect
                            value={q.difficulty}
                            onChange={(val) => updateQuestion(sIdx, qIdx, 'difficulty', val)}
                            options={options.difficultyLevels.map(d => ({ label: d.charAt(0).toUpperCase() + d.slice(1), value: d }))}
                            placeholder="Select Difficulty"
                            noLabel
                          />
                        </div>
                        <div className="md:col-span-3 space-y-1">
                          <label className="text-[8px] font-black text-gray-400 uppercase tracking-widest ml-1">Chapters (Optional)</label>
                          <input 
                            type="text" 
                            value={q.specific_chapters}
                            onChange={(e) => updateQuestion(sIdx, qIdx, 'specific_chapters', e.target.value)}
                            className="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl font-bold text-xs focus:border-[#1e293b] outline-none"
                            placeholder="Use comma for multiple"
                          />
                        </div>
                        <div className="md:col-span-1">
                          <button 
                            onClick={() => removeQuestion(sIdx, qIdx)}
                            className="w-full py-2 flex items-center justify-center text-red-400 hover:text-red-600 hover:bg-red-50 rounded-xl transition-all"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </div>
                    ))}
                    <button 
                      onClick={() => addQuestionType(sIdx)}
                      className="w-full py-3 border-2 border-dashed border-gray-100 rounded-2xl text-gray-400 hover:text-[#1e293b] hover:border-[#1e293b]/20 hover:bg-slate-50 transition-all font-black text-[10px] uppercase tracking-widest flex items-center justify-center gap-2"
                    >
                      <Plus size={14} /> Add Question Type
                    </button>
                  </div>
                </div>

                {/* Special Instructions */}
                <div className="space-y-3">
                  <label className="text-xs font-black text-gray-700 uppercase tracking-widest flex items-center gap-2 ml-1">
                    <MessageSquare size={14} className="text-slate-400" />
                    Special Instructions (Optional)
                  </label>
                  <textarea 
                    value={section.special_instructions}
                    onChange={(e) => updateSection(sIdx, 'special_instructions', e.target.value)}
                    rows={2}
                    placeholder="e.g., Focus on vocabulary and inference questions"
                    className="w-full px-5 py-4 bg-gray-50 border border-gray-100 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all font-bold text-sm text-gray-800 placeholder-gray-300"
                  />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Summary Tracker */}
      <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[calc(100%-3rem)] max-w-5xl z-40 animate-in slide-in-from-bottom-10 duration-500">
        <div className="bg-[#1e293b] text-white p-4 md:p-6 rounded-[32px] shadow-2xl flex flex-wrap items-center justify-between gap-6 border border-white/10 backdrop-blur-md">
          <div className="flex items-center gap-8 md:px-4">
            <div className="space-y-0.5">
              <p className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">Sections</p>
              <p className="text-lg font-black">{summary.totalSections}</p>
            </div>
            <div className="w-px h-8 bg-white/10 hidden md:block"></div>
            <div className="space-y-0.5">
              <p className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">Questions</p>
              <p className="text-lg font-black">{summary.totalQuestions}</p>
            </div>
            <div className="w-px h-8 bg-white/10 hidden md:block"></div>
            <div className="space-y-0.5">
              <p className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">Total Marks</p>
              <div className="flex items-baseline gap-1">
                <p className="text-lg font-black">{summary.totalMarks}</p>
              </div>
            </div>
            {validationResult && (
              <>
                <div className="w-px h-8 bg-white/10 hidden md:block"></div>
                <div className="space-y-0.5">
                  <p className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">Status</p>
                  <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest ${validationResult.valid ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                    {validationResult.valid ? <Check size={10} /> : <AlertCircle size={10} />}
                    {validationResult.valid ? 'Valid' : 'Invalid'}
                  </div>
                </div>
              </>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button 
              onClick={() => router.back()}
              className="px-6 py-3 bg-white/5 hover:bg-white/10 text-white rounded-2xl font-black text-[10px] uppercase tracking-widest transition-all"
            >
              Back
            </button>
            <button 
              onClick={validateBlueprint}
              disabled={validating}
              className="px-8 py-3 bg-white/10 hover:bg-white/20 text-white rounded-2xl font-black text-[10px] uppercase tracking-widest transition-all flex items-center gap-2 border border-white/10"
            >
              {validating ? <RefreshCw className="animate-spin" size={14} /> : <Check size={14} />}
              Validate
            </button>
            <button 
              onClick={handleSave}
              disabled={saving}
              className="px-10 py-3 bg-emerald-500 hover:bg-emerald-400 text-[#1e293b] rounded-2xl font-black text-[10px] uppercase tracking-widest transition-all flex items-center gap-2 shadow-lg shadow-emerald-500/20"
            >
              {saving ? <RefreshCw className="animate-spin" size={14} /> : <Save size={14} />}
              Save Blueprint
            </button>
          </div>
        </div>
      </div>

      {/* Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm" onClick={() => setShowImportModal(false)}></div>
          <div className="relative glass-card w-full max-w-2xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="p-8 border-b border-gray-100 flex items-center justify-between">
              <div>
                <h3 className="text-xl font-black text-gray-900 uppercase tracking-tight">Import from Text</h3>
                <p className="text-gray-400 text-xs font-bold uppercase tracking-widest">Paste your blueprint structure below</p>
              </div>
              <button onClick={() => setShowImportModal(false)} className="p-2 hover:bg-gray-100 rounded-xl transition-colors">
                <Plus className="rotate-45" size={24} />
              </button>
            </div>
            <div className="p-8 space-y-4">
              <textarea 
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                rows={10}
                placeholder="Example:
Section A - Reading Comprehension - 10 marks
- 5 MCQs of 1 mark each
- 2 Short Answer of 2.5 marks each

Section B - Grammar - 10 marks
- 10 Fill in the blanks"
                className="w-full px-6 py-6 bg-gray-50 border border-gray-100 rounded-[32px] focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all font-medium text-sm leading-relaxed"
              />
              <div className="p-4 bg-slate-50 rounded-2xl border border-slate-100 flex gap-3">
                <Info size={18} className="text-slate-400 shrink-0 mt-0.5" />
                <p className="text-[10px] text-slate-500 font-bold uppercase leading-relaxed tracking-wider">
                  The AI will analyze the text to extract sections, question types, counts, and marks. 
                  Make sure to specify marks and counts clearly.
                </p>
              </div>
            </div>
            <div className="p-8 bg-gray-50 flex items-center justify-end gap-3">
              <button 
                onClick={() => setShowImportModal(false)}
                className="px-6 py-3 text-xs font-black text-gray-400 uppercase tracking-widest hover:text-gray-600 transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={handleImportText}
                disabled={loading}
                className="px-10 py-3 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-slate-200 hover:shadow-slate-300 transition-all flex items-center gap-2"
              >
                {loading ? <RefreshCw className="animate-spin" size={16} /> : <Wand2 size={16} />}
                Import & Parse
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
