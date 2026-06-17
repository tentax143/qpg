'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  Upload, FileText, CheckCircle,
  ArrowLeft, BookOpen, Layers,
  Plus, Trash2, Settings,
  FileUp, FolderPlus, HelpCircle, RefreshCw, AlertCircle,
  Cpu, Cloud, Undo, LayoutGrid
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';
import { subjectOptions } from '@/lib/subjects';

const CLASS_OPTIONS = ['1','2','3','4','5','6','7','8','9','10','11','12'].map(c => ({ label: `Class ${c}`, value: c }));
const TYPE_OPTIONS = [
  { label: 'Textbook', value: 'textbook' },
  { label: 'Notes', value: 'notes' },
  { label: 'Question Bank', value: 'bank' },
  { label: 'Syllabus', value: 'syllabus' },
  { label: 'Reference Book', value: 'reference' },
];

function FileProgressRow({ name, size, fp }) {
  const status = fp?.status ?? 'pending';
  const pct    = fp?.pct ?? 0;
  const color  = { pending: 'text-gray-400', uploading: 'text-blue-500', done: 'text-emerald-500', error: 'text-red-500' }[status];
  const bar    = { pending: 'bg-gray-200',   uploading: 'bg-blue-500',   done: 'bg-emerald-500',   error: 'bg-red-500'   }[status];
  const Icon   = status === 'done' ? CheckCircle : status === 'error' ? AlertCircle : status === 'uploading' ? RefreshCw : FileText;
  return (
    <div className="flex items-center gap-4 p-4 bg-white border border-gray-100 rounded-2xl shadow-sm text-left">
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${status === 'done' ? 'bg-emerald-50' : status === 'error' ? 'bg-red-50' : 'bg-gray-50'}`}>
        <Icon size={16} className={`${color} ${status === 'uploading' ? 'animate-spin' : ''}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-xs font-black text-gray-900 truncate uppercase tracking-tight">{name}</p>
          <span className={`text-[10px] font-black uppercase tracking-wider shrink-0 ml-3 ${color}`}>
            {status === 'pending' ? `${(size/(1024*1024)).toFixed(1)} MB` : status === 'uploading' ? `${pct}%` : status === 'done' ? 'Done' : 'Failed'}
          </span>
        </div>
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-300 ${bar}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    </div>
  );
}

