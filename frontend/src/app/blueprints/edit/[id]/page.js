'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { 
  Plus, Trash2, ArrowLeft, Save, 
  BookOpen, GraduationCap, Layers,
  CheckCircle, Settings, HelpCircle, FileText, RefreshCw
} from 'lucide-react';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function EditExamBlueprintPage() {
  const router = useRouter();
  const { id } = useParams();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  
  const [formData, setFormData] = useState({
    class_name: '',
    subject: '',
    code: '',
    sections: []
  });

  useEffect(() => {
    if (id) {
      fetchBlueprint();
    }
  }, [id]);

  const fetchBlueprint = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/blueprints/${id}/`);
      const data = res.data;
      
      let sections = [];
      if (data.blueprint && Array.isArray(data.blueprint.sections)) {
        sections = data.blueprint.sections;
      }

      setFormData({
        class_name: data.class_name || '',
        subject: data.subject || '',
        code: data.code || '',
        sections: sections
      });
    } catch (err) {
      setError('Failed to load blueprint data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSectionChange = (index, field, value) => {
    setFormData(prev => {
      const newSections = [...prev.sections];
      newSections[index] = { 
        ...newSections[index], 
        [field]: (field === 'marks' || field === 'questions_count') ? parseInt(value) || 0 : value 
      };
      return { ...prev, sections: newSections };
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    try {
      const payload = {
        class_name: formData.class_name,
        subject: formData.subject,
        code: formData.code,
        blueprint: {
          sections: formData.sections
        }
      };

      await apiClient.put(`/blueprints/${id}/`, payload);
      setSuccess('Blueprint updated successfully!');
      setTimeout(() => router.push('/blueprints'), 1500);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Failed to update blueprint');
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
    <div className="w-full relative py-2 mb-20 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white shadow-sm border border-gray-100 rounded-xl flex items-center justify-center">
            <FileText className="text-emerald-600" size={20} />
          </div>
          <h1 className="text-2xl font-black text-gray-900 tracking-tight uppercase">Edit Blueprint</h1>
        </div>
        <Link href="/blueprints" className="text-xs font-bold text-gray-400 hover:text-gray-900 transition-colors flex items-center gap-2 uppercase tracking-widest">
          <ArrowLeft size={14} />
          Back to Blueprints
        </Link>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="space-y-8">
        <div className="glass-card p-8">
          <h2 className="text-xl font-black text-gray-900 mb-6 uppercase tracking-tight">Exam Info</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Class</label>
              <input 
                type="text" name="class_name" value={formData.class_name} onChange={handleInputChange}
                className="w-full px-5 py-4 bg-gray-50 border-2 border-transparent rounded-2xl font-black text-gray-900 focus:bg-white focus:border-emerald-500 outline-none transition-all"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Subject</label>
              <input 
                type="text" name="subject" value={formData.subject} onChange={handleInputChange}
                className="w-full px-5 py-4 bg-gray-50 border-2 border-transparent rounded-2xl font-black text-gray-900 focus:bg-white focus:border-emerald-500 outline-none transition-all"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Code</label>
              <input 
                type="text" name="code" value={formData.code} onChange={handleInputChange}
                className="w-full px-5 py-4 bg-gray-50 border-2 border-transparent rounded-2xl font-black text-gray-900 focus:bg-white focus:border-emerald-500 outline-none transition-all"
              />
            </div>
          </div>
        </div>

        <div className="glass-card p-8">
          <h2 className="text-xl font-black text-gray-900 uppercase tracking-tight mb-8">Section Distribution</h2>
          <div className="space-y-4">
            {formData.sections.map((section, idx) => (
              <div key={idx} className="grid grid-cols-1 md:grid-cols-3 gap-6 p-6 bg-gray-50/50 rounded-3xl border border-gray-100">
                <div className="space-y-2">
                  <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Section {section.id || idx+1}</label>
                  <input 
                    value={section.name} readOnly
                    className="w-full px-4 py-3 bg-white/50 border border-gray-100 rounded-xl font-bold text-gray-400 cursor-not-allowed"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Questions Count</label>
                  <input 
                    type="number" value={section.questions_count} onChange={(e) => handleSectionChange(idx, 'questions_count', e.target.value)}
                    className="w-full px-4 py-3 bg-white border border-gray-200 rounded-xl font-bold text-gray-900 focus:border-emerald-500 outline-none"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Total Marks</label>
                  <input 
                    type="number" value={section.marks} onChange={(e) => handleSectionChange(idx, 'marks', e.target.value)}
                    className="w-full px-4 py-3 bg-white border border-gray-200 rounded-xl font-bold text-gray-900 focus:border-emerald-500 outline-none"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-4">
          <button 
            type="button" onClick={() => router.push('/blueprints')}
            className="px-8 py-4 text-xs font-black text-gray-400 uppercase tracking-widest hover:text-gray-900"
          >
            Cancel
          </button>
          <button 
            type="submit" disabled={saving}
            className="bg-emerald-600 text-white px-10 py-4 rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-emerald-200 hover:bg-emerald-700 transition-all flex items-center gap-3"
          >
            {saving ? <RefreshCw className="animate-spin" /> : <Save size={18} />}
            Save Changes
          </button>
        </div>
      </form>
    </div>
  );
}
