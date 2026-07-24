'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { 
  Plus, X, Upload, Eye, EyeOff, Zap,
  Settings, BookOpen, Layers, BarChart, FilePlus,
  ArrowRight, RefreshCcw, ChevronRight, Users, Clock, Star,
  CheckCircle, Info, Undo, AlertCircle, GraduationCap, Sparkles, FileText, Check, LayoutGrid
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import CustomSelect from '@/components/CustomSelect';

function GeneratorContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Form State
  const [formData, setFormData] = useState({
    class_name: '',
    subject: '',
    pattern: '',
    difficulty: 'Easy',
    blueprint: '',
    chapters: '',
    duration: '',
    total_marks: '',
  });

  const [numOneMarkQuestions, setNumOneMarkQuestions] = useState(20);
  const [additionalFiles, setAdditionalFiles] = useState([]);
  
  // Data State
  const [subjects, setSubjects] = useState([]);
  const [patterns, setPatterns] = useState([]);
  const [blueprints, setBlueprints] = useState([]);
  const [availableChapters, setAvailableChapters] = useState([]);
  const [selectedChapters, setSelectedChapters] = useState([]);
  
  // One Mark Test helper — derived from selected pattern
  const isOneMarkTest = patterns.find(p => String(p.id) === String(formData.pattern))?.pattern_source === 'one_mark_test';

  // UI State
  const [selectedPatternDetails, setSelectedPatternDetails] = useState(null);
  const [loadingSubjects, setLoadingSubjects] = useState(false);
  const [loadingChapters, setLoadingChapters] = useState(false);
  const [loadingBlueprints, setLoadingBlueprints] = useState(false);
  const [loadingPatternDetails, setLoadingPatternDetails] = useState(false);
  const [showBlueprintModal, setShowBlueprintModal] = useState(false);
  const [previewBlueprintData, setPreviewBlueprintData] = useState(null);
  const [expandedSections, setExpandedSections] = useState(new Set());

  const toggleSection = (idx) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx); else next.add(idx);
      return next;
    });
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  const fetchInitialData = async () => {
    try {
      const patternsRes = await apiClient.get('/patterns/?page_size=100');
      const allPatterns = patternsRes.data.results || [];
      setPatterns(allPatterns);
      
      // Check for pattern ID in URL
      const patternId = searchParams.get('pattern');
      if (patternId) {
        const foundPattern = allPatterns.find(p => String(p.id) === patternId);
        if (foundPattern) {
          setFormData(prev => ({ 
            ...prev, 
            pattern: patternId,
            class_name: foundPattern.class_name || prev.class_name,
            subject: foundPattern.subject || prev.subject
          }));
        }
      }
    } catch (err) {
      console.error("Failed to load patterns", err);
    } finally {
      setLoading(false);
    }
  };

  // Load subjects for class
  useEffect(() => {
    if (formData.class_name.trim()) {
      const timer = setTimeout(() => {
        loadSubjects();
      }, 500);
      return () => clearTimeout(timer);
    } else {
      setSubjects([]);
      setFormData(prev => ({ ...prev, subject: '', blueprint: '', chapters: '' }));
      setSelectedChapters([]);
      setAvailableChapters([]);
      setBlueprints([]);
    }
  }, [formData.class_name]);

  const loadSubjects = async () => {
    setLoadingSubjects(true);
    try {
      const res = await apiClient.get(`/get_subjects_for_class/?class_name=${encodeURIComponent(formData.class_name)}`);
      setSubjects(res.data.subjects || []);
    } catch (err) {
      console.error("Error loading subjects", err);
    } finally {
      setLoadingSubjects(false);
    }
  };

  // Load chapters and blueprints when subject changes
  useEffect(() => {
    if (formData.subject && formData.class_name) {
      loadChapters();
      loadBlueprints();
    } else {
      setAvailableChapters([]);
      setSelectedChapters([]);
      setBlueprints([]);
    }
  }, [formData.subject, formData.class_name]);

  const loadChapters = async () => {
    setLoadingChapters(true);
    try {
      const res = await apiClient.get(`/get_chapters/?class_name=${encodeURIComponent(formData.class_name)}&subject=${encodeURIComponent(formData.subject)}`);
      setAvailableChapters(res.data.chapters || []);
      setSelectedChapters([]); // Reset selection when subject changes
    } catch (err) {
      console.error("Error loading chapters", err);
    } finally {
      setLoadingChapters(false);
    }
  };

  const loadBlueprints = async () => {
    setLoadingBlueprints(true);
    try {
      const res = await apiClient.get(`/get_blueprints/?class_name=${encodeURIComponent(formData.class_name)}&subject=${encodeURIComponent(formData.subject)}`);
      setBlueprints(res.data.blueprints || []);
    } catch (err) {
      console.error("Error loading blueprints", err);
    } finally {
      setLoadingBlueprints(false);
    }
  };

  // Load pattern details when pattern changes
  useEffect(() => {
    setExpandedSections(new Set());
    if (formData.pattern) {
      loadPatternDetails();
    } else {
      setSelectedPatternDetails(null);
    }
  }, [formData.pattern]);

  const loadPatternDetails = async () => {
    setLoadingPatternDetails(true);
    try {
      const patternId = String(formData.pattern);
      let res;
      
      if (patternId.startsWith('exam_') || patternId.startsWith('template_')) {
        res = await apiClient.get(`/get_blueprint_details/${patternId}/`);
        
        if (res.data.success && res.data.blueprint) {
          const bp = res.data.blueprint;
          const sections = bp.blueprint?.sections || bp.sections || [];
          
          setSelectedPatternDetails({
            ...bp,
            sections: sections,
            total_marks: bp.total_marks || sections.reduce((acc, s) => acc + (s.marks || 0), 0),
            total_questions: bp.total_questions || sections.reduce((acc, s) => {
              const qCount = s.questions_count || s.question_distribution?.reduce((qAcc, q) => qAcc + (Number(q.count) || 0), 0);
              return acc + (Number(qCount) || 0);
            }, 0)
          });
        }
      } else {
        res = await apiClient.get(`/patterns/${patternId}/`);
        setSelectedPatternDetails(res.data);
      }
    } catch (err) {
      console.error("Error loading pattern details", err);
      try {
        const patternId = String(formData.pattern);
        const fallbackEndpoint = (patternId.startsWith('exam_') || patternId.startsWith('template_')) 
          ? `/patterns/${patternId}/` 
          : `/get_blueprint_details/${patternId}/`;
          
        const res = await apiClient.get(fallbackEndpoint);
        const data = res.data.blueprint || res.data;
        setSelectedPatternDetails(data);
      } catch (fallbackErr) {
        console.error("Fallback lookup also failed", fallbackErr);
        setSelectedPatternDetails(null);
      }
    } finally {
      setLoadingPatternDetails(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const toggleChapter = (chapter) => {
    setSelectedChapters(prev => 
      prev.includes(chapter) 
        ? prev.filter(c => c !== chapter)
        : [...prev, chapter]
    );
  };

  const handleFileChange = (e) => {
    const files = Array.from(e.target.files);
    setAdditionalFiles(prev => [...prev, ...files]);
  };

  const removeFile = (index) => {
    setAdditionalFiles(prev => prev.filter((_, i) => i !== index));
  };

  const resetForm = () => {
    setFormData({
      class_name: '',
      subject: '',
      pattern: '',
      difficulty: 'Easy',
      blueprint: '',
      chapters: '',
      duration: '',
      total_marks: '',
    });
    setAdditionalFiles([]);
    setSelectedChapters([]);
    setSelectedPatternDetails(null);
  };

  const previewBlueprint = async () => {
    if (!formData.blueprint) return;
    try {
      const res = await apiClient.get(`/get_blueprint_details/${formData.blueprint}/`);
      if (res.data.success) {
        setPreviewBlueprintData(res.data.blueprint);
        setShowBlueprintModal(true);
      }
    } catch (err) {
      setError("Failed to load blueprint details");
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (selectedChapters.length === 0 && !isOneMarkTest) {
      setError("Please select at least one chapter");
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    const data = new FormData();
    Object.keys(formData).forEach(key => {
      if (key === 'chapters') {
        data.append('chapters', selectedChapters.join(','));
      } else {
        data.append(key, formData[key]);
      }
    });

    if (isOneMarkTest) {
      data.append('num_one_mark_questions', numOneMarkQuestions);
    }

    additionalFiles.forEach(file => {
      data.append('additional_docs', file);
    });

    try {
      const res = await apiClient.post('/papers/', data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      const queued = res?.data?.status === 'queued' && !res?.data?.task_id;
      setSuccess(queued
        ? "Queued — this paper will start automatically when your current one finishes."
        : "Question paper generation started successfully!");
      setTimeout(() => router.push('/dashboard'), 2000);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.detail || "Failed to generate paper");
      setSubmitting(false);
    }
  };

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );

  const difficultyConfig = {
    Easy: { color: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200', gradient: 'from-emerald-400 to-emerald-500', icon: <CheckCircle size={16} /> },
    Medium: { color: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-200', gradient: 'from-amber-400 to-amber-500', icon: <BarChart size={16} /> },
    Hard: { color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200', gradient: 'from-red-400 to-red-500', icon: <Zap size={16} /> },
  };

  const diffStyle = difficultyConfig[formData.difficulty] || difficultyConfig.Easy;

  // A small helper component for section headings
  const SectionHeading = ({ number, title, icon: Icon }) => (
    <div className="flex items-center gap-3 mb-5">
      <div className="w-8 h-8 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 font-bold text-sm">
        {number}
      </div>
      <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
        {title}
        {Icon && <Icon size={18} className="text-slate-400" />}
      </h3>
    </div>
  );

  return (
    <div className="w-full pb-12 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 text-center max-w-2xl mx-auto">
        <div className="inline-flex items-center justify-center gap-1.5 px-4 py-1.5 bg-white border border-slate-200/60 shadow-sm rounded-full mb-4">
          <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
          <span className="text-[12px] font-bold text-slate-700 uppercase tracking-widest">AI Paper Generator</span>
        </div>
        <h1 className="text-[36px] font-extrabold text-slate-900 tracking-tight leading-tight mb-3">
          Create Perfect Exams <br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600">in Seconds.</span>
        </h1>
        <p className="text-[16px] text-slate-500 leading-relaxed">
          Configure parameters, select chapters, and let our AI craft a high-quality, perfectly formatted question paper tailored to your needs.
        </p>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6 max-w-4xl mx-auto" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6 max-w-4xl mx-auto" />}

      <form onSubmit={handleSubmit} className="max-w-6xl mx-auto grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-8">
        
        {/* Main Form Left Side */}
        <div className="space-y-6">
          
          {/* Block 1: Basics */}
          <div className="relative z-[60] bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <SectionHeading number="1" title="Core Details" icon={GraduationCap} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <CustomSelect
                label="Class / Grade"
                icon={GraduationCap}
                value={formData.class_name}
                onChange={(val) => handleInputChange({ target: { name: 'class_name', value: val } })}
                options={['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'].map(c => ({ label: `Class ${c}`, value: c }))}
                placeholder="Select Class"
              />
              <CustomSelect
                label="Subject"
                icon={BookOpen}
                value={formData.subject}
                onChange={(val) => handleInputChange({ target: { name: 'subject', value: val } })}
                options={subjects.map(s => ({ label: s, value: s }))}
                placeholder={loadingSubjects ? 'Loading subjects...' : formData.class_name ? 'Select Subject' : 'Select Class First'}
                disabled={!formData.class_name || loadingSubjects}
              />
            </div>
          </div>

          {/* Block 2: Pattern & Difficulty */}
          <div className="relative z-[50] bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <SectionHeading number="2" title="Exam Structure" icon={Layers} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-6">
              <CustomSelect
                label="Exam Pattern"
                icon={Layers}
                value={formData.pattern}
                onChange={(val) => handleInputChange({ target: { name: 'pattern', value: val } })}
                options={[
                  ...patterns.filter(p => p.pattern_source === 'one_mark_test').map(p => ({
                    label: `⚡ ${p.name}`,
                    value: p.id,
                  })),
                  ...patterns
                    .filter(p => p.pattern_source !== 'one_mark_test')
                    .sort((a, b) => {
                      const sel = formData.subject?.toLowerCase();
                      const cls = formData.class_name;
                      const aSubj = a.subject?.toLowerCase() === sel;
                      const bSubj = b.subject?.toLowerCase() === sel;
                      const aCls  = a.class_name === cls;
                      const bCls  = b.class_name === cls;
                      const aScore = (aSubj && aCls ? 3 : aSubj ? 2 : aCls ? 1 : 0);
                      const bScore = (bSubj && bCls ? 3 : bSubj ? 2 : bCls ? 1 : 0);
                      return bScore - aScore;
                    })
                    .map(p => ({
                      label: `${p.name} (${p.class_name} - ${p.subject})`,
                      value: p.id,
                    })),
                ]}
                placeholder="Select an exam pattern"
              />

              <CustomSelect
                label="Blueprint (Optional)"
                icon={Settings}
                value={formData.blueprint}
                onChange={(val) => handleInputChange({ target: { name: 'blueprint', value: val } })}
                options={blueprints.map(b => ({ label: b.name, value: b.id }))}
                placeholder="Auto-select blueprint"
              />
            </div>

            {/* Premium Radio Cards for Difficulty */}
            <div className="mb-2">
              <label className="flex items-center gap-2 text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-3">
                <Star size={14} className="text-indigo-500" strokeWidth={1.75} />
                Difficulty Level
              </label>
              <div className="grid grid-cols-3 gap-3">
                {Object.entries(difficultyConfig).map(([level, config]) => {
                  const isSelected = formData.difficulty === level;
                  return (
                    <button
                      key={level}
                      type="button"
                      onClick={() => handleInputChange({ target: { name: 'difficulty', value: level } })}
                      className={`relative flex flex-col items-center justify-center p-4 rounded-2xl border transition-all duration-200 overflow-hidden ${
                        isSelected 
                          ? `bg-white border-${config.gradient.split('-')[1]}-400 shadow-md ring-1 ring-${config.gradient.split('-')[1]}-400`
                          : 'bg-slate-50 border-slate-200 hover:border-slate-300 hover:bg-slate-100/50 text-slate-500'
                      }`}
                    >
                      {isSelected && (
                        <div className={`absolute top-0 left-0 w-full h-1 bg-gradient-to-r ${config.gradient}`} />
                      )}
                      <div className={`mb-2 ${isSelected ? config.color : 'text-slate-400'}`}>
                        {config.icon}
                      </div>
                      <span className={`text-[14px] font-bold ${isSelected ? 'text-slate-900' : 'text-slate-600'}`}>
                        {level}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* One Mark Test Add-on */}
            {isOneMarkTest && (
              <div className="mt-6 p-5 bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 rounded-2xl">
                <div className="flex items-center gap-2 mb-2">
                  <Zap size={18} className="text-amber-500 fill-amber-500" />
                  <h4 className="text-[13px] font-bold text-amber-900 uppercase tracking-wider">One Mark MCQ Configuration</h4>
                </div>
                <p className="text-[13px] text-amber-700/80 leading-relaxed mb-4">
                  Each question is a 4-option MCQ worth 1 mark. Options are randomly shuffled.
                  {formData.difficulty === 'Hard' && ' Hard difficulty generates more critical thinking and application based questions.'}
                </p>
                <div className="flex items-center gap-4">
                  <div className="relative">
                    <input
                      type="number"
                      min={5}
                      max={100}
                      value={numOneMarkQuestions}
                      onChange={e => setNumOneMarkQuestions(Math.max(5, Math.min(100, parseInt(e.target.value) || 20)))}
                      className="w-28 pl-4 pr-10 py-3 border border-amber-300/80 rounded-xl text-lg font-bold text-slate-800 focus:outline-none focus:ring-2 focus:ring-amber-400/50 bg-white"
                    />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 font-medium">Q</span>
                  </div>
                  <div className="flex gap-2">
                    {[10, 20, 30, 50].map(n => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setNumOneMarkQuestions(n)}
                        className={`px-3 py-1.5 rounded-xl text-[13px] font-bold transition-all duration-200 ${
                          numOneMarkQuestions === n
                            ? 'bg-amber-500 text-white shadow-sm'
                            : 'bg-white border border-amber-200 text-amber-700 hover:bg-amber-100'
                        }`}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                  <span className="ml-auto text-[13px] font-bold text-amber-600 bg-amber-100/50 px-3 py-1.5 rounded-lg">
                    Total: {numOneMarkQuestions} Marks
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Block 3: Syllabus / Chapters */}
          <div className="relative z-[40] bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <div className="flex items-center justify-between mb-5">
              <SectionHeading number="3" title="Syllabus Coverage" icon={LayoutGrid} />
              {availableChapters.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    if (selectedChapters.length === availableChapters.length) setSelectedChapters([]);
                    else setSelectedChapters([...availableChapters]);
                  }}
                  className="text-[12px] font-bold text-indigo-600 hover:text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors"
                >
                  {selectedChapters.length === availableChapters.length ? 'Deselect All' : 'Select All'}
                </button>
              )}
            </div>

            {!formData.subject ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400 border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50">
                <BookOpen size={32} className="mb-3 text-slate-300" strokeWidth={1.5} />
                <p className="text-[14px] font-semibold text-slate-500">Select a subject to view chapters</p>
              </div>
            ) : loadingChapters ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400 border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50">
                <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-500 rounded-full animate-spin mb-3" />
                <span className="text-[14px] font-medium text-slate-500">Loading curriculum...</span>
              </div>
            ) : availableChapters.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400 border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50">
                <Info size={32} className="mb-3 text-slate-300" strokeWidth={1.5} />
                <p className="text-[14px] font-semibold text-slate-500">No chapters found for this subject</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {availableChapters.map((chapter) => {
                  const isSelected = selectedChapters.includes(chapter);
                  return (
                    <button
                      key={chapter}
                      type="button"
                      onClick={() => toggleChapter(chapter)}
                      className={`text-left p-4 rounded-2xl border transition-all duration-200 flex items-start gap-3 group ${
                        isSelected 
                          ? 'bg-indigo-50/50 border-indigo-400/60 shadow-sm'
                          : 'bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center shrink-0 border transition-colors ${
                        isSelected ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 bg-white group-hover:border-indigo-400'
                      }`}>
                        {isSelected && <Check size={12} strokeWidth={3} />}
                      </div>
                      <span className={`text-[13px] leading-snug ${isSelected ? 'font-semibold text-indigo-900' : 'font-medium text-slate-700'}`}>
                        {chapter}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Block 4: Finishing Touches */}
          <div className="relative z-[30] bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <SectionHeading number="4" title="Finishing Touches" icon={FilePlus} />
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
              <div>
                <label className="flex items-center gap-2 text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-2">
                  <Clock size={14} className="text-indigo-500" strokeWidth={1.75} />
                  Time Duration
                </label>
                <div className="relative">
                  <input 
                    type="text" 
                    name="duration"
                    value={formData.duration}
                    onChange={handleInputChange}
                    placeholder="e.g. 3 hours"
                    className="w-full px-4 py-3.5 bg-slate-50 border border-slate-200 rounded-2xl outline-none text-[14px] font-bold text-slate-900 placeholder:text-slate-400 focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-500/10 transition-all duration-200"
                  />
                </div>
              </div>

              <div>
                <label className="flex items-center gap-2 text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-2">
                  <BarChart size={14} className="text-indigo-500" strokeWidth={1.75} />
                  Total Marks
                </label>
                <input 
                  type="number" 
                  name="total_marks"
                  value={formData.total_marks}
                  onChange={handleInputChange}
                  placeholder="e.g. 100"
                  className="w-full px-4 py-3.5 bg-slate-50 border border-slate-200 rounded-2xl outline-none text-[14px] font-bold text-slate-900 placeholder:text-slate-400 focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-500/10 transition-all duration-200"
                />
              </div>
            </div>

            <div>
              <label className="flex items-center gap-2 text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-3">
                <Upload size={14} className="text-indigo-500" strokeWidth={1.75} />
                Additional Reference Materials (Optional)
              </label>
              
              <div className="relative group">
                <input 
                  type="file" 
                  multiple 
                  onChange={handleFileChange}
                  accept=".pdf,.docx"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10" 
                />
                <div className="px-6 py-8 border-2 border-dashed border-slate-200 bg-slate-50/50 rounded-2xl flex flex-col items-center justify-center transition-all duration-200 group-hover:border-indigo-400 group-hover:bg-indigo-50/30">
                  <div className="w-12 h-12 bg-white rounded-xl shadow-sm border border-slate-100 flex items-center justify-center mb-3 group-hover:-translate-y-1 transition-transform duration-300">
                    <FilePlus size={20} className="text-indigo-500" strokeWidth={1.5} />
                  </div>
                  <p className="text-slate-700 font-semibold text-[14px]">Drop PDFs or Word documents here</p>
                  <p className="text-slate-400 text-[12px] mt-1">Or click to browse from your computer</p>
                </div>
              </div>

              {additionalFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-4">
                  {additionalFiles.map((file, i) => (
                    <div key={i} className="flex items-center gap-2 bg-slate-100 text-slate-700 px-3 py-2 rounded-xl text-[13px] font-medium border border-slate-200">
                      <FileText size={14} className="text-slate-500" />
                      <span className="truncate max-w-[200px]">{file.name}</span>
                      <button type="button" onClick={() => removeFile(i)} className="text-slate-400 hover:text-red-500 transition-colors ml-1">
                         <X size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Sidebar - Sticky Summary Container */}
        <div className="relative">
          <div className="sticky top-24 space-y-6">
            
            {/* Generate Action Card */}
            <div className="bg-slate-900 rounded-[28px] p-6 shadow-2xl shadow-slate-900/20 text-white relative overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/30 blur-2xl rounded-full" />
              <div className="absolute bottom-0 left-0 w-32 h-32 bg-purple-500/30 blur-2xl rounded-full" />
              
              <div className="relative z-10">
                <h3 className="text-xl font-bold mb-1">Ready to Generate?</h3>
                <p className="text-slate-400 text-sm mb-6">Review your settings and let AI do the heavy lifting.</p>
                
                <div className="space-y-3 mb-6">
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-slate-400">Chapters</span>
                    <span className="font-bold text-white">{selectedChapters.length} Selected</span>
                  </div>
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-slate-400">Difficulty</span>
                    <span className="font-bold text-white">{formData.difficulty}</span>
                  </div>
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-slate-400">Pattern</span>
                    <span className="font-bold text-white truncate max-w-[150px] text-right">
                      {patterns.find(p => String(p.id) === String(formData.pattern))?.name || 'Not set'}
                    </span>
                  </div>
                </div>

                <button 
                  type="submit" 
                  disabled={submitting}
                  className="w-full py-4 bg-white text-slate-900 rounded-2xl font-bold text-[15px] shadow-lg hover:shadow-xl hover:scale-[1.02] active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-50 disabled:hover:scale-100"
                >
                  {submitting ? (
                    <>
                      <div className="w-5 h-5 border-2 border-slate-300 border-t-slate-900 rounded-full animate-spin"></div>
                      Generating Paper...
                    </>
                  ) : (
                    <>
                      <Sparkles size={18} strokeWidth={2.5} className="text-indigo-600" />
                      Generate Question Paper
                    </>
                  )}
                </button>
                
                <button 
                  type="button" 
                  onClick={resetForm}
                  className="w-full mt-3 py-3 text-slate-400 hover:text-white text-sm font-semibold transition-colors flex justify-center items-center gap-2"
                >
                  <Undo size={14} /> Clear Form
                </button>
              </div>
            </div>

            {/* Pattern Details Summary (Only shows if pattern selected) */}
            <div className={`bg-white border border-slate-200/60 rounded-[28px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden transition-all duration-500 ${selectedPatternDetails ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none hidden'}`}>
              <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between">
                <h3 className="font-bold text-slate-800 flex items-center gap-2">
                  <Layers size={16} className="text-indigo-500" />
                  Pattern Overview
                </h3>
                {formData.blueprint && (
                  <button 
                    type="button"
                    onClick={previewBlueprint}
                    className="p-1.5 bg-indigo-50 text-indigo-600 hover:bg-indigo-100 rounded-lg transition-colors"
                    title="Preview full blueprint"
                  >
                    <Eye size={16} />
                  </button>
                )}
              </div>

              <div className="p-6">
                {loadingPatternDetails ? (
                  <div className="flex justify-center py-8">
                    <div className="w-6 h-6 border-2 border-slate-200 border-t-indigo-500 rounded-full animate-spin"></div>
                  </div>
                ) : selectedPatternDetails && (
                  <div className="space-y-5">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="p-4 bg-slate-50 rounded-2xl border border-slate-100 text-center">
                        <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">Total Marks</p>
                        <p className="text-2xl font-extrabold text-slate-900">{selectedPatternDetails.total_marks}</p>
                      </div>
                      <div className="p-4 bg-slate-50 rounded-2xl border border-slate-100 text-center">
                        <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">Questions</p>
                        <p className="text-2xl font-extrabold text-slate-900">{selectedPatternDetails.total_questions}</p>
                      </div>
                    </div>

                    {selectedPatternDetails.sections?.length > 0 && (
                       <div>
                         <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-3 px-1">Section Breakdown</p>
                         <div className="space-y-2">
                           {selectedPatternDetails.sections.map((sec, idx) => (
                             <div key={idx} className="flex items-center justify-between px-3 py-2.5 bg-white border border-slate-100 shadow-sm rounded-xl text-[12px]">
                               <div className="flex items-center gap-2.5">
                                 <span className="w-6 h-6 rounded-lg bg-indigo-50 text-indigo-600 font-bold flex items-center justify-center">{sec.name}</span>
                                 <span className="font-semibold text-slate-700 truncate max-w-[100px]">{sec.subject || sec.title || `Section ${sec.name}`}</span>
                               </div>
                               <div className="flex items-center gap-2 font-bold">
                                 <span className="text-slate-400">{sec.questions}Q</span>
                                 <span className="text-slate-900">{sec.marks}M</span>
                               </div>
                             </div>
                           ))}
                         </div>
                       </div>
                    )}
                  </div>
                )}
              </div>
            </div>

          </div>
        </div>
      </form>

      {/* Blueprint Preview Modal */}
      {showBlueprintModal && previewBlueprintData && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
          <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={() => setShowBlueprintModal(false)}></div>
          <div className="bg-white rounded-[32px] shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden relative z-10 flex flex-col">
            <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between bg-white shrink-0">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
                  <Layers size={22} strokeWidth={2} />
                </div>
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900 tracking-tight">{previewBlueprintData.name}</h3>
                  <p className="text-slate-500 font-medium text-[13px]">{previewBlueprintData.class_name} • {previewBlueprintData.subject}</p>
                </div>
              </div>
              <button onClick={() => setShowBlueprintModal(false)} className="w-10 h-10 bg-slate-50 rounded-full flex items-center justify-center text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition-all">
                <X size={20} />
              </button>
            </div>
            
            <div className="p-8 overflow-y-auto flex-1 bg-slate-50/50">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {previewBlueprintData.blueprint?.sections?.map((section, idx) => (
                  <div key={idx} className="p-6 bg-white border border-slate-200/60 shadow-sm rounded-2xl hover:shadow-md transition-shadow">
                    <div className="flex justify-between items-center mb-4">
                      <span className="px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-lg text-[11px] font-bold uppercase tracking-wider">
                        Section {section.name}
                      </span>
                      <span className="font-bold text-slate-900 bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-100 text-[12px]">
                        {section.marks} Marks
                      </span>
                    </div>
                    <h4 className="text-[16px] font-bold text-slate-900 mb-3 line-clamp-2 leading-tight">{section.title}</h4>
                    <div className="space-y-2">
                       <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Question Types</p>
                       <div className="flex flex-wrap gap-1.5">
                          {section.question_types?.map((type, tIdx) => (
                            <span key={tIdx} className="px-2.5 py-1 bg-slate-50 border border-slate-200/60 rounded-md text-[11px] font-semibold text-slate-600">{type}</span>
                          ))}
                       </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function GeneratorPage() {
  return (
    <Suspense fallback={<LoadingSpinner message="Loading AI Studio..." />}>
      <GeneratorContent />
    </Suspense>
  );
}
