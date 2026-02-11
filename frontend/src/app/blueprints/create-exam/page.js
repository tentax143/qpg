'use client';

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { 
  Plus, ArrowLeft, Save, 
  BookOpen, GraduationCap, Layers,
  CheckCircle, Settings, HelpCircle, Layout,
  Info, Lightbulb, FileText, ClipboardList, Code, Hash
} from 'lucide-react';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

function CreateExamContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const templateId = searchParams.get('template');

  const [loading, setLoading] = useState(false);
  const [fetchingTemplates, setFetchingTemplates] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  const [templates, setTemplates] = useState([]);
  const [formData, setFormData] = useState({
    class_name: '',
    subject: '',
    section: '',
    code: '',
    template: templateId || ''
  });

  useEffect(() => {
    fetchTemplates();
  }, []);

  useEffect(() => {
    if (templateId) {
      setFormData(prev => ({ ...prev, template: templateId }));
    }
  }, [templateId]);

  const fetchTemplates = async () => {
    try {
      const res = await apiClient.get('/templates/?page_size=100');
      setTemplates(res.data.results || []);
    } catch (err) {
      console.error("Failed to fetch templates", err);
      setError("Failed to load blueprint templates. Please try again.");
    } finally {
      setFetchingTemplates(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    if (!formData.template) {
      setError("Please select a blueprint template.");
      setLoading(false);
      return;
    }

    try {
      const payload = {
        class_name: formData.class_name,
        subject: formData.subject,
        section: formData.section || null,
        code: formData.code || null,
        template: formData.template
      };

      await apiClient.post('/blueprints/', payload);
      setSuccess('Blueprint created successfully!');
      setTimeout(() => router.push('/blueprints'), 1500);
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.detail || err.message || 'Failed to create blueprint');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full relative py-6 mb-20 px-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between mb-12 gap-6">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-white/80 backdrop-blur-md shadow-2xl shadow-blue-500/10 border border-white/50 rounded-2xl flex items-center justify-center">
            <ClipboardList size={28} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight">Create Blueprint</h1>
            <p className="text-gray-500 font-medium tracking-tight">Generate a specific blueprint from a template</p>
          </div>
        </div>
        <Link href="/blueprints" className="flex items-center gap-2 bg-white/80 backdrop-blur-sm text-gray-600 px-6 py-3 rounded-2xl font-bold text-sm border border-gray-100 shadow-sm hover:shadow-md hover:bg-white transition-all active:scale-95">
          <ArrowLeft size={18} />
          Back to list
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="space-y-12">
        <div className="bg-white/80 backdrop-blur-xl rounded-[40px] shadow-2xl shadow-blue-500/5 border border-white/20 p-10">
          <div className="flex items-center gap-3 mb-10 pb-6 border-b border-gray-100">
            <div className="w-2 h-8 bg-blue-600 rounded-full"></div>
            <h2 className="text-xl font-black text-gray-900 tracking-tight">Blueprint Details</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            {/* Class */}
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-widest ml-1">
                <GraduationCap size={14} /> Class
              </label>
              <input 
                type="text" name="class_name" value={formData.class_name} onChange={handleInputChange}
                className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/5 transition-all outline-none"
                placeholder="e.g. 10 or 12" required
              />
              <p className="text-[10px] text-gray-400 font-medium ml-1">The class level for this blueprint</p>
            </div>

            {/* Subject */}
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-widest ml-1">
                <BookOpen size={14} /> Subject
              </label>
              <input 
                type="text" name="subject" value={formData.subject} onChange={handleInputChange}
                className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/5 transition-all outline-none"
                placeholder="e.g. Mathematics" required
              />
              <p className="text-[10px] text-gray-400 font-medium ml-1">The subject name</p>
            </div>

            {/* Section */}
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-widest ml-1">
                <Layers size={14} /> Section
              </label>
              <input 
                type="text" name="section" value={formData.section} onChange={handleInputChange}
                className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/5 transition-all outline-none"
                placeholder="e.g. A (Optional)"
              />
              <p className="text-[10px] text-gray-400 font-medium ml-1">Optional section identifier</p>
            </div>

            {/* Code */}
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-xs font-bold text-gray-400 uppercase tracking-widest ml-1">
                <Hash size={14} /> Subject Code
              </label>
              <input 
                type="text" name="code" value={formData.code} onChange={handleInputChange}
                className="w-full px-6 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl font-bold text-gray-900 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/5 transition-all outline-none"
                placeholder="e.g. MAT-101 (Optional)"
              />
              <p className="text-[10px] text-gray-400 font-medium ml-1">Official subject code if any</p>
            </div>
          </div>

          <div className="mt-12">
            <CustomSelect
              label="Blueprint Template"
              icon={Layout}
              value={formData.template}
              onChange={(val) => setFormData(prev => ({ ...prev, template: val }))}
              options={templates.map(t => ({ 
                label: `${t.name} (Class ${t.class_name} - ${t.subject})`, 
                value: t.id 
              }))}
              placeholder={fetchingTemplates ? 'Loading templates...' : 'Select a template...'}
              required
            />
            <p className="text-[10px] text-gray-400 font-medium ml-1 mt-2">The layout template defining the sections and marks</p>
          </div>

          <div className="mt-12 flex justify-end pt-8 border-t border-gray-100">
            <button 
              type="submit" disabled={loading}
              className="px-12 py-5 bg-blue-600 text-white rounded-2xl font-black text-sm uppercase tracking-widest shadow-2xl shadow-blue-500/20 hover:bg-blue-700 transition-all flex items-center gap-3 disabled:opacity-50 hover:-translate-y-1 active:scale-95"
            >
              {loading ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              ) : (
                <>
                  <Plus size={20} />
                  <span>Create Blueprint</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Info Card */}
        <div className="bg-gradient-to-br from-gray-900 to-blue-900 rounded-[40px] p-10 text-white shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl -mr-20 -mt-20"></div>
          <div className="flex items-center gap-4 mb-8">
            <div className="w-12 h-12 bg-white/10 backdrop-blur-md rounded-2xl flex items-center justify-center border border-white/10">
              <Lightbulb className="text-amber-400" size={24} />
            </div>
            <h2 className="text-xl font-black tracking-tight">Understanding Blueprints</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            <p className="text-blue-100 font-medium leading-relaxed">
              Blueprints are the bridge between a generic template and your actual exam. They contain specific details like subject codes and class identifiers while inheriting the structure from a template.
            </p>
            <div className="space-y-4">
              {[
                "Templates define sections & marks",
                "Blueprints link templates to classes",
                "Generator uses blueprints to create papers",
                "Customize distribution after creation"
              ].map((text, i) => (
                <div key={i} className="flex items-center gap-3 text-sm font-bold text-white/80">
                  <div className="w-2 h-2 rounded-full bg-blue-400"></div>
                  {text}
                </div>
              ))}
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}

export default function CreateExamBlueprintPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin w-8 h-8 border-4 border-[#1e293b] border-t-transparent rounded-full" />
      </div>
    }>
      <CreateExamContent />
    </Suspense>
  );
}
