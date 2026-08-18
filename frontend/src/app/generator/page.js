'use client';

import { useState, useEffect, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { 
  Plus, X, Upload, Eye, EyeOff, Zap,
  Settings, BookOpen, Layers, BarChart, FilePlus,
  ArrowRight, RefreshCcw, ChevronRight, Users, Clock, Star,
  CheckCircle, Info, Undo, AlertCircle, GraduationCap
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

  // Load chapters when subject changes.
  useEffect(() => {
    if (formData.subject && formData.class_name) {
      loadChapters();
    } else {
      setAvailableChapters([]);
      setSelectedChapters([]);
    }
  }, [formData.subject, formData.class_name]);

  // Blueprints depend on the PATTERN as well: a blueprint pins that pattern's printed question
  // numbers, so one built for another pattern would map units onto the wrong questions (the worker
  // rejects it). Re-fetch whenever the pattern changes and clear any stale selection.
  useEffect(() => {
    if (formData.subject && formData.class_name && formData.pattern) {
      loadBlueprints();
    } else {
      setBlueprints([]);
    }
    setFormData(prev => (prev.blueprint ? { ...prev, blueprint: '' } : prev));
  }, [formData.subject, formData.class_name, formData.pattern]);

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
      const res = await apiClient.get(`/get_blueprints/?class_name=${encodeURIComponent(formData.class_name)}&subject=${encodeURIComponent(formData.subject)}&pattern=${encodeURIComponent(formData.pattern)}`);
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
        // It's a blueprint ID - call the discovery utility
        res = await apiClient.get(`/get_blueprint_details/${patternId}/`);
        
        if (res.data.success && res.data.blueprint) {
          const bp = res.data.blueprint;
          const sections = bp.blueprint?.sections || bp.sections || [];
          
          // Normalize the blueprint data for the Pattern Info Card
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
        // It's a standard pattern ID - call the patterns viewset
        res = await apiClient.get(`/patterns/${patternId}/`);
        setSelectedPatternDetails(res.data);
      }
    } catch (err) {
      console.error("Error loading pattern details", err);
      // Fallback: If one failed, try the other as a safety measure
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

  const handleAddChapter = (chapter) => {
    if (!selectedChapters.includes(chapter)) {
      setSelectedChapters(prev => [...prev, chapter]);
    }
  };

  const handleRemoveChapter = (chapter) => {
    setSelectedChapters(prev => prev.filter(c => c !== chapter));
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
      // Use the standard REST API /papers/ endpoint
      // It includes all logic (Celery, Text Extraction) and returns JSON
      const res = await apiClient.post('/papers/', data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      // If another generation is already running, this paper is queued (no task dispatched yet)
      // and starts automatically when the current one finishes.
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
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">AI Generator</span>
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight">Generate Question Paper</h1>
          <p className="text-gray-500 font-medium text-lg mt-1 tracking-tight">Configure AI to generate professional-grade exam content.</p>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">
          <div className="glass-card shadow-xl mb-12 overflow-visible relative z-30">
            <div className="p-6 border-b border-gray-100 flex items-center gap-3 bg-white/50 rounded-t-[32px]">
              <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center">
                <Settings size={18} />
              </div>
              <h2 className="text-xl font-black text-gray-900">Paper Configuration</h2>
            </div>
            
            <form onSubmit={handleSubmit} className="p-8 space-y-8">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Class */}
                <CustomSelect
                  label="Class"
                  icon={GraduationCap}
                  value={formData.class_name}
                  onChange={(val) => handleInputChange({ target: { name: 'class_name', value: val } })}
                  options={['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'].map(c => ({ label: `Class ${c}`, value: c }))}
                  placeholder="Select Class"
                  className="space-y-2"
                />

                {/* Subject */}
                <CustomSelect
                  label="Subject"
                  icon={BookOpen}
                  value={formData.subject}
                  onChange={(val) => handleInputChange({ target: { name: 'subject', value: val } })}
                  options={subjects.map(s => ({ label: s, value: s }))}
                  placeholder={loadingSubjects ? 'Loading subjects...' : formData.class_name ? 'Select Subject' : 'Select Class First'}
                  disabled={!formData.class_name || loadingSubjects}
                  className="space-y-2"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Exam Pattern */}
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
                        // Full match (class + subject) > subject-only > class-only > no match
                        const aScore = (aSubj && aCls ? 3 : aSubj ? 2 : aCls ? 1 : 0);
                        const bScore = (bSubj && bCls ? 3 : bSubj ? 2 : bCls ? 1 : 0);
                        return bScore - aScore;
                      })
                      .map(p => ({
                        label: `${p.name} (${p.class_name} - ${p.subject})`,
                        value: p.id,
                      })),
                  ]}
                  placeholder="Select a pattern"
                  className="space-y-2"
                />

                {/* Difficulty */}
                <CustomSelect
                  label="Difficulty Level"
                  icon={Star}
                  value={formData.difficulty}
                  onChange={(val) => handleInputChange({ target: { name: 'difficulty', value: val } })}
                  options={[
                    { label: 'Easy', value: 'Easy' },
                    { label: 'Medium', value: 'Medium' },
                    { label: 'Hard', value: 'Hard' }
                  ]}
                  placeholder="Select difficulty"
                  className="space-y-2"
                />
              </div>

              {/* One Mark Test: question count field */}
              {isOneMarkTest && (
                <div className="p-5 bg-amber-50 border border-amber-200 rounded-2xl space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">⚡</span>
                    <p className="text-sm font-black text-amber-800 uppercase tracking-wider">One Mark Test Configuration</p>
                  </div>
                  <p className="text-xs text-amber-700">
                    Each question is a 4-option MCQ (1 mark). Correct answers are distributed randomly across options.
                    {formData.difficulty === 'Hard' && ' Hard difficulty generates critical thinking questions.'}
                  </p>
                  <div className="space-y-1">
                    <label className="text-xs font-black text-amber-800 uppercase tracking-wider">
                      Number of Questions
                    </label>
                    <div className="flex items-center gap-3">
                      <input
                        type="number"
                        min={5}
                        max={100}
                        value={numOneMarkQuestions}
                        onChange={e => setNumOneMarkQuestions(Math.max(5, Math.min(100, parseInt(e.target.value) || 20)))}
                        className="w-28 px-4 py-3 border border-amber-300 rounded-xl text-sm font-bold text-center focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
                      />
                      <span className="text-xs text-amber-600 font-medium">× 1 mark = {numOneMarkQuestions} marks total</span>
                    </div>
                    <div className="flex gap-2 pt-1">
                      {[10, 20, 25, 30, 50].map(n => (
                        <button
                          key={n}
                          type="button"
                          onClick={() => setNumOneMarkQuestions(n)}
                          className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-colors ${
                            numOneMarkQuestions === n
                              ? 'bg-amber-600 text-white'
                              : 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                          }`}
                        >
                          {n}Q
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Blueprint */}
                <CustomSelect
                  label="Blueprint (Optional)"
                  icon={Settings}
                  value={formData.blueprint}
                  onChange={(val) => handleInputChange({ target: { name: 'blueprint', value: val } })}
                  options={blueprints.map(b => ({ label: b.name, value: b.id }))}
                  placeholder="Auto-select blueprint"
                  className="space-y-2"
                />

                {/* Preview Button */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-black text-gray-700 uppercase tracking-wider">
                    <Eye size={16} className="text-blue-500" />
                    Blueprint Preview
                  </label>
                  <button 
                    type="button"
                    onClick={previewBlueprint}
                    disabled={!formData.blueprint}
                    className="w-full px-5 py-4 bg-indigo-50 text-indigo-600 rounded-2xl font-black text-sm uppercase tracking-wider transition-all hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    <Eye size={18} />
                    Preview Selection
                  </button>
                  <p className="text-[10px] font-bold text-gray-400 uppercase ml-1">View structure before generation</p>
                </div>
              </div>

              {/* Chapters Selection */}
              <div className="space-y-3 pt-4 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm font-black text-gray-700 uppercase tracking-wider">
                    <BookOpen size={16} className="text-blue-500" />
                    Chapters/Units Selection
                  </label>
                  {availableChapters.length > 0 && (
                    <span className="text-[10px] font-bold text-blue-600 uppercase tracking-wider">
                      {selectedChapters.length}/{availableChapters.length} selected
                    </span>
                  )}
                </div>

                {!formData.subject ? (
                  <div className="flex flex-col items-center justify-center py-8 text-gray-400 border-2 border-dashed border-gray-200 rounded-2xl">
                    <BookOpen size={28} className="mb-2 opacity-20" />
                    <p className="text-[10px] uppercase font-black tracking-widest text-gray-500">Select a subject first</p>
                  </div>
                ) : loadingChapters ? (
                  <div className="flex items-center justify-center py-8 text-gray-400">
                    <div className="w-4 h-4 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin mr-2" />
                    <span className="text-sm font-bold">Loading chapters…</span>
                  </div>
                ) : availableChapters.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-gray-400 border-2 border-dashed border-gray-200 rounded-2xl">
                    <BookOpen size={28} className="mb-2 opacity-20" />
                    <p className="text-sm font-bold">No chapters found for this subject</p>
                  </div>
                ) : (
                  <div className="border border-gray-200 rounded-2xl overflow-hidden">
                    {/* Select All */}
                    <label className="flex items-center gap-3 px-4 py-3 bg-gray-50 border-b border-gray-200 cursor-pointer hover:bg-gray-100 transition-colors select-none">
                      <input
                        type="checkbox"
                        checked={selectedChapters.length === availableChapters.length}
                        ref={el => { if (el) el.indeterminate = selectedChapters.length > 0 && selectedChapters.length < availableChapters.length; }}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedChapters([...availableChapters]);
                          } else {
                            setSelectedChapters([]);
                          }
                        }}
                        className="w-4 h-4 accent-blue-600 cursor-pointer"
                      />
                      <span className="text-xs font-black text-gray-700 uppercase tracking-wider">Select All</span>
                    </label>

                    {/* Chapter list */}
                    <div className="divide-y divide-gray-100 max-h-64 overflow-y-auto">
                      {availableChapters.map((chapter) => {
                        const checked = selectedChapters.includes(chapter);
                        return (
                          <label
                            key={chapter}
                            className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-blue-50/50 transition-colors select-none ${checked ? 'bg-blue-50/30' : ''}`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => checked ? handleRemoveChapter(chapter) : handleAddChapter(chapter)}
                              className="w-4 h-4 accent-blue-600 cursor-pointer flex-shrink-0"
                            />
                            <span className={`text-sm ${checked ? 'font-bold text-blue-700' : 'font-medium text-gray-700'}`}>
                              {chapter}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}

                <p className="text-[10px] font-bold text-gray-500 uppercase ml-1 flex items-center gap-1">
                  <Info size={12} />
                  Choose one or more chapters to cover in the paper.
                </p>
              </div>

              {/* Additional Documents */}
              <div className="space-y-4 pt-4 border-t border-gray-100">
                <label className="flex items-center gap-2 text-sm font-black text-gray-700 uppercase tracking-wider">
                  <Upload size={16} className="text-blue-500" />
                  Additional Documents (Optional)
                </label>
                
                <div className="relative group">
                  <input 
                    type="file" 
                    multiple 
                    onChange={handleFileChange}
                    accept=".pdf,.docx"
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10" 
                  />
                  <div className="p-10 border-2 border-dashed border-gray-200 bg-gray-50/50 rounded-3xl flex flex-col items-center justify-center transition-all group-hover:border-blue-400 group-hover:bg-blue-50/30">
                    <div className="w-16 h-16 bg-white rounded-2xl shadow-sm flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
                      <FilePlus size={32} className="text-blue-500" />
                    </div>
                    <p className="text-gray-900 font-extrabold text-sm uppercase tracking-widest">Click or drag to upload</p>
                    <p className="text-gray-400 text-[10px] font-bold mt-2 uppercase tracking-widest">PDF or Word files (.pdf, .docx)</p>
                  </div>
                </div>

                {additionalFiles.length > 0 && (
                  <div className="flex flex-wrap gap-3">
                    {additionalFiles.map((file, i) => (
                      <div key={i} className="flex items-center gap-3 bg-emerald-50 text-emerald-700 px-4 py-3 rounded-2xl text-xs font-black border border-emerald-100 animate-in slide-in-from-bottom-2">
                        <span>{file.name}</span>
                        <button type="button" onClick={() => removeFile(i)} className="text-emerald-400 hover:text-emerald-700">
                          <X size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-4 border-t border-gray-100">
                {/* Duration */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-black text-gray-700 uppercase tracking-wider">
                    <Clock size={16} className="text-blue-500" />
                    Time Duration
                  </label>
                  <input 
                    type="text" 
                    name="duration"
                    value={formData.duration}
                    onChange={handleInputChange}
                    placeholder="e.g. 3 hours"
                    className="w-full px-5 py-4 bg-gray-50/50 border border-gray-200 rounded-2xl outline-none font-bold text-gray-900"
                  />
                </div>

                {/* Total Marks */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-black text-gray-700 uppercase tracking-wider">
                    <Star size={16} className="text-blue-500" />
                    Total Marks
                  </label>
                  <input 
                    type="number" 
                    name="total_marks"
                    value={formData.total_marks}
                    onChange={handleInputChange}
                    placeholder="e.g. 100"
                    className="w-full px-5 py-4 bg-gray-50/50 border border-gray-200 rounded-2xl outline-none font-bold text-gray-900 placeholder:text-gray-400"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-4 pt-8 border-t border-gray-100">
                <button 
                  type="button" 
                  onClick={resetForm}
                  className="px-8 py-4 bg-gray-100 text-gray-700 rounded-2xl font-black text-sm uppercase tracking-wider hover:bg-gray-200 transition-all duration-300 flex items-center gap-2 hover:-translate-y-0.5 active:scale-95"
                >
                  <Undo size={18} />
                  Reset
                </button>
                <button 
                  type="submit" 
                  disabled={submitting}
                  className="px-10 py-4 bg-blue-600 text-white rounded-2xl font-black text-sm uppercase tracking-wider shadow-2xl shadow-blue-200 hover:bg-blue-700 transition-all duration-300 flex items-center gap-3 disabled:opacity-50 group hover:-translate-y-1 active:scale-95"
                >
                  {submitting ? (
                    <>
                      <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                      Generating...
                    </>
                  ) : (
                    <>
                      Generate Paper
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="space-y-8">
          {/* Pattern Info Card */}
          <div className={`glass-card p-0 overflow-hidden transition-all duration-500 ${selectedPatternDetails ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'}`}>
            <div className={`p-6 text-white flex items-center gap-3 transition-colors duration-300 ${
              formData.difficulty === 'Easy' ? 'bg-green-500' :
              formData.difficulty === 'Hard' ? 'bg-red-500' :
              'bg-amber-500'
            }`}>
              <AlertCircle size={22} className="animate-pulse" />
              <h3 className="text-lg font-black tracking-tight">Pattern Details</h3>
              <span className="ml-auto text-xs font-bold uppercase tracking-widest opacity-80">{formData.difficulty}</span>
            </div>
            <div className="p-8 space-y-6">
              {loadingPatternDetails ? (
                <div className="flex items-center justify-center py-12">
                  <div className={`w-8 h-8 border-3 rounded-full animate-spin ${
                    formData.difficulty === 'Easy' ? 'border-green-100 border-t-green-500' :
                    formData.difficulty === 'Hard' ? 'border-red-100 border-t-red-500' :
                    'border-amber-100 border-t-amber-500'
                  }`}></div>
                </div>
              ) : selectedPatternDetails && (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 bg-gray-50 rounded-2xl border border-gray-100">
                      <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">Total Marks</p>
                      <p className="text-2xl font-black text-gray-900">{selectedPatternDetails.total_marks}</p>
                    </div>
                    <div className="p-4 bg-gray-50 rounded-2xl border border-gray-100">
                      <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">Questions</p>
                      <p className="text-2xl font-black text-gray-900">{selectedPatternDetails.total_questions}</p>
                    </div>
                  </div>

                  <div className="space-y-4 pt-4 mt-2">
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest flex items-center gap-2 pl-1">
                       <Layers size={14} className="text-blue-500" />
                       Pattern Structure
                    </p>
                    {/* Compound subject: render per-subject accordion */}
                    {selectedPatternDetails.sections?.length > 0 && selectedPatternDetails.sections[0]?.subject ? (
                      <div className="rounded-2xl border border-gray-100 overflow-hidden">
                        {/* Header row */}
                        <div className="grid grid-cols-[28px_1fr_40px_44px_56px_32px_32px_24px] bg-gray-50 border-b border-gray-200 px-3 py-2">
                          {['§','Subject','Qs','Marks','Choice','HOTS','CBQ',''].map((h, i) => (
                            <span key={i} className={`text-[8px] font-black text-gray-400 uppercase tracking-widest ${i >= 2 && i < 7 ? 'text-center' : ''}`}>{h}</span>
                          ))}
                        </div>

                        {selectedPatternDetails.sections.map((sec, idx) => {
                          const isOpen = expandedSections.has(idx);
                          return (
                            <div key={idx} className="border-b border-gray-50 last:border-0">
                              {/* Clickable summary row */}
                              <button
                                type="button"
                                onClick={() => toggleSection(idx)}
                                className="w-full grid grid-cols-[28px_1fr_40px_44px_56px_32px_32px_24px] items-center px-3 py-2.5 hover:bg-blue-50/50 transition-colors text-left"
                              >
                                <span className="inline-flex items-center justify-center w-6 h-6 bg-blue-600 text-white rounded-lg text-[9px] font-black">{sec.name}</span>
                                <span className="font-bold text-gray-900 text-xs truncate pr-1">{sec.subject || sec.title}</span>
                                <span className="text-center text-xs font-bold text-gray-600">{sec.questions}</span>
                                <span className="text-center text-xs font-black text-gray-900">{sec.marks}M</span>
                                <span className="text-center text-[10px] font-bold">
                                  {sec.internal_choice
                                    ? <span className="text-emerald-700">Yes{sec.choices ? ` (${sec.choices})` : ''}</span>
                                    : <span className="text-gray-400">No</span>}
                                </span>
                                <span className="text-center text-[10px] font-bold text-amber-700">{sec.hots || '—'}</span>
                                <span className="text-center text-[10px] font-bold text-purple-700">{sec.cbq || '—'}</span>
                                <ChevronRight size={12} className={`text-gray-400 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} />
                              </button>

                              {/* Expanded detail panel */}
                              {isOpen && (
                                <div className="px-4 pb-3 bg-blue-50/30 border-t border-blue-100/50">
                                  <div className="pt-3 space-y-2.5">
                                    {/* Blueprint info badges */}
                                    <div className="flex flex-wrap gap-1.5">
                                      {sec.hots > 0 && (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-100 text-amber-800 rounded-full text-[9px] font-black uppercase tracking-wider">
                                          ★ {sec.hots} HOTS
                                        </span>
                                      )}
                                      {sec.cbq > 0 && (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-800 rounded-full text-[9px] font-black uppercase tracking-wider">
                                          ❖ {sec.cbq} CBQ
                                        </span>
                                      )}
                                      {sec.internal_choice && (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-full text-[9px] font-black uppercase tracking-wider">
                                          ⇄ {sec.choices || ''} Internal Choice{sec.choices > 1 ? 's' : ''}
                                        </span>
                                      )}
                                    </div>

                                    {/* Question type breakdown from question_types array */}
                                    {sec.question_types?.length > 0 && (
                                      <div className="rounded-xl overflow-hidden border border-gray-100">
                                        <table className="w-full text-[9px]">
                                          <thead>
                                            <tr className="bg-gray-100">
                                              <th className="text-left px-2 py-1 font-black text-gray-500 uppercase tracking-wider">Questions</th>
                                              <th className="text-left px-2 py-1 font-black text-gray-500 uppercase tracking-wider">Type</th>
                                              <th className="text-center px-2 py-1 font-black text-gray-500 uppercase tracking-wider">Marks</th>
                                              <th className="text-center px-2 py-1 font-black text-gray-500 uppercase tracking-wider">Total</th>
                                            </tr>
                                          </thead>
                                          <tbody>
                                            {sec.question_types.map((qt, qi) => (
                                              <tr key={qi} className="border-t border-gray-100">
                                                <td className="px-2 py-1 font-bold text-gray-700">{qt.range || `${qt.count}Q`}</td>
                                                <td className="px-2 py-1 text-gray-600">{qt.type}</td>
                                                <td className="px-2 py-1 text-center font-bold text-gray-700">{qt.marks_each}M</td>
                                                <td className="px-2 py-1 text-center font-black text-gray-900">{qt.total || qt.count * qt.marks_each}M</td>
                                              </tr>
                                            ))}
                                          </tbody>
                                        </table>
                                      </div>
                                    )}

                                    {/* Notes text */}
                                    {sec.notes && (
                                      <p className="text-[9px] text-gray-500 leading-relaxed bg-white rounded-xl px-3 py-2 border border-gray-100">
                                        {sec.notes}
                                      </p>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Total footer */}
                        <div className="grid grid-cols-[28px_1fr_40px_44px_56px_32px_32px_24px] items-center px-3 py-2 bg-gray-50 border-t-2 border-gray-200">
                          <span></span>
                          <span className="text-[9px] font-black text-gray-500 uppercase tracking-widest">Total</span>
                          <span className="text-center text-xs font-black text-gray-900">
                            {selectedPatternDetails.sections.reduce((s, r) => s + (r.questions || 0), 0)}
                          </span>
                          <span className="text-center text-xs font-black text-gray-900">
                            {selectedPatternDetails.sections.reduce((s, r) => s + (r.marks || 0), 0)}M
                          </span>
                          <span colSpan={4}></span>
                        </div>
                      </div>
                    ) : (
                      /* Traditional format: render as section rows */
                      <div className="space-y-2">
                        {selectedPatternDetails.sections?.map((sec, idx) => (
                          <div key={idx} className="flex items-center justify-between px-3 py-2.5 bg-gray-50 rounded-xl border border-gray-100 text-xs">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center justify-center w-6 h-6 bg-blue-600 text-white rounded-lg text-[9px] font-black">{sec.name}</span>
                              <span className="font-bold text-gray-800 truncate max-w-[140px]">{sec.title}</span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className="text-gray-500 font-bold">{sec.questions}Q</span>
                              <span className="font-black text-gray-900">{sec.marks}M</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>

          {[
            { label: 'Fast Generation', sub: 'Generate papers in minutes', icon: Clock, color: 'text-indigo-600', bg: 'bg-indigo-50' },
            { label: 'Quality Assured', sub: 'Verified output format', icon: CheckCircle, color: 'text-emerald-600', bg: 'bg-emerald-50' },
          ].map((item, i) => (
            <div key={i} className="glass-card p-8 hover:bg-white transition-all group">
              <div className="flex items-center gap-6">
                <div className={`w-14 h-14 ${item.bg} ${item.color} rounded-2xl flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform`}>
                  <item.icon size={26} />
                </div>
                <div>
                  <h4 className="font-extrabold text-gray-900">{item.label}</h4>
                  <p className="text-sm font-bold text-gray-500 uppercase tracking-tight mt-0.5">{item.sub}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Blueprint Preview Modal */}
      {showBlueprintModal && previewBlueprintData && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={() => setShowBlueprintModal(false)}></div>
          <div className="bg-white rounded-[40px] shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden relative z-10 animate-in fade-in zoom-in-95 duration-300">
            <div className="p-8 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-blue-600 text-white rounded-2xl flex items-center justify-center shadow-lg shadow-blue-200">
                  <Eye size={24} />
                </div>
                <div>
                  <h3 className="text-2xl font-black text-gray-900 tracking-tight">{previewBlueprintData.name}</h3>
                  <p className="text-gray-500 font-bold text-sm uppercase tracking-wider">{previewBlueprintData.class_name} • {previewBlueprintData.subject}</p>
                </div>
              </div>
              <button onClick={() => setShowBlueprintModal(false)} className="w-12 h-12 bg-white border border-gray-100 rounded-2xl flex items-center justify-center text-gray-400 hover:text-gray-900 hover:shadow-md transition-all">
                <X size={24} />
              </button>
            </div>
            
            <div className="p-8 overflow-y-auto max-h-[calc(90vh-180px)] space-y-8 custom-scrollbar">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {previewBlueprintData.blueprint?.sections?.map((section, idx) => (
                  <div key={idx} className="p-6 bg-gray-50 border border-gray-100 rounded-[30px] hover:border-blue-200 transition-colors group">
                    <div className="flex justify-between items-center mb-4">
                      <div className="px-4 py-1.5 bg-blue-600 text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
                        Section {section.name}
                      </div>
                      <div className="font-black text-gray-900 bg-white px-3 py-1.5 rounded-xl border border-gray-100">
                        {section.marks} Marks
                      </div>
                    </div>
                    <h4 className="text-lg font-black text-gray-900 mb-2 truncate">{section.title}</h4>
                    <div className="space-y-2">
                       <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest">Question Types</p>
                       <div className="flex flex-wrap gap-2">
                          {section.question_types?.map((type, tIdx) => (
                            <span key={tIdx} className="px-2 py-1 bg-white border border-gray-100 rounded-lg text-[10px] font-bold text-gray-600">{type}</span>
                          ))}
                       </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-8 bg-gray-50/50 border-t border-gray-100 flex justify-end">
              <button 
                onClick={() => setShowBlueprintModal(false)}
                className="px-10 py-4 bg-gray-900 text-white rounded-2xl font-black text-sm uppercase tracking-wider hover:bg-black transition-all"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function GeneratorPage() {
  return (
    <Suspense fallback={<LoadingSpinner message="Pre-configuring AI..." />}>
      <GeneratorContent />
    </Suspense>
  );
}


