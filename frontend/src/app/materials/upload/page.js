'use client';

import { useState } from 'react';
import Link from 'next/link';
import { 
  Upload, X, FileText, CheckCircle, 
  ArrowLeft, Sparkles, BookOpen, Layers, Info,
  Plus, Trash2, FilePlus, Settings, Save, Undo,
  FileUp, FolderPlus, HelpCircle
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

export default function UploadMaterialPage() {
  const [formData, setFormData] = useState({
    class_name: '',
    subject: '',
    type: '',
    isBulk: false,
    chapterCount: 1,
    chapters: [{ unit: '', title: '', file: null }]
  });
  const [bulkFiles, setBulkFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  const classes = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'];
  const subjects = ['English', 'Mathematics', 'Science', 'Physics', 'Chemistry', 'Biology', 'History', 'Geography'];

  const handleFieldChange = (field, value) => {
    setFormData(prev => {
      const newData = { ...prev, [field]: value };
      
      // Handle chapter count changes
      if (field === 'chapterCount') {
        const count = parseInt(value) || 0;
        const currentChapters = [...prev.chapters];
        if (count > currentChapters.length) {
          for (let i = currentChapters.length; i < count; i++) {
            currentChapters.push({ unit: '', title: '', file: null });
          }
        } else {
          currentChapters.splice(count);
        }
        newData.chapters = currentChapters;
      }
      
      return newData;
    });
  };

  const handleChapterChange = (index, field, value) => {
    const newChapters = [...formData.chapters];
    newChapters[index][field] = value;
    setFormData({ ...formData, chapters: newChapters });
  };

  const handleBulkFilesChange = (e) => {
    setBulkFiles(Array.from(e.target.files));
  };

  const resetForm = () => {
    setFormData({
      class_name: '',
      subject: '',
      type: '',
      isBulk: false,
      chapterCount: 1,
      chapters: [{ unit: '', title: '', file: null }]
    });
    setBulkFiles([]);
    setError(null);
    setSuccess(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);
    setUploadProgress(10);

    try {
      const data = new FormData();
      data.append('class_name', formData.class_name);
      data.append('subject', formData.subject);
      data.append('type', formData.type);
      data.append('bulk_upload', formData.isBulk);

      if (formData.isBulk) {
        if (bulkFiles.length === 0) throw new Error('Please select at least one file for bulk upload');
        bulkFiles.forEach(file => {
          data.append('bulk_files', file);
        });
      } else {
        data.append('chapter_count', formData.chapterCount);
        formData.chapters.forEach((ch, i) => {
          if (!ch.file) throw new Error(`Please select a file for Chapter ${i+1}`);
          data.append(`unit_${i}`, ch.unit);
          data.append(`title_${i}`, ch.title);
          data.append(`file_${i}`, ch.file);
        });
      }

      setUploadProgress(40);
      await apiClient.post('/materials/', data, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      setUploadProgress(100);
      setSuccess('Materials uploaded successfully and processing started!');
      
      // Reset form after delay
      setTimeout(() => {
        resetForm();
        setUploadProgress(0);
      }, 2000);

    } catch (err) {
      setError(err.message || 'Failed to upload materials');
      setUploadProgress(0);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-8 mb-12">
        <div className="flex items-center gap-6">
          <Link href="/materials" className="w-14 h-14 bg-white border border-gray-100 rounded-2xl flex items-center justify-center text-gray-400 hover:text-blue-600 hover:border-blue-100 hover:shadow-xl hover:shadow-blue-500/5 transition-all group">
            <ArrowLeft className="group-hover:-translate-x-1 transition-transform" size={24} />
          </Link>
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Asset Management</span>
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
            </div>
            <h1 className="text-4xl font-black text-gray-900 leading-tight">Upload Material</h1>
            <p className="text-gray-500 font-medium text-lg mt-1 tracking-tight">Populate your knowledge base with fresh curriculum content.</p>
          </div>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit}>
        {/* Main Info Card */}
        <div className="glass-card mb-8 overflow-visible relative z-30">
          <div className="p-6 border-b border-gray-100 bg-white/50 flex items-center gap-3 rounded-t-[32px]">
             <div className="w-10 h-10 bg-blue-600 text-white rounded-xl flex items-center justify-center shadow-lg shadow-blue-200">
               <BookOpen size={20} />
             </div>
             <h2 className="text-xl font-black text-gray-900">Material Information</h2>
          </div>
          
          <div className="p-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
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
                <label className="flex items-center gap-2 text-xs font-black text-gray-700 uppercase tracking-widest ml-1">
                  <FileText size={14} className="text-blue-500" /> Subject
                </label>
                <input
                  type="text"
                  required
                  value={formData.subject}
                  onChange={(e) => handleFieldChange('subject', e.target.value)}
                  placeholder="e.g. Biology, English Core"
                  className="w-full px-5 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] bg-white outline-none transition-all font-bold text-gray-800"
                />
                <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider ml-1">Enter the subject name</p>
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

            {/* Bulk Toggle */}
            <div className="p-6 bg-blue-50/30 border border-blue-100 rounded-[30px] flex items-center justify-between group transition-all hover:bg-blue-50">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center text-blue-600 shadow-sm transition-transform group-hover:scale-110">
                  <FolderPlus size={24} />
                </div>
                <div>
                  <h4 className="font-black text-gray-900 uppercase tracking-tight">Bulk Upload Mode</h4>
                  <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mt-0.5">FILENAMES (WITHOUT .PDF) WILL BE USED AS TITLES AND CHAPTER NAMES.</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input 
                  type="checkbox" 
                  checked={formData.isBulk}
                  onChange={(e) => handleFieldChange('isBulk', e.target.checked)}
                  className="sr-only peer" 
                />
                <div className="w-14 h-8 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[4px] after:left-[4px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-6 after:w-6 after:transition-all peer-checked:bg-[#1e293b]"></div>
              </label>
            </div>
          </div>
        </div>

        {/* Dynamic Section */}
        {formData.isBulk ? (
          <div className="glass-card p-8 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500 relative z-10">
            <div className="text-center py-10 border-2 border-dashed border-gray-200 rounded-[40px] bg-gray-50/30">
              <input
                type="file"
                multiple
                accept=".pdf"
                onChange={handleBulkFilesChange}
                className="hidden"
                id="bulk-file-input"
              />
              <label htmlFor="bulk-file-input" className="cursor-pointer">
                <div className="w-20 h-20 bg-white rounded-[30px] shadow-sm flex items-center justify-center mx-auto mb-6 text-blue-600 ring-8 ring-blue-50/50">
                  <FileUp size={40} />
                </div>
                <h3 className="text-xl font-black text-gray-900 mb-2">Select Multiple PDF Files</h3>
                <p className="text-sm text-gray-400 font-medium mb-8 max-w-xs mx-auto">Filenames will be automatically assigned as titles. Support for up to 50 files.</p>
                <span className="inline-flex items-center gap-2 bg-blue-600 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-blue-700 active:scale-95 shadow-xl shadow-blue-200">
                  Browse Files
                </span>
              </label>

              {bulkFiles.length > 0 && (
                <div className="mt-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 px-6">
                  {bulkFiles.map((file, idx) => (
                    <div key={idx} className="flex items-center gap-3 p-4 bg-white border border-gray-100 rounded-2xl shadow-sm text-left">
                      <div className="w-10 h-10 bg-emerald-50 text-emerald-600 rounded-xl flex items-center justify-center shrink-0">
                        <CheckCircle size={18} />
                      </div>
                      <div className="truncate">
                        <p className="text-xs font-black text-gray-900 truncate leading-tight uppercase tracking-tight">{file.name}</p>
                        <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest mt-1">{(file.size / (1024*1024)).toFixed(2)} MB</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-8 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500 relative z-10">
             <div className="glass-card p-8 overflow-visible">
               <div className="flex items-center justify-between mb-8">
                  <div>
                    <h3 className="text-xl font-black text-gray-900 uppercase tracking-tight">Step-by-Step Chapters</h3>
                    <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest mt-0.5">Upload specific lesson units manually</p>
                  </div>
                  <div className="flex items-center gap-4">
                    <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Count:</label>
                    <input
                      type="number"
                      min="1"
                      max="20"
                      value={formData.chapterCount}
                      onChange={(e) => handleFieldChange('chapterCount', e.target.value)}
                      className="w-20 px-4 py-2 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none font-bold text-center"
                    />
                  </div>
               </div>

               <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                 {formData.chapters.map((chapter, idx) => (
                   <div key={idx} className="p-6 bg-white border border-gray-100 rounded-[30px] hover:border-blue-200 transition-all shadow-sm">
                     <div className="flex items-center gap-3 mb-6">
                        <span className="w-8 h-8 bg-blue-50 text-blue-600 rounded-lg flex items-center justify-center font-black text-xs">
                          {idx + 1}
                        </span>
                        <h4 className="font-black text-gray-900 uppercase text-sm tracking-widest">Chapter Details</h4>
                     </div>
                     
                     <div className="space-y-4">
                        <input
                          required
                          type="text"
                          placeholder="Unit / Chapter Name (e.g. Atoms)"
                          value={chapter.unit}
                          onChange={(e) => handleChapterChange(idx, 'unit', e.target.value)}
                          className="w-full px-4 py-3 bg-gray-50/50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-bold"
                        />
                        <input
                          required
                          type="text"
                          placeholder="Display Title (e.g. Ch-1 Atoms)"
                          value={chapter.title}
                          onChange={(e) => handleChapterChange(idx, 'title', e.target.value)}
                          className="w-full px-4 py-3 bg-gray-50/50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-bold"
                        />
                        <div className="relative">
                          <input
                            required
                            type="file"
                            accept=".pdf"
                            onChange={(e) => handleChapterChange(idx, 'file', e.target.files[0])}
                            className="hidden"
                            id={`file-input-${idx}`}
                          />
                          <label 
                            htmlFor={`file-input-${idx}`}
                            className={`flex items-center justify-center gap-3 w-full px-4 py-4 rounded-xl border-2 border-dashed transition-all cursor-pointer ${
                              chapter.file ? 'bg-emerald-50 border-emerald-200 text-emerald-600' : 'bg-gray-50 border-gray-200 text-gray-400 hover:border-blue-300 hover:text-blue-500'
                            }`}
                          >
                            {chapter.file ? (
                              <>
                                <CheckCircle size={18} />
                                <span className="text-xs font-black uppercase truncate max-w-[150px]">{chapter.file.name}</span>
                              </>
                            ) : (
                              <>
                                <Upload size={18} />
                                <span className="text-xs font-black uppercase">Upload PDF</span>
                              </>
                            )}
                          </label>
                        </div>
                     </div>
                   </div>
                 ))}
               </div>
             </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 p-8 glass-card">
           <div className="flex items-center gap-4 text-gray-400">
             <HelpCircle size={18} />
             <p className="text-[10px] font-black uppercase tracking-widest">All uploads are encrypted and processed by Al for concept extraction.</p>
           </div>
           
           <div className="flex items-center gap-4 w-full md:w-auto">
             <button
                type="button"
                onClick={resetForm}
                className="flex-1 md:flex-none flex items-center justify-center gap-2 px-8 py-4 bg-white border border-gray-200 text-gray-500 rounded-2xl font-black text-xs uppercase tracking-wider hover:bg-gray-50 transition-all active:scale-95"
             >
                <Undo size={18} /> Reset
             </button>
             <button
                disabled={loading}
                type="submit"
                className="flex-1 md:flex-none flex items-center justify-center gap-3 px-10 py-4 bg-blue-600 text-white rounded-2xl font-black text-xs uppercase tracking-wider shadow-xl shadow-blue-200 hover:bg-blue-700 transition-all hover:-translate-y-1 active:translate-y-0 disabled:opacity-50 disabled:translate-y-0"
             >
                {loading ? (
                  <>
                    <RefreshCw size={18} className="animate-spin" /> Processing...
                  </>
                ) : (
                  <>
                    <Upload size={18} /> Upload Materials
                  </>
                )}
             </button>
           </div>
        </div>
      </form>
    </div>
  );
}
