'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { 
  Plus, Sparkles, ArrowLeft, Wand2, Info, 
  BookOpen, GraduationCap, FileText, CheckCircle, 
  Settings, Calculator, Send, Hash, RefreshCw, 
  Eye, FileInput, ChevronDown, Activity, AlignLeft,
  FileSearch, Zap, Lightbulb
} from 'lucide-react';
import Link from 'next/link';
import apiClient from '@/lib/api';
import SuccessAlert from '@/components/SuccessAlert';
import ErrorAlert from '@/components/ErrorAlert';
import CustomSelect from '@/components/CustomSelect';

export default function AICreateBlueprintPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  const [formData, setFormData] = useState({
    name: '',
    class_name: '',
    subject: '',
    text_pattern: '',
    blueprint_type: 'template' // 'template' or 'exam'
  });

  const classes = ['6', '7', '8', '9', '10', '11', '12'];
  const subjects = ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology', 'Social Science'];

  const examples = {
    english: "Reading Comprehension - 5 marks\nWriting - 10 marks\nGrammar - 5 marks\nLiterature - 20 marks\n- 5 MCQ each 1 mark\n- 3 Short Answer each 2 marks\n- 2 Long Answer each 4.5 marks",
    math: "Section A: 10 MCQ each 1 mark\nSection B: 5 Short Answer each 2 marks\nSection C: 3 Long Answer each 5 marks from Algebra and Geometry"
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const loadExample = () => {
    setFormData(prev => ({
      ...prev,
      class_name: '8',
      subject: 'English',
      name: 'Class 8 Term Exam Pattern',
      text_pattern: examples.english
    }));
  };

  const handlePreview = async () => {
    if (!formData.text_pattern) {
      setError('Please provide a pattern to preview.');
      return;
    }
    setPreviewing(true);
    setError(null);
    try {
      const res = await apiClient.post('/blueprint/preview/', {
        text_pattern: formData.text_pattern,
        class_name: formData.class_name,
        subject: formData.subject
      });
      alert("AI Interpretation:\n" + JSON.stringify(res.data.structure, null, 2));
    } catch (err) {
      setError(err.response?.data?.error || 'Preview failed');
    } finally {
      setPreviewing(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      if (!formData.text_pattern || !formData.class_name || !formData.subject) {
        throw new Error('Please fill in all required fields and provide the text pattern.');
      }

      await apiClient.post('/generate-blueprint/', {
        text_pattern: formData.text_pattern,
        class_name: formData.class_name,
        subject: formData.subject,
        blueprint_name: formData.name || `Class ${formData.class_name} ${formData.subject} AI Blueprint`,
        blueprint_type: formData.blueprint_type
      });

      setSuccess('AI Blueprint generated and saved successfully!');
      setTimeout(() => router.push('/blueprints'), 2000);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to generate blueprint');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full relative py-2 mb-20 px-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-12">
        <div className="flex items-center gap-5">
          <div className="w-16 h-16 bg-white shadow-2xl shadow-purple-500/10 border border-purple-100 rounded-[28px] flex items-center justify-center group transform hover:rotate-6 transition-all duration-500">
            <Sparkles size={32} className="text-purple-600" />
          </div>
          <div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight">AI Pattern Generator</h1>
            <p className="text-gray-500 font-bold flex items-center gap-2 text-sm">
              <span className="w-2 h-2 rounded-full bg-purple-500 animate-pulse"></span>
              Transform text descriptions into paper architecture
            </p>
          </div>
        </div>
        <Link href="/blueprints" className="bg-white/80 backdrop-blur-sm text-gray-400 hover:text-purple-600 px-6 py-3 rounded-2xl font-black text-[10px] uppercase tracking-widest transition-all border border-gray-100 flex items-center gap-2 hover:shadow-lg hover:-translate-y-0.5 active:scale-95 group">
          <ArrowLeft size={14} className="group-hover:-translate-x-1 transition-transform" />
          Back to list
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="space-y-10">
        <div className="bg-white/80 backdrop-blur-xl rounded-[40px] shadow-2xl shadow-purple-500/5 border border-white/20 p-10 group transition-all duration-500 hover:shadow-purple-500/10">
          <h2 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-10 flex items-center gap-2">
            <Info size={14} className="text-purple-500" />
            Extraction Configuration
          </h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10 mb-10">
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Grade / Class</label>
              <CustomSelect
                icon={GraduationCap}
                value={formData.class_name}
                onChange={(val) => setFormData(prev => ({ ...prev, class_name: val }))}
                options={classes.map(c => ({ label: `Class ${c}`, value: c }))}
                placeholder="Select Class"
              />
            </div>
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Subject Matter</label>
              <CustomSelect
                icon={BookOpen}
                value={formData.subject}
                onChange={(val) => setFormData(prev => ({ ...prev, subject: val }))}
                options={subjects.map(s => ({ label: s, value: s }))}
                placeholder="Select Subject"
              />
            </div>
          </div>

          <div className="space-y-3 mb-10">
            <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Blueprint Title (Optional)</label>
            <div className="relative group/input">
              <div className="absolute left-5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within/input:text-purple-500 transition-colors">
                <FileInput size={18} />
              </div>
              <input 
                type="text" name="name" value={formData.name} onChange={handleInputChange}
                className="w-full pl-14 pr-6 py-4.5 bg-gray-50/50 border border-gray-100 rounded-[22px] font-bold text-gray-900 focus:bg-white focus:border-purple-600 transition-all outline-none shadow-sm group-hover/input:shadow-md"
                placeholder="e.g. Mid-Term Exam 2024"
              />
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between px-1">
              <label className="text-[10px] font-black text-gray-600 uppercase tracking-widest ml-1">Describe Pattern / Content</label>
              <button 
                type="button" onClick={loadExample}
                className="text-[10px] font-black text-purple-600 uppercase tracking-widest hover:text-purple-800 transition-colors flex items-center gap-2 hover:scale-105"
              >
                <Zap size={14} className="fill-purple-600" /> Try Example
              </button>
            </div>
            <div className="relative group/textarea">
               <textarea 
                name="text_pattern" value={formData.text_pattern} onChange={handleInputChange}
                rows={10}
                className="w-full p-8 bg-gray-900 text-purple-100 border-none rounded-[36px] font-mono text-sm leading-relaxed focus:ring-8 focus:ring-purple-500/10 transition-all outline-none shadow-2xl selection:bg-purple-500/30"
                placeholder="Example: Section A: 5 MCQs (1 mark each). Section B: 2 Short questions (2 marks each)..."
                required
              />
              <div className="absolute right-8 bottom-8 opacity-20 group-focus-within/textarea:opacity-50 transition-opacity">
                <AlignLeft size={32} className="text-white" />
              </div>
            </div>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest text-center pt-4">
              Our AI engine will parse this text and structure your paper sections automatically
            </p>
          </div>
        </div>

        {/* Save As Options */}
        <div className="bg-white/80 backdrop-blur-xl rounded-[32px] p-8 border border-white/20 shadow-xl shadow-gray-200/50">
             <h3 className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] mb-6 ml-1">Blueprint Category Selection</h3>
             <div className="flex flex-wrap items-center gap-10">
                <label className="flex items-center gap-4 cursor-pointer group">
                  <div className="relative flex items-center justify-center">
                    <input 
                      type="radio" 
                      name="blueprint_type"
                      value="template"
                      checked={formData.blueprint_type === 'template'}
                      onChange={handleInputChange}
                      className="w-6 h-6 appearance-none rounded-full border-2 border-slate-200 checked:border-purple-600 transition-all group-hover:border-purple-300"
                    />
                    {formData.blueprint_type === 'template' && <div className="absolute w-3 h-3 bg-purple-600 rounded-full animate-in zoom-in"></div>}
                  </div>
                  <div className="flex flex-col">
                    <span className={`text-[11px] font-black uppercase tracking-widest transition-colors ${formData.blueprint_type === 'template' ? 'text-gray-900' : 'text-gray-400'}`}>Template Architecture</span>
                    <span className="text-[9px] font-bold text-gray-400 uppercase tracking-tight">Reusable for any future exam generator</span>
                  </div>
                </label>

                <label className="flex items-center gap-4 cursor-pointer group">
                  <div className="relative flex items-center justify-center">
                    <input 
                      type="radio" 
                      name="blueprint_type"
                      value="exam"
                      checked={formData.blueprint_type === 'exam'}
                      onChange={handleInputChange}
                      className="w-6 h-6 appearance-none rounded-full border-2 border-slate-200 checked:border-purple-600 transition-all group-hover:border-purple-300"
                    />
                    {formData.blueprint_type === 'exam' && <div className="absolute w-3 h-3 bg-purple-600 rounded-full animate-in zoom-in"></div>}
                  </div>
                  <div className="flex flex-col">
                    <span className={`text-[11px] font-black uppercase tracking-widest transition-colors ${formData.blueprint_type === 'exam' ? 'text-gray-900' : 'text-gray-400'}`}>One-time Exam Blueprint</span>
                    <span className="text-[9px] font-bold text-gray-400 uppercase tracking-tight">Locked for specific exam iteration</span>
                  </div>
                </label>
             </div>
          </div>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-6 pt-6 sticky bottom-6 z-20">
          <button 
            type="button" 
            onClick={handlePreview}
            disabled={previewing || !formData.text_pattern}
            className="w-full sm:w-auto px-10 py-5 bg-white/80 backdrop-blur-md border border-gray-200 text-gray-600 rounded-[24px] font-black text-xs uppercase tracking-widest hover:bg-white transition-all shadow-xl flex items-center justify-center gap-3 active:scale-95 disabled:opacity-50 hover:-translate-y-1"
          >
            {previewing ? <RefreshCw className="animate-spin" size={18} /> : <Eye size={18} />}
            Analyze Logic
          </button>
          
          <button 
            type="submit" 
            disabled={loading}
            className="w-full sm:w-auto px-12 py-5 bg-gradient-to-r from-purple-600 to-indigo-600 text-white rounded-[24px] font-black text-xs uppercase tracking-[0.2em] shadow-2xl shadow-purple-500/30 hover:shadow-indigo-500/40 hover:-translate-y-1 hover:scale-105 transition-all flex items-center justify-center gap-3 active:scale-95"
          >
            {loading ? <RefreshCw className="animate-spin" size={20} /> : <Wand2 size={20} />}
            Generate Intelligence
          </button>
        </div>
      </form>
      
      <div className="mt-20 bg-gradient-to-br from-purple-50/50 to-indigo-50/50 border border-purple-100/50 rounded-[48px] p-10 flex flex-col md:flex-row items-center gap-10">
          <div className="w-20 h-20 bg-white rounded-[28px] shadow-xl shadow-purple-500/10 flex items-center justify-center shrink-0 animate-bounce-slow">
            <Lightbulb size={40} className="text-purple-600" />
          </div>
          <div>
            <h4 className="text-lg font-black text-purple-900 uppercase tracking-tight mb-3 italic">Pattern Mastery Tip</h4>
            <p className="text-sm font-bold text-purple-700/80 leading-relaxed uppercase tracking-tight">
              Mention marks and question types explicitly. For example: <span className="text-purple-900">"Section A: 10 MCQ (1 mark each)"</span>. The more contextual data you provide, the faster our AI builds the perfect paper structure.
            </p>
          </div>
      </div>
    </div>
  );
}
