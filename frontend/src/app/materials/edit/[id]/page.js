'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { 
  ArrowLeft, BookOpen, Layers, FileText, 
  Settings, Save, CheckCircle, RefreshCw,
  FilePlus, Trash2, Info, AlertCircle
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

export default function EditMaterialPage() {
  const router = useRouter();
  const { id } = useParams();
  const [formData, setFormData] = useState({
    class_name: '',
    subject: '',
    unit: '',
    title: '',
    type: 'textbook',
  });
  const [currentFile, setCurrentFile] = useState(null);
  const [newFile, setNewFile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    fetchMaterial();
  }, [id]);

  const fetchMaterial = async () => {
    try {
      setLoading(true);
      const res = await apiClient.get(`/materials/${id}/`);
      const data = res.data;
      setFormData({
        class_name: data.class_name,
        subject: data.subject,
        unit: data.unit || '',
        title: data.title,
        type: data.type,
      });
      setCurrentFile(data.file);
    } catch (err) {
      setError('Failed to load material details');
    } finally {
      setLoading(false);
    }
  };

  const handleFieldChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const data = new FormData();
      data.append('class_name', formData.class_name);
      data.append('subject', formData.subject);
      data.append('unit', formData.unit);
      data.append('title', formData.title);
      data.append('type', formData.type);
      
      if (newFile) {
        data.append('file', newFile);
      }

      await apiClient.patch(`/materials/${id}/`, data);
      setSuccess('Material updated successfully!');
      
      setTimeout(() => {
        router.push('/materials');
      }, 1500);
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to update material');
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
    <div className="w-full relative py-2 mb-20">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-8 mb-12">
        <div className="flex items-center gap-6">
          <Link href="/materials" className="w-12 h-12 bg-white border border-gray-100 rounded-xl flex items-center justify-center text-gray-400 hover:text-blue-600 transition-all group shadow-sm">
            <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform" />
          </Link>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Editor</span>
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></span>
            </div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight">Edit Material</h1>
          </div>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit} className="max-w-4xl text-gray-900">
        <div className="bg-white/80 backdrop-blur-xl rounded-[32px] shadow-2xl shadow-blue-500/5 border border-white/20 overflow-visible relative z-30">
          <div className="p-8 border-b border-gray-50 flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-600 text-white rounded-2xl flex items-center justify-center shadow-lg shadow-blue-200">
              <BookOpen size={24} />
            </div>
            <div>
              <h2 className="text-xl font-black text-gray-900 uppercase tracking-tight">Material Details</h2>
              <p className="text-[10px] text-gray-400 font-black uppercase tracking-widest mt-0.5">Update chapter information and content</p>
            </div>
          </div>

          <div className="p-8 space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <CustomSelect
                label="Class"
                icon={Layers}
                value={formData.class_name}
                onChange={(val) => handleFieldChange('class_name', val)}
                options={['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'].map(c => ({ label: `Class ${c}`, value: c }))}
                placeholder="Select Class"
                className="space-y-2"
              />

              <div className="space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-black text-gray-700 uppercase tracking-widest ml-1">
                  <FileText size={14} className="text-[#1e293b]" /> Subject
                </label>
                <input
                  required
                  type="text"
                  value={formData.subject}
                  onChange={(e) => handleFieldChange('subject', e.target.value)}
                  className="w-full px-5 py-4 bg-gray-50 border border-gray-100 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all font-bold text-gray-700"
                />
              </div>

              <div className="space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-black text-gray-700 uppercase tracking-widest ml-1">
                  <Info size={14} className="text-[#1e293b]" /> Lesson / Chapter Name
                </label>
                <input
                  required
                  type="text"
                  value={formData.unit}
                  onChange={(e) => handleFieldChange('unit', e.target.value)}
                  placeholder="e.g. Unit 1: Introduction"
                  className="w-full px-5 py-4 bg-gray-50 border border-gray-100 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all font-bold text-gray-700"
                />
              </div>

              <div className="space-y-2">
                <label className="flex items-center gap-2 text-[10px] font-black text-gray-700 uppercase tracking-widest ml-1">
                  <FileText size={14} className="text-[#1e293b]" /> Title
                </label>
                <input
                  required
                  type="text"
                  value={formData.title}
                  onChange={(e) => handleFieldChange('title', e.target.value)}
                  placeholder="e.g. The Living World"
                  className="w-full px-5 py-4 bg-gray-50 border border-gray-100 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all font-bold text-gray-700"
                />
              </div>

              <CustomSelect
                label="Material Type"
                icon={Settings}
                value={formData.type}
                onChange={(val) => handleFieldChange('type', val)}
                options={[
                  { label: 'Textbook', value: 'textbook' },
                  { label: 'Notes', value: 'notes' },
                  { label: 'Question Bank', value: 'bank' },
                  { label: 'Syllabus', value: 'syllabus' },
                  { label: 'Reference Book', value: 'reference' }
                ]}
                placeholder="Select type"
                className="space-y-2"
              />
            </div>

            <div className="space-y-4">
              <label className="flex items-center gap-2 text-[10px] font-black text-gray-700 uppercase tracking-widest ml-1">
                <FilePlus size={14} className="text-blue-500" /> Source Document
              </label>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {currentFile && !newFile && (
                  <div className="p-4 bg-emerald-50 border border-emerald-100 rounded-2xl flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-white rounded-xl flex items-center justify-center text-emerald-600 shadow-sm">
                        <CheckCircle size={20} />
                      </div>
                      <div>
                        <p className="text-xs font-black text-emerald-900 uppercase tracking-tight">Current File Attached</p>
                        <a href={currentFile} target="_blank" className="text-[10px] text-emerald-600 font-bold uppercase hover:underline">View Document</a>
                      </div>
                    </div>
                  </div>
                )}

                <div className="relative group/upload">
                  <input
                    type="file"
                    accept=".pdf"
                    onChange={(e) => setNewFile(e.target.files[0])}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                    id="file-upload"
                  />
                  <div className={`p-4 border-2 border-dashed rounded-2xl transition-all flex items-center gap-3 ${newFile ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-200 group-hover/upload:border-blue-400'}`}>
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center shadow-sm ${newFile ? 'bg-blue-600 text-white' : 'bg-white text-gray-400 group-hover/upload:text-blue-600 transition-colors'}`}>
                      <RefreshCw size={20} className={saving ? 'animate-spin' : ''} />
                    </div>
                    <div>
                      <p className="text-xs font-black text-gray-900 uppercase tracking-tight">{newFile ? newFile.name : 'Replace Document'}</p>
                      <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest">{newFile ? `${(newFile.size / 1024 / 1024).toFixed(2)} MB` : 'Optional (.pdf only)'}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-8 border-t border-gray-50 flex items-center justify-end gap-3">
              <Link href="/materials" className="px-6 py-3 rounded-xl font-black text-xs text-gray-400 uppercase tracking-wider hover:text-gray-900 transition-colors">
                Cancel
              </Link>
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 bg-blue-600 text-white px-8 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-blue-200 hover:bg-blue-700 transition-all active:scale-95 disabled:opacity-70 disabled:active:scale-100"
              >
                {saving ? (
                   <>
                     <RefreshCw size={16} className="animate-spin" />
                     Saving Changes...
                   </>
                ) : (
                  <>
                    <Save size={16} />
                    Save Material
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