// ── Multi-subject group card ──────────────────────────────────────────────────
function SubjectGroupCard({ group, index, onChange, onRemove, fileProgress }) {
  const inputId = `ms-files-${index}`;
  return (
    <div className="bg-white border border-gray-100 rounded-[28px] p-6 shadow-sm">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <span className="w-8 h-8 bg-blue-50 text-blue-600 rounded-lg flex items-center justify-center font-black text-xs">{index + 1}</span>
          <span className="font-black text-gray-900 uppercase text-sm tracking-widest">Subject Group</span>
        </div>
        <button type="button" onClick={onRemove} className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all">
          <Trash2 size={14} />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        <CustomSelect label="Class" icon={Layers} value={group.class_name}
          onChange={v => onChange('class_name', v)} options={CLASS_OPTIONS} placeholder="Class" />
        <CustomSelect label="Subject" icon={BookOpen} value={group.subject}
          onChange={v => onChange('subject', v)} options={subjectOptions} placeholder="Subject" />
        <CustomSelect label="Type" icon={Settings} value={group.type}
          onChange={v => onChange('type', v)} options={TYPE_OPTIONS} placeholder="Type" />
      </div>

      <div className="border-2 border-dashed border-gray-200 rounded-2xl p-4 bg-gray-50/30">
        <input type="file" multiple accept=".pdf" id={inputId} className="hidden"
          onChange={e => onChange('files', Array.from(e.target.files))} />
        {group.files.length === 0 ? (
          <label htmlFor={inputId} className="flex flex-col items-center gap-2 cursor-pointer py-4">
            <FileUp size={28} className="text-blue-400" />
            <p className="text-xs font-black text-gray-500 uppercase tracking-wider">Drop PDFs here or click to browse</p>
          </label>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">{group.files.length} file(s) selected</span>
              <label htmlFor={inputId} className="text-[10px] font-black text-blue-500 uppercase tracking-wider cursor-pointer hover:text-blue-700">Change</label>
            </div>
            {group.files.map((f, i) => (
              <FileProgressRow key={i} name={f.name} size={f.size} fp={fileProgress[`${index}-${f.name}`]} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function UploadMaterialPage() {
  const [embeddingProvider, setEmbeddingProvider] = useState('local');
  const [isMultiSubject, setIsMultiSubject] = useState(false);
  const [formData, setFormData] = useState({
    class_name: '', subject: '', type: '', isBulk: false,
    chapterCount: 1, chapters: [{ unit: '', title: '', file: null }],
  });
  const [bulkFiles, setBulkFiles]       = useState([]);
  const [subjectGroups, setSubjectGroups] = useState([
    { class_name: '', subject: '', type: '', files: [] },
  ]);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState(null);
  const [success, setSuccess]           = useState(null);
  const [fileProgress, setFileProgress] = useState({});

  const setFilePct = (key, pct, status) =>
    setFileProgress(prev => ({ ...prev, [key]: { pct, status } }));

  const handleFieldChange = (field, value) => {
    setFormData(prev => {
      const next = { ...prev, [field]: value };
      if (field === 'chapterCount') {
        const count = parseInt(value) || 0;
        const chs = [...prev.chapters];
        if (count > chs.length) for (let i = chs.length; i < count; i++) chs.push({ unit: '', title: '', file: null });
        else chs.splice(count);
        next.chapters = chs;
      }
      return next;
    });
  };

  const handleChapterChange = (index, field, value) => {
    const chs = [...formData.chapters];
    chs[index][field] = value;
    setFormData({ ...formData, chapters: chs });
  };

  const updateGroup = (index, field, value) => {
    setSubjectGroups(prev => prev.map((g, i) => i === index ? { ...g, [field]: value } : g));
  };

  const addGroup = () => setSubjectGroups(prev => [...prev, { class_name: '', subject: '', type: '', files: [] }]);

  const removeGroup = index => setSubjectGroups(prev => prev.filter((_, i) => i !== index));

  const resetForm = () => {
    setFormData({ class_name: '', subject: '', type: '', isBulk: false, chapterCount: 1, chapters: [{ unit: '', title: '', file: null }] });
    setBulkFiles([]);
    setSubjectGroups([{ class_name: '', subject: '', type: '', files: [] }]);
    setFileProgress({});
    setError(null);
    setSuccess(null);
  };

  const uploadSingle = async (key, formPayload) => {
    setFilePct(key, 0, 'uploading');
    try {
      await apiClient.post('/materials/', formPayload, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: e => setFilePct(key, e.total ? Math.round((e.loaded * 100) / e.total) : 50, 'uploading'),
      });
      setFilePct(key, 100, 'done');
    } catch (err) {
      setFilePct(key, 100, 'error');
      throw err;
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);
    setFileProgress({});

    try {
      if (isMultiSubject) {
        // ── Multi-subject mode ──────────────────────────────────────────────
        for (let gi = 0; gi < subjectGroups.length; gi++) {
          const g = subjectGroups[gi];
          if (!g.class_name || !g.subject || !g.type) throw new Error(`Group ${gi + 1}: please fill in Class, Subject and Type`);
          if (g.files.length === 0) throw new Error(`Group ${gi + 1}: no files selected`);
          for (const file of g.files) {
            const data = new FormData();
            data.append('class_name', g.class_name);
            data.append('subject', g.subject);
            data.append('type', g.type);
            data.append('bulk_upload', 'true');
            data.append('bulk_files', file);
            data.append('embedding_provider', embeddingProvider);
            await uploadSingle(`${gi}-${file.name}`, data);
          }
        }
      } else if (formData.isBulk) {
        // ── Single-subject bulk mode ────────────────────────────────────────
        if (bulkFiles.length === 0) throw new Error('Please select at least one file');
        for (const file of bulkFiles) {
          const data = new FormData();
          data.append('class_name', formData.class_name);
          data.append('subject', formData.subject);
          data.append('type', formData.type);
          data.append('bulk_upload', 'true');
          data.append('bulk_files', file);
          data.append('embedding_provider', embeddingProvider);
          await uploadSingle(file.name, data);
        }
      } else {
        // ── Chapter-by-chapter mode ─────────────────────────────────────────
        formData.chapters.forEach((ch, i) => { if (!ch.file) throw new Error(`Please select a file for Chapter ${i + 1}`); });
        for (let i = 0; i < formData.chapters.length; i++) {
          const ch = formData.chapters[i];
          const data = new FormData();
          data.append('class_name', formData.class_name);
          data.append('subject', formData.subject);
          data.append('type', formData.type);
          data.append('bulk_upload', 'false');
          data.append('chapter_count', '1');
          data.append('unit_0', ch.unit);
          data.append('title_0', ch.title);
          data.append('file_0', ch.file);
          data.append('embedding_provider', embeddingProvider);
          await uploadSingle(ch.file.name, data);
        }
      }

      setSuccess('All files uploaded! Embedding ingestion is running in the background.');
      setTimeout(resetForm, 3000);
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Upload failed');
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

      {error   && <ErrorAlert   message={error}   onClose={() => setError(null)}   className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      <form onSubmit={handleSubmit}>
        {/* Settings card — always visible */}
        <div className="glass-card mb-8 overflow-visible relative z-30">
          <div className="p-6 border-b border-gray-100 bg-white/50 flex items-center gap-3 rounded-t-[32px]">
            <div className="w-10 h-10 bg-blue-600 text-white rounded-xl flex items-center justify-center shadow-lg shadow-blue-200">
              <Settings size={20} />
            </div>
            <h2 className="text-xl font-black text-gray-900">Upload Settings</h2>
          </div>
          <div className="p-8 space-y-4">

            {/* Multi-subject toggle */}
            <div className="p-6 bg-violet-50/40 border border-violet-100 rounded-[30px] flex items-center justify-between group transition-all hover:bg-violet-50">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center text-violet-600 shadow-sm transition-transform group-hover:scale-110">
                  <LayoutGrid size={24} />
                </div>
                <div>
                  <h4 className="font-black text-gray-900 uppercase tracking-tight">Multi-Subject Mode</h4>
                  <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mt-0.5">Upload files for multiple subjects in one session.</p>
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" checked={isMultiSubject}
                  onChange={e => setIsMultiSubject(e.target.checked)} className="sr-only peer" />
                <div className="w-14 h-8 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[4px] after:left-[4px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-6 after:w-6 after:transition-all peer-checked:bg-violet-600"></div>
              </label>
            </div>

            {/* Bulk toggle — only when not multi-subject */}
            {!isMultiSubject && (
              <div className="p-6 bg-blue-50/30 border border-blue-100 rounded-[30px] flex items-center justify-between group transition-all hover:bg-blue-50">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center text-blue-600 shadow-sm transition-transform group-hover:scale-110">
                    <FolderPlus size={24} />
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900 uppercase tracking-tight">Bulk Upload Mode</h4>
                    <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mt-0.5">Filenames (without .pdf) will be used as titles and chapter names.</p>
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" checked={formData.isBulk}
                    onChange={e => handleFieldChange('isBulk', e.target.checked)} className="sr-only peer" />
                  <div className="w-14 h-8 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[4px] after:left-[4px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-6 after:w-6 after:transition-all peer-checked:bg-[#1e293b]"></div>
                </label>
              </div>
            )}

            {/* Embedding provider */}
            <div className="p-6 bg-slate-50/50 border border-slate-100 rounded-[30px]">
              <div className="flex items-center gap-3 mb-4">
                <Cpu size={18} className="text-slate-500" />
                <h4 className="font-black text-gray-900 uppercase tracking-tight text-sm">Embedding Provider</h4>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { value: 'local',       label: 'Local (Ollama)',  sub: 'nomic-embed-text · Fast · Free', Icon: Cpu,   active: 'border-emerald-500 bg-emerald-50 text-emerald-700' },
                  { value: 'openrouter',  label: 'OpenRouter',      sub: 'llama-nemotron · 2048-dim · API', Icon: Cloud, active: 'border-blue-500 bg-blue-50 text-blue-700' },
                ].map(({ value, label, sub, Icon, active }) => (
                  <button key={value} type="button" onClick={() => setEmbeddingProvider(value)}
                    className={`flex items-center gap-3 p-4 rounded-2xl border-2 transition-all ${embeddingProvider === value ? active : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'}`}>
                    <Icon size={20} />
                    <div className="text-left">
                      <p className="font-black text-xs uppercase tracking-tight">{label}</p>
                      <p className="text-[10px] font-bold opacity-70 mt-0.5">{sub}</p>
                    </div>
                    {embeddingProvider === value && <CheckCircle size={16} className="ml-auto shrink-0" />}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ── Multi-subject groups ────────────────────────────────────────── */}
        {isMultiSubject ? (
          <div className="space-y-4 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-300">
            {subjectGroups.map((group, idx) => (
              <SubjectGroupCard
                key={idx}
                group={group}
                index={idx}
                onChange={(field, value) => updateGroup(idx, field, value)}
                onRemove={() => removeGroup(idx)}
                fileProgress={fileProgress}
              />
            ))}
            <button type="button" onClick={addGroup}
              className="w-full py-4 border-2 border-dashed border-violet-200 rounded-[28px] text-violet-500 font-black text-xs uppercase tracking-wider flex items-center justify-center gap-2 hover:border-violet-400 hover:bg-violet-50/30 transition-all">
              <Plus size={16} /> Add Subject Group
            </button>
          </div>

        ) : (
          <>
            {/* ── Single-subject info ──────────────────────────────────────── */}
            <div className="glass-card mb-8 overflow-visible relative z-20">
              <div className="p-6 border-b border-gray-100 bg-white/50 flex items-center gap-3 rounded-t-[32px]">
                <div className="w-10 h-10 bg-blue-600 text-white rounded-xl flex items-center justify-center shadow-lg shadow-blue-200">
                  <BookOpen size={20} />
                </div>
                <h2 className="text-xl font-black text-gray-900">Material Information</h2>
              </div>
              <div className="p-8">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                  <CustomSelect label="Class" icon={Layers} value={formData.class_name}
                    onChange={v => handleFieldChange('class_name', v)} options={CLASS_OPTIONS} placeholder="Select Class" />
                  <CustomSelect label="Subject" icon={BookOpen} value={formData.subject}
                    onChange={v => handleFieldChange('subject', v)} options={subjectOptions} placeholder="Select Subject" />
                  <CustomSelect label="Material Type" icon={Settings} value={formData.type}
                    onChange={v => handleFieldChange('type', v)} options={TYPE_OPTIONS} placeholder="Select type" />
                </div>
              </div>
            </div>

            {/* ── Bulk / chapter file section ──────────────────────────────── */}
            {formData.isBulk ? (
              <div className="glass-card p-8 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500 relative z-10">
                <div className="text-center py-10 border-2 border-dashed border-gray-200 rounded-[40px] bg-gray-50/30">
                  <input type="file" multiple accept=".pdf" onChange={e => setBulkFiles(Array.from(e.target.files))} className="hidden" id="bulk-file-input" />
                  <label htmlFor="bulk-file-input" className="cursor-pointer">
                    <div className="w-20 h-20 bg-white rounded-[30px] shadow-sm flex items-center justify-center mx-auto mb-6 text-blue-600 ring-8 ring-blue-50/50">
                      <FileUp size={40} />
                    </div>
                    <h3 className="text-xl font-black text-gray-900 mb-2">Select Multiple PDF Files</h3>
                    <p className="text-sm text-gray-400 font-medium mb-8 max-w-xs mx-auto">Filenames will be automatically assigned as titles. Up to 50 files.</p>
                    <span className="inline-flex items-center gap-2 bg-blue-600 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-blue-700 active:scale-95 shadow-xl shadow-blue-200">
                      Browse Files
                    </span>
                  </label>
                  {bulkFiles.length > 0 && (
                    <div className="mt-10 flex flex-col gap-3 px-6">
                      {bulkFiles.map((file, idx) => (
                        <FileProgressRow key={idx} name={file.name} size={file.size} fp={fileProgress[file.name]} />
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
                      <input type="number" min="1" max="20" value={formData.chapterCount}
                        onChange={e => handleFieldChange('chapterCount', e.target.value)}
                        className="w-20 px-4 py-2 bg-gray-50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none font-bold text-center" />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {formData.chapters.map((chapter, idx) => (
                      <div key={idx} className="p-6 bg-white border border-gray-100 rounded-[30px] hover:border-blue-200 transition-all shadow-sm">
                        <div className="flex items-center gap-3 mb-6">
                          <span className="w-8 h-8 bg-blue-50 text-blue-600 rounded-lg flex items-center justify-center font-black text-xs">{idx + 1}</span>
                          <h4 className="font-black text-gray-900 uppercase text-sm tracking-widest">Chapter Details</h4>
                        </div>
                        <div className="space-y-4">
                          <input required type="text" placeholder="Unit / Chapter Name (e.g. Atoms)"
                            value={chapter.unit} onChange={e => handleChapterChange(idx, 'unit', e.target.value)}
                            className="w-full px-4 py-3 bg-gray-50/50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-bold" />
                          <input required type="text" placeholder="Display Title (e.g. Ch-1 Atoms)"
                            value={chapter.title} onChange={e => handleChapterChange(idx, 'title', e.target.value)}
                            className="w-full px-4 py-3 bg-gray-50/50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-bold" />
                          <div className="relative">
                            <input required type="file" accept=".pdf"
                              onChange={e => handleChapterChange(idx, 'file', e.target.files[0])}
                              className="hidden" id={`file-input-${idx}`} />
                            <label htmlFor={`file-input-${idx}`}
                              className={`flex items-center justify-center gap-3 w-full px-4 py-4 rounded-xl border-2 border-dashed transition-all cursor-pointer ${chapter.file ? 'bg-emerald-50 border-emerald-200 text-emerald-600' : 'bg-gray-50 border-gray-200 text-gray-400 hover:border-blue-300 hover:text-blue-500'}`}>
                              {chapter.file
                                ? <><CheckCircle size={18} /><span className="text-xs font-black uppercase truncate max-w-[150px]">{chapter.file.name}</span></>
                                : <><Upload size={18} /><span className="text-xs font-black uppercase">Upload PDF</span></>}
                            </label>
                          </div>
                          {chapter.file && fileProgress[chapter.file.name] && (
                            <FileProgressRow name={chapter.file.name} size={chapter.file.size} fp={fileProgress[chapter.file.name]} />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* Action bar */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 p-8 glass-card">
          <div className="flex items-center gap-4 text-gray-400">
            <HelpCircle size={18} />
            <p className="text-[10px] font-black uppercase tracking-widest">All uploads are processed by AI for concept extraction.</p>
          </div>
          <div className="flex items-center gap-4 w-full md:w-auto">
            <button type="button" onClick={resetForm}
              className="flex-1 md:flex-none flex items-center justify-center gap-2 px-8 py-4 bg-white border border-gray-200 text-gray-500 rounded-2xl font-black text-xs uppercase tracking-wider hover:bg-gray-50 transition-all active:scale-95">
              <Undo size={18} /> Reset
            </button>
            <button disabled={loading} type="submit"
              className="flex-1 md:flex-none flex items-center justify-center gap-3 px-10 py-4 bg-blue-600 text-white rounded-2xl font-black text-xs uppercase tracking-wider shadow-xl shadow-blue-200 hover:bg-blue-700 transition-all hover:-translate-y-1 active:translate-y-0 disabled:opacity-50 disabled:translate-y-0">
              {loading
                ? <><RefreshCw size={18} className="animate-spin" /> Processing...</>
                : <><Upload size={18} /> Upload Materials</>}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
