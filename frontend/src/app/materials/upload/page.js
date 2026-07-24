'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Upload, FileText, CheckCircle,
  ArrowLeft, BookOpen, Layers,
  Plus, Trash2, Settings,
  FileUp, FolderPlus, HelpCircle, RefreshCw, AlertCircle,
  Cpu, Cloud, Undo, LayoutGrid, Globe, ListTree, Search, Sparkles, Database
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';
import ChapterMultiSelect from '@/components/ChapterMultiSelect';
import { subjectOptions } from '@/lib/subjects';

const CLASS_OPTIONS = ['1','2','3','4','5','6','7','8','9','10','11','12'].map(c => ({ label: `Class ${c}`, value: c }));
const TYPE_OPTIONS = [
  { label: 'Textbook', value: 'textbook' },
  { label: 'Notes', value: 'notes' },
  { label: 'Question Bank', value: 'bank' },
  { label: 'Syllabus', value: 'syllabus' },
  { label: 'Reference Book', value: 'reference' },
];

// Accessible on/off switch. Uses a real knob element (not an ::after pseudo + `peer` chain,
// which renders invisibly white-on-white under Tailwind v4). The border + knob shadow keep it
// visible on any card background. `activeClass` must be a full literal class so the JIT keeps it.
function Toggle({ checked, onChange, activeClass = 'bg-violet-600' }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-8 w-14 shrink-0 cursor-pointer items-center rounded-full border transition-colors focus:outline-none ${checked ? `${activeClass} border-transparent` : 'bg-gray-200 border-gray-300'}`}
    >
      <span className={`inline-block h-6 w-6 rounded-full bg-white shadow-md ring-1 ring-black/5 transition-transform ${checked ? 'translate-x-[26px]' : 'translate-x-[3px]'}`} />
    </button>
  );
}

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

      {group.type && group.type !== 'textbook' && (
        <div className="mb-4 p-4 bg-blue-50/30 border border-blue-100 rounded-2xl">
          <ChapterMultiSelect
            classValue={group.class_name}
            subject={group.subject}
            value={group.chapters || []}
            onChange={arr => onChange('chapters', arr)}
            label="Related chapter(s) — applies to every file in this group"
          />
        </div>
      )}

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
  const [isUrlImport, setIsUrlImport]   = useState(false);
  const [importUrl, setImportUrl]       = useState('');
  const [detecting, setDetecting]       = useState(false);
  const [detected, setDetected]         = useState(null);   // { count, chapters:[{unit,chars}], bytes } | null
  const [detectError, setDetectError]   = useState(null);
  const [formData, setFormData] = useState({
    class_name: '', subject: '', type: '', isBulk: false,
    chapterCount: 1, chapters: [{ unit: '', title: '', file: null, chapters: [] }],
  });
  const [bulkFiles, setBulkFiles]       = useState([]);
  const [bulkChapters, setBulkChapters] = useState([]);
  const [autoDetectUnits, setAutoDetectUnits] = useState(false);  // bulk textbooks: AI-name from PDF vs filename
  const [detectedNames, setDetectedNames] = useState(null);       // [{filename,name,detected}] aligned to bulkFiles | null
  const [namingBusy, setNamingBusy]       = useState(false);
  const [nameError, setNameError]         = useState(null);
  // Bulk textbook "split into sub-chapters" mode: each PDF is auto-split into its lessons/poems.
  const [bulkSplit, setBulkSplit]         = useState(false);
  const [splitPreview, setSplitPreview]   = useState(null);       // [{filename,chapters:[],count,split}] aligned to bulkFiles | null
  const [splitBusy, setSplitBusy]         = useState(false);
  const [splitError, setSplitError]       = useState(null);
  // Parsed table-of-contents (BookContents) for exact official lesson splits.
  const [tocInfo, setTocInfo]             = useState(null);       // {exists,title,unit_count,lesson_count}|null
  const [tocBusy, setTocBusy]             = useState(false);
  const [tocError, setTocError]           = useState(null);
  const [subjectGroups, setSubjectGroups] = useState([
    { class_name: '', subject: '', type: '', files: [], chapters: [] },
  ]);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState(null);
  const [success, setSuccess]           = useState(null);
  const [fileProgress, setFileProgress] = useState({});
  // Named vector stores (superadmin only): pick which store this upload feeds. '' = global shared.
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [vectorStores, setVectorStores] = useState([]);
  const [vectorStoreId, setVectorStoreId] = useState('');

  useEffect(() => {
    const u = JSON.parse(localStorage.getItem('user') || 'null');
    if (u?.role === 'superadmin') {
      setIsSuperAdmin(true);
      apiClient.get('/admin/vector-stores/')
        .then(r => setVectorStores(r.data || []))
        .catch(() => setVectorStores([]));
    }
  }, []);

  const setFilePct = (key, pct, status) =>
    setFileProgress(prev => ({ ...prev, [key]: { pct, status } }));

  const handleFieldChange = (field, value) => {
    setFormData(prev => {
      const next = { ...prev, [field]: value };
      if (field === 'chapterCount') {
        const count = parseInt(value) || 0;
        const chs = [...prev.chapters];
        if (count > chs.length) for (let i = chs.length; i < count; i++) chs.push({ unit: '', title: '', file: null, chapters: [] });
        else chs.splice(count);
        next.chapters = chs;
      }
      // Selected chapters belong to a specific class+subject — drop them when either changes.
      if (field === 'class_name' || field === 'subject') {
        next.chapters = (next.chapters || prev.chapters).map(c => ({ ...c, chapters: [] }));
      }
      return next;
    });
    if (field === 'class_name' || field === 'subject') {
      setBulkChapters([]);
      // Detected units/names are subject-specific (they snap to that subject's catalog) — re-detect.
      setDetected(null);
      setDetectError(null);
      setDetectedNames(null);
      setNameError(null);
      setSplitPreview(null);
      setSplitError(null);
    }
    // Switching material type changes whether names come from the PDF at all — drop stale names.
    if (field === 'type') { setDetectedNames(null); setNameError(null); setSplitPreview(null); setSplitError(null); }
  };

  const handleChapterChange = (index, field, value) => {
    const chs = [...formData.chapters];
    chs[index][field] = value;
    setFormData({ ...formData, chapters: chs });
  };

  const updateGroup = (index, field, value) => {
    setSubjectGroups(prev => prev.map((g, i) => {
      if (i !== index) return g;
      const ng = { ...g, [field]: value };
      if (field === 'class_name' || field === 'subject') ng.chapters = [];  // chapters are class+subject specific
      return ng;
    }));
  };

  const addGroup = () => setSubjectGroups(prev => [...prev, { class_name: '', subject: '', type: '', files: [], chapters: [] }]);

  const removeGroup = index => setSubjectGroups(prev => prev.filter((_, i) => i !== index));

  const resetForm = () => {
    setFormData({ class_name: '', subject: '', type: '', isBulk: false, chapterCount: 1, chapters: [{ unit: '', title: '', file: null, chapters: [] }] });
    setBulkFiles([]);
    setBulkChapters([]);
    setAutoDetectUnits(false);
    setDetectedNames(null);
    setNameError(null);
    setBulkSplit(false);
    setSplitPreview(null);
    setSplitError(null);
    setSubjectGroups([{ class_name: '', subject: '', type: '', files: [], chapters: [] }]);
    setFileProgress({});
    setImportUrl('');
    setDetected(null);
    setDetectError(null);
    setError(null);
    setSuccess(null);
  };

  // ── URL import: fetch the page and show its detected chapter units (no ingest yet) ──
  const handleDetectUnits = async () => {
    setDetectError(null);
    setDetected(null);
    const url = importUrl.trim();
    if (!url.toLowerCase().startsWith('http')) { setDetectError('Enter a valid http(s) URL'); return; }
    if (!formData.subject)                      { setDetectError('Pick a Subject first — unit names snap to it'); return; }
    setDetecting(true);
    try {
      const res = await apiClient.post('/materials/preview-url/', { url, subject: formData.subject });
      setDetected(res.data);
      if (!res.data?.count) setDetectError('No chapter units could be detected on that page.');
    } catch (err) {
      setDetectError(err.response?.data?.error || 'Could not read that URL');
    } finally {
      setDetecting(false);
    }
  };

  // ── Bulk textbooks: read each PDF and detect its chapter name, shown for review before upload ──
  const handleDetectNames = async () => {
    setNameError(null);
    if (bulkFiles.length === 0) { setNameError('Select PDF files first'); return; }
    if (!formData.subject)      { setNameError('Pick a Subject first — names snap to it'); return; }
    setNamingBusy(true);
    try {
      const data = new FormData();
      data.append('class_name', formData.class_name);
      data.append('subject', formData.subject);
      bulkFiles.forEach(f => data.append('files', f));
      const res = await apiClient.post('/materials/preview-names/', data, { headers: { 'Content-Type': 'multipart/form-data' } });
      // Align to bulkFiles by index (server preserves order); fall back to filename if unmatched.
      const names = res.data?.names || [];
      setDetectedNames(bulkFiles.map((f, i) => ({
        filename: f.name,
        name: (names[i]?.name) || f.name.replace(/\.[^.]+$/, ''),
        detected: !!names[i]?.detected,
      })));
    } catch (err) {
      setNameError(err.response?.data?.error || 'Could not detect names');
    } finally {
      setNamingBusy(false);
    }
  };

  // ── Book contents (TOC): fetch existing, and import from the prelims PDF ──
  useEffect(() => {
    if (!(bulkSplit && formData.type === 'textbook' && formData.class_name && formData.subject)) {
      setTocInfo(null);
      return;
    }
    apiClient.get(`/materials/book-contents/?class_name=${encodeURIComponent(formData.class_name)}&subject=${encodeURIComponent(formData.subject)}`)
      .then(r => setTocInfo(r.data))
      .catch(() => setTocInfo(null));
  }, [bulkSplit, formData.type, formData.class_name, formData.subject]);

  const handleImportContents = async (file) => {
    if (!file) return;
    if (!formData.class_name || !formData.subject) { setTocError('Pick Class and Subject first'); return; }
    setTocBusy(true); setTocError(null);
    try {
      const data = new FormData();
      data.append('class_name', formData.class_name);
      data.append('subject', formData.subject);
      data.append('file', file);
      const r = await apiClient.post('/materials/book-contents/', data, { headers: { 'Content-Type': 'multipart/form-data' } });
      setTocInfo(r.data);
      setSplitPreview(null);   // re-detect so splits use the imported contents
    } catch (err) {
      setTocError(err.response?.data?.error || 'Could not parse a table of contents from that PDF');
    } finally {
      setTocBusy(false);
    }
  };

  // ── Bulk textbooks (split mode): detect each PDF's sub-chapters (lessons) for review ──
  const handleDetectSplit = async () => {
    setSplitError(null);
    if (bulkFiles.length === 0) { setSplitError('Select PDF files first'); return; }
    if (!formData.subject)      { setSplitError('Pick a Subject first — names snap to it'); return; }
    setSplitBusy(true);
    try {
      const data = new FormData();
      data.append('class_name', formData.class_name);
      data.append('subject', formData.subject);
      bulkFiles.forEach(f => data.append('files', f));
      const res = await apiClient.post('/materials/preview-split/', data, { headers: { 'Content-Type': 'multipart/form-data' } });
      const filesOut = res.data?.files || [];
      setSplitPreview(bulkFiles.map((f, i) => filesOut[i] || {
        filename: f.name, chapters: [f.name.replace(/\.[^.]+$/, '')], count: 1, split: false,
      }));
    } catch (err) {
      setSplitError(err.response?.data?.error || 'Could not detect sub-chapters');
    } finally {
      setSplitBusy(false);
    }
  };

  const uploadSingle = async (key, formPayload) => {
    if (vectorStoreId) formPayload.append('vector_store_id', vectorStoreId);
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
      if (isUrlImport) {
        // ── Import a whole HTML book by URL → one Material per detected chapter ──
        if (!formData.class_name || !formData.subject || !formData.type)
          throw new Error('Select Class, Subject and Type first');
        if (!importUrl.trim()) throw new Error('Enter a book URL');
        if (!detected || !detected.count) throw new Error('Click "Detect units" and confirm the chapters first');
        const data = new FormData();
        data.append('class_name', formData.class_name);
        data.append('subject', formData.subject);
        data.append('type', formData.type);
        data.append('import_url', importUrl.trim());
        data.append('embedding_provider', embeddingProvider);
        if (vectorStoreId) data.append('vector_store_id', vectorStoreId);
        const res = await apiClient.post('/materials/', data, { headers: { 'Content-Type': 'multipart/form-data' } });
        setSuccess(res.data?.message || `Importing ${detected.count} chapter(s) from the URL in the background.`);
        setTimeout(resetForm, 4000);
        return;
      }

      if (isMultiSubject) {
        // ── Multi-subject mode ──────────────────────────────────────────────
        for (let gi = 0; gi < subjectGroups.length; gi++) {
          const g = subjectGroups[gi];
          if (!g.class_name || !g.subject || !g.type) throw new Error(`Group ${gi + 1}: please fill in Class, Subject and Type`);
          if (g.files.length === 0) throw new Error(`Group ${gi + 1}: no files selected`);
          if (g.type !== 'textbook' && (g.chapters || []).length === 0)
            throw new Error(`Group ${gi + 1}: select at least one chapter this material relates to`);
          for (const file of g.files) {
            const data = new FormData();
            data.append('class_name', g.class_name);
            data.append('subject', g.subject);
            data.append('type', g.type);
            data.append('bulk_upload', 'true');
            data.append('bulk_files', file);
            if (g.type !== 'textbook') data.append('chapters', JSON.stringify(g.chapters));
            data.append('embedding_provider', embeddingProvider);
            await uploadSingle(`${gi}-${file.name}`, data);
          }
        }
      } else if (formData.isBulk) {
        // ── Single-subject bulk mode ────────────────────────────────────────
        if (bulkFiles.length === 0) throw new Error('Please select at least one file');
        if (formData.type !== 'textbook' && bulkChapters.length === 0)
          throw new Error('Select at least one chapter this material relates to');
        // AI naming (textbooks): names were detected & reviewed first — upload each file with its
        // confirmed name via the per-file fields (the bulk path can't carry a name per file).
        const useAINaming = formData.type === 'textbook' && autoDetectUnits;
        const useSplit    = formData.type === 'textbook' && bulkSplit;
        if (useAINaming && !detectedNames)
          throw new Error('Click "Detect chapter names" and review them before uploading');
        if (useSplit && !splitPreview)
          throw new Error('Click "Detect sub-chapters" and review them before uploading');
        for (let i = 0; i < bulkFiles.length; i++) {
          const file = bulkFiles[i];
          const data = new FormData();
          data.append('class_name', formData.class_name);
          data.append('subject', formData.subject);
          data.append('type', formData.type);
          if (useSplit) {
            // Whole-unit PDF → server splits it into its lessons (detect_book_chapters).
            data.append('split_book', 'true');
            data.append('bulk_files', file);
          } else if (useAINaming) {
            const nm = (detectedNames[i]?.name || file.name.replace(/\.[^.]+$/, '')).trim();
            data.append('bulk_upload', 'false');
            data.append('chapter_count', '1');
            data.append('unit_0', nm);
            data.append('title_0', nm);
            data.append('file_0', file);
          } else {
            data.append('bulk_upload', 'true');
            data.append('bulk_files', file);
            if (formData.type !== 'textbook') data.append('chapters', JSON.stringify(bulkChapters));
          }
          data.append('embedding_provider', embeddingProvider);
          await uploadSingle(file.name, data);
        }
      } else {
        // ── Chapter-by-chapter mode ─────────────────────────────────────────
        const isTextbook = formData.type === 'textbook';
        formData.chapters.forEach((ch, i) => {
          if (!ch.file) throw new Error(`Please select a file for ${isTextbook ? 'Chapter' : 'File'} ${i + 1}`);
          if (!isTextbook && (ch.chapters || []).length === 0)
            throw new Error(`File ${i + 1}: select at least one chapter it relates to`);
        });
        for (let i = 0; i < formData.chapters.length; i++) {
          const ch = formData.chapters[i];
          const data = new FormData();
          data.append('class_name', formData.class_name);
          data.append('subject', formData.subject);
          data.append('type', formData.type);
          data.append('bulk_upload', 'false');
          data.append('chapter_count', '1');
          data.append('unit_0', isTextbook ? ch.unit : (ch.chapters[0] || ''));
          data.append('title_0', ch.title);
          data.append('file_0', ch.file);
          if (!isTextbook) data.append('chapters_0', JSON.stringify(ch.chapters));
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
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Library</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Upload Materials</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Add textbooks, notes, and references to the AI library.</p>
        </div>
        
        <div className="flex items-center gap-4">
          <Link href="/materials" className="flex items-center gap-2 bg-white border border-slate-200 text-slate-700 px-6 py-3.5 rounded-2xl font-bold text-[13px] hover:bg-slate-50 hover:text-indigo-600 hover:border-indigo-200 transition-all active:scale-[0.98]">
            <ArrowLeft size={16} />
            Back to Library
          </Link>
        </div>
      </div>

      {error   && <ErrorAlert   message={error}   onClose={() => setError(null)}   className="mb-6 max-w-7xl mx-auto" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6 max-w-7xl mx-auto" />}

      <form onSubmit={handleSubmit} className="max-w-7xl mx-auto relative z-[50]">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

        {/* RIGHT — Upload Settings, in its own container (sticky on desktop, on top on mobile) */}
        <aside className="xl:col-span-4 xl:order-2 xl:sticky xl:top-6">
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative z-[60]">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center">
              <Settings size={18} strokeWidth={2} />
            </div>
            <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Upload Configuration</h2>
          </div>
          <div className="space-y-4">

            {/* Import-from-URL toggle — only when not multi-subject */}
            {!isMultiSubject && (
              <div className="p-6 bg-teal-50/40 border border-teal-100 rounded-[30px] flex items-center justify-between group transition-all hover:bg-teal-50">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center text-teal-600 shadow-sm transition-transform group-hover:scale-110">
                    <Globe size={24} />
                  </div>
                  <div>
                    <h4 className="font-black text-gray-900 uppercase tracking-tight">Import from URL</h4>
                    <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mt-0.5">Paste an HTML textbook link — auto-splits into chapters.</p>
                  </div>
                </div>
                <Toggle checked={isUrlImport} activeClass="bg-teal-600"
                  onChange={val => { setIsUrlImport(val); if (val) handleFieldChange('isBulk', false); }} />
              </div>
            )}

            {/* Multi-subject toggle — only when not importing from URL */}
            {!isUrlImport && (
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
              <Toggle checked={isMultiSubject} activeClass="bg-violet-600" onChange={setIsMultiSubject} />
            </div>
            )}

            {/* Bulk toggle — only when not multi-subject and not URL import */}
            {!isMultiSubject && !isUrlImport && (
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
                <Toggle checked={formData.isBulk} activeClass="bg-[#1e293b]"
                  onChange={val => handleFieldChange('isBulk', val)} />
              </div>
            )}

            {/* Embedding provider */}
            <div className="p-6 bg-slate-50/50 border border-slate-100 rounded-[30px]">
              <div className="flex items-center gap-3 mb-4">
                <Cpu size={18} className="text-slate-500" />
                <h4 className="font-black text-gray-900 uppercase tracking-tight text-sm">Embedding Provider</h4>
              </div>
              <div className="grid grid-cols-1 gap-3">
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

            {/* Vector store (superadmin only) — which named store this upload feeds. */}
            {isSuperAdmin && (
              <div className="p-6 bg-slate-50/50 border border-slate-100 rounded-[30px]">
                <div className="flex items-center gap-3 mb-1.5">
                  <Database size={18} className="text-slate-500" />
                  <h4 className="font-black text-gray-900 uppercase tracking-tight text-sm">Vector Store</h4>
                </div>
                <p className="text-[11px] font-semibold text-slate-400 mb-4">
                  Add this material to a named store (seen only by the institutions it is allocated to).
                  Leave as “Global shared store” for the default behaviour.
                </p>
                <CustomSelect
                  label="Store"
                  icon={Database}
                  value={vectorStoreId}
                  onChange={setVectorStoreId}
                  options={[{ label: 'Global shared store (default)', value: '' },
                            ...vectorStores.map(s => ({ label: `${s.name} · ${s.school_count} school(s)`, value: String(s.id) }))]}
                  placeholder="Global shared store (default)"
                />
                <Link href="/superadmin/vector-stores" className="inline-flex items-center gap-1 mt-3 text-xs font-bold text-blue-600 hover:text-blue-800">
                  <Plus className="w-3.5 h-3.5" /> Manage vector stores
                </Link>
              </div>
            )}
          </div>
        </div>
        </aside>

        {/* LEFT — main upload area */}
        <div className="lg:col-span-12 xl:col-span-8 space-y-8">
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
            {/* z-30 keeps the Class/Subject/Type dropdowns above the file card below it */}
            <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative z-[50]">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center">
                  <Database size={18} strokeWidth={2} />
                </div>
                <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Source Details</h2>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                <CustomSelect label="Class" icon={Layers} value={formData.class_name}
                  onChange={v => handleFieldChange('class_name', v)} options={CLASS_OPTIONS} placeholder="Select Class" />
                <CustomSelect label="Subject" icon={BookOpen} value={formData.subject}
                  onChange={v => handleFieldChange('subject', v)} options={subjectOptions} placeholder="Select Subject" />
                <CustomSelect label="Material Type" icon={Settings} value={formData.type}
                  onChange={v => handleFieldChange('type', v)} options={TYPE_OPTIONS} placeholder="Select type" />
              </div>
            </div>

            {/* ── URL import section ───────────────────────────────────────── */}
            {isUrlImport ? (
              <div className="glass-card p-8 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500 relative z-10 overflow-visible">
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 bg-teal-600 text-white rounded-xl flex items-center justify-center shadow-lg shadow-teal-200">
                    <Globe size={20} />
                  </div>
                  <div>
                    <h3 className="text-xl font-black text-gray-900 uppercase tracking-tight">Import Book from URL</h3>
                    <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest mt-0.5">HTML textbook → auto-split into chapter units</p>
                  </div>
                </div>

                {/* URL input + detect */}
                <div className="flex flex-col sm:flex-row gap-3 mb-2">
                  <div className="relative flex-1">
                    <Globe size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300" />
                    <input
                      type="url"
                      inputMode="url"
                      placeholder="https://…/10-Tamil-TM/10-Tamil-TM.html"
                      value={importUrl}
                      onChange={e => { setImportUrl(e.target.value); setDetected(null); setDetectError(null); }}
                      className="w-full pl-11 pr-4 py-4 bg-gray-50/50 border border-gray-100 rounded-2xl focus:ring-2 focus:ring-teal-500 outline-none text-sm font-bold" />
                  </div>
                  <button type="button" onClick={handleDetectUnits} disabled={detecting}
                    className="flex items-center justify-center gap-2 px-7 py-4 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-black active:scale-95 disabled:opacity-50 shrink-0">
                    {detecting ? <><RefreshCw size={16} className="animate-spin" /> Reading…</> : <><Search size={16} /> Detect units</>}
                  </button>
                </div>
                <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider mb-6 px-1">Works with TN-schools style HTML books — extracts clean text even where PDFs fail (Tamil/Hindi).</p>

                {detectError && (
                  <div className="flex items-center gap-2 p-4 bg-red-50 border border-red-100 rounded-2xl text-red-600 mb-4">
                    <AlertCircle size={16} /><span className="text-xs font-bold">{detectError}</span>
                  </div>
                )}

                {/* Detected units preview */}
                {detected && detected.count > 0 && (
                  <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <ListTree size={16} className="text-teal-600" />
                        <span className="text-xs font-black text-gray-900 uppercase tracking-widest">{detected.count} chapter unit(s) detected</span>
                      </div>
                      <span className="text-[10px] font-black text-gray-400 uppercase tracking-wider">{(detected.bytes / (1024 * 1024)).toFixed(1)} MB page</span>
                    </div>
                    <div className="max-h-80 overflow-y-auto pr-1 space-y-2">
                      {detected.chapters.map((c, i) => (
                        <div key={i} className="flex items-center gap-3 p-3 bg-white border border-gray-100 rounded-2xl shadow-sm">
                          <span className="w-7 h-7 bg-teal-50 text-teal-600 rounded-lg flex items-center justify-center font-black text-[11px] shrink-0">{i + 1}</span>
                          <span className="flex-1 min-w-0 text-sm font-bold text-gray-800 truncate">{c.unit}</span>
                          <span className="text-[10px] font-black text-gray-400 uppercase tracking-wider shrink-0">{(c.chars / 1000).toFixed(1)}k chars</span>
                        </div>
                      ))}
                    </div>
                    <p className="text-[10px] text-emerald-600 font-bold uppercase tracking-wider mt-4 px-1">Looks right? Click “Import Book” below — each unit is embedded into the vector store.</p>
                  </div>
                )}
              </div>
            ) : formData.isBulk ? (
              <div className="glass-card p-8 mb-8 animate-in fade-in slide-in-from-bottom-4 duration-500 relative z-10 overflow-visible">
                {formData.type && formData.type !== 'textbook' && (
                  <div className="mb-6 p-5 bg-blue-50/30 border border-blue-100 rounded-2xl">
                    <ChapterMultiSelect
                      classValue={formData.class_name}
                      subject={formData.subject}
                      value={bulkChapters}
                      onChange={setBulkChapters}
                      label="Related chapter(s) — applies to every file below"
                    />
                  </div>
                )}
                {/* Textbook bulk: choose how each chapter is named — filename vs LLM reading the PDF */}
                {formData.type === 'textbook' && (
                  <div className="mb-6 p-5 bg-violet-50/30 border border-violet-100 rounded-2xl">
                    <div className="flex items-center gap-2 mb-3">
                      <Sparkles size={16} className="text-violet-500" />
                      <h4 className="font-black text-gray-900 uppercase tracking-tight text-xs">Chapter naming</h4>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      {[
                        { m: 'filename', label: 'Use filename',          sub: 'The PDF filename becomes the chapter name', Icon: FileText },
                        { m: 'ai',       label: 'Detect with AI',         sub: 'Read each PDF & name it (one name per file)', Icon: Sparkles },
                        { m: 'split',    label: 'Split into sub-chapters', sub: 'Auto-split each PDF into its lessons/poems', Icon: ListTree },
                      ].map(({ m, label, sub, Icon }) => {
                        const mode = bulkSplit ? 'split' : autoDetectUnits ? 'ai' : 'filename';
                        const on = mode === m;
                        return (
                          <button key={m} type="button"
                            onClick={() => {
                              setAutoDetectUnits(m === 'ai');
                              setBulkSplit(m === 'split');
                              setDetectedNames(null); setNameError(null);
                              setSplitPreview(null); setSplitError(null);
                            }}
                            className={`flex items-center gap-3 p-4 rounded-2xl border-2 transition-all text-left ${on ? 'border-violet-500 bg-violet-50 text-violet-700' : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'}`}>
                            <Icon size={18} className="shrink-0" />
                            <div className="min-w-0">
                              <p className="font-black text-xs uppercase tracking-tight">{label}</p>
                              <p className="text-[10px] font-bold opacity-70 mt-0.5 leading-tight">{sub}</p>
                            </div>
                            {on && <CheckCircle size={16} className="ml-auto shrink-0" />}
                          </button>
                        );
                      })}
                    </div>

                    {/* Book contents (TOC) — optional, makes the split use exact official titles */}
                    {bulkSplit && (
                      <div className="mt-4 p-4 bg-white border border-violet-100 rounded-2xl">
                        <div className="flex items-center gap-2 mb-1.5">
                          <ListTree size={15} className="text-violet-500" />
                          <h5 className="font-black text-gray-900 uppercase tracking-tight text-[11px]">Book contents — optional, most accurate</h5>
                        </div>
                        <p className="text-[10px] font-bold text-gray-400 leading-tight mb-3">
                          Upload the book&apos;s contents/prelims PDF once. Unit files then split into the EXACT official lessons listed in the table of contents (no guessing).
                        </p>
                        {tocInfo?.exists && (
                          <div className="flex items-center gap-1.5 text-[11px] font-black text-emerald-600 mb-2.5">
                            <CheckCircle size={14} /> Contents imported{tocInfo.title ? `: ${tocInfo.title}` : ''} · {tocInfo.unit_count} units · {tocInfo.lesson_count} lessons
                          </div>
                        )}
                        <input type="file" accept=".pdf" id="toc-input" className="hidden"
                          onChange={e => handleImportContents(e.target.files[0])} />
                        <label htmlFor="toc-input"
                          className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl font-black text-[11px] uppercase tracking-wider cursor-pointer transition-all active:scale-95">
                          {tocBusy
                            ? <><RefreshCw size={14} className="animate-spin" /> Reading contents…</>
                            : <><FileUp size={14} /> {tocInfo?.exists ? 'Replace contents PDF' : 'Upload contents PDF'}</>}
                        </label>
                        {tocError && <p className="text-[10px] font-bold text-red-500 mt-2">{tocError}</p>}
                      </div>
                    )}
                  </div>
                )}
                <div className="text-center py-10 border-2 border-dashed border-gray-200 rounded-[40px] bg-gray-50/30">
                  <input type="file" multiple accept=".pdf" onChange={e => { setBulkFiles(Array.from(e.target.files)); setDetectedNames(null); setNameError(null); }} className="hidden" id="bulk-file-input" />
                  <label htmlFor="bulk-file-input" className="cursor-pointer">
                    <div className="w-20 h-20 bg-white rounded-[30px] shadow-sm flex items-center justify-center mx-auto mb-6 text-blue-600 ring-8 ring-blue-50/50">
                      <FileUp size={40} />
                    </div>
                    <h3 className="text-xl font-black text-gray-900 mb-2">Select Multiple PDF Files</h3>
                    <p className="text-sm text-gray-400 font-medium mb-8 max-w-xs mx-auto">
                      {formData.type === 'textbook' && autoDetectUnits
                        ? 'Then detect each PDF’s chapter name for review before uploading. Up to 50 files.'
                        : 'Filenames will be automatically assigned as titles. Up to 50 files.'}
                    </p>
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

                {/* AI naming (textbooks): detect each PDF's chapter name, review/edit, THEN upload */}
                {formData.type === 'textbook' && autoDetectUnits && bulkFiles.length > 0 && (
                  <div className="mt-6">
                    <button type="button" onClick={handleDetectNames} disabled={namingBusy}
                      className="flex items-center justify-center gap-2 w-full sm:w-auto px-7 py-4 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-black active:scale-95 disabled:opacity-50">
                      {namingBusy
                        ? <><RefreshCw size={16} className="animate-spin" /> Reading {bulkFiles.length} PDF(s)…</>
                        : <><Sparkles size={16} /> {detectedNames ? 'Re-detect chapter names' : 'Detect chapter names'}</>}
                    </button>

                    {nameError && (
                      <div className="flex items-center gap-2 p-4 mt-4 bg-red-50 border border-red-100 rounded-2xl text-red-600">
                        <AlertCircle size={16} /><span className="text-xs font-bold">{nameError}</span>
                      </div>
                    )}

                    {detectedNames && (
                      <div className="mt-5 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="flex items-center gap-2 mb-3">
                          <Sparkles size={16} className="text-violet-600" />
                          <span className="text-xs font-black text-gray-900 uppercase tracking-widest">Review chapter names — edit any before uploading</span>
                        </div>
                        <div className="max-h-96 overflow-y-auto pr-1 space-y-2">
                          {detectedNames.map((d, i) => (
                            <div key={i} className="flex items-center gap-3 p-3 bg-white border border-gray-100 rounded-2xl shadow-sm">
                              <span className="w-7 h-7 bg-violet-50 text-violet-600 rounded-lg flex items-center justify-center font-black text-[11px] shrink-0">{i + 1}</span>
                              <div className="flex-1 min-w-0">
                                <input type="text" value={d.name}
                                  onChange={e => setDetectedNames(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                                  className="w-full px-3 py-2 bg-gray-50/60 border border-gray-100 rounded-xl focus:ring-2 focus:ring-violet-500 outline-none text-sm font-bold" />
                                <p className="text-[10px] font-bold text-gray-400 truncate mt-1 px-1">{d.filename}</p>
                              </div>
                              <span className={`text-[9px] font-black uppercase tracking-wider shrink-0 px-2 py-1 rounded-full ${d.detected ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                                {d.detected ? 'AI' : 'filename'}
                              </span>
                            </div>
                          ))}
                        </div>
                        <p className="text-[10px] text-emerald-600 font-bold uppercase tracking-wider mt-4 px-1">Looks right? Click “Upload Materials” below — these names become the chapter titles.</p>
                      </div>
                    )}
                  </div>
                )}

                {/* Split mode (textbooks): detect each PDF's sub-chapters, review, THEN upload */}
                {formData.type === 'textbook' && bulkSplit && bulkFiles.length > 0 && (
                  <div className="mt-6">
                    <button type="button" onClick={handleDetectSplit} disabled={splitBusy}
                      className="flex items-center justify-center gap-2 w-full sm:w-auto px-7 py-4 bg-[#1e293b] text-white rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-black active:scale-95 disabled:opacity-50">
                      {splitBusy
                        ? <><RefreshCw size={16} className="animate-spin" /> Splitting {bulkFiles.length} PDF(s)…</>
                        : <><ListTree size={16} /> {splitPreview ? 'Re-detect sub-chapters' : 'Detect sub-chapters'}</>}
                    </button>

                    {splitError && (
                      <div className="flex items-center gap-2 p-4 mt-4 bg-red-50 border border-red-100 rounded-2xl text-red-600">
                        <AlertCircle size={16} /><span className="text-xs font-bold">{splitError}</span>
                      </div>
                    )}

                    {splitPreview && (
                      <div className="mt-5 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="flex items-center gap-2 mb-3">
                          <ListTree size={16} className="text-violet-600" />
                          <span className="text-xs font-black text-gray-900 uppercase tracking-widest">Review sub-chapters — each becomes its own material</span>
                        </div>
                        <div className="max-h-96 overflow-y-auto pr-1 space-y-3">
                          {splitPreview.map((f, i) => (
                            <div key={i} className="p-4 bg-white border border-gray-100 rounded-2xl shadow-sm">
                              <div className="flex items-center gap-2 mb-3">
                                <FileText size={14} className="text-gray-400 shrink-0" />
                                <span className="flex-1 min-w-0 text-[11px] font-black text-gray-500 uppercase tracking-wider truncate">{f.filename}</span>
                                <span className={`text-[9px] font-black uppercase tracking-wider shrink-0 px-2 py-1 rounded-full ${f.split ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                                  {f.split ? `${f.count} sub-chapters` : 'single unit'}
                                </span>
                              </div>
                              <div className="space-y-1.5 pl-1">
                                {f.chapters.map((ch, j) => (
                                  <div key={j} className="flex items-center gap-2.5">
                                    <span className="w-6 h-6 bg-violet-50 text-violet-600 rounded-lg flex items-center justify-center font-black text-[10px] shrink-0">{j + 1}</span>
                                    <span className="text-sm font-bold text-gray-800 truncate">{ch}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                        <p className="text-[10px] text-emerald-600 font-bold uppercase tracking-wider mt-4 px-1">Looks right? Click “Upload Materials” below — each sub-chapter is embedded as its own unit.</p>
                      </div>
                    )}
                  </div>
                )}
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
                          <h4 className="font-black text-gray-900 uppercase text-sm tracking-widest">{formData.type === 'textbook' ? 'Chapter Details' : 'File Details'}</h4>
                        </div>
                        <div className="space-y-4">
                          {formData.type === 'textbook' ? (
                            <input required type="text" placeholder="Unit / Chapter Name (e.g. Atoms)"
                              value={chapter.unit} onChange={e => handleChapterChange(idx, 'unit', e.target.value)}
                              className="w-full px-4 py-3 bg-gray-50/50 border border-gray-100 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-bold" />
                          ) : (
                            <ChapterMultiSelect
                              classValue={formData.class_name}
                              subject={formData.subject}
                              value={chapter.chapters || []}
                              onChange={arr => handleChapterChange(idx, 'chapters', arr)}
                              label="Related chapter(s)"
                            />
                          )}
                          <input required={formData.type === 'textbook'} type="text" placeholder="Display Title (optional)"
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
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 p-6 mt-8 bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative z-[40]">
          <div className="flex items-center gap-4 text-slate-400">
            <HelpCircle size={18} />
            <p className="text-[11px] font-bold uppercase tracking-wider">All uploads are processed by AI for concept extraction.</p>
          </div>
          <div className="flex items-center gap-4 w-full md:w-auto">
            <button type="button" onClick={resetForm}
              className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-3.5 bg-white border border-slate-200 text-slate-500 hover:text-slate-900 rounded-2xl font-bold text-[13px] uppercase tracking-wider hover:bg-slate-50 transition-all active:scale-95">
              <Undo size={16} /> Reset
            </button>
            <button disabled={loading || (isUrlImport && !(detected && detected.count > 0)) || (formData.isBulk && formData.type === 'textbook' && autoDetectUnits && !detectedNames) || (formData.isBulk && formData.type === 'textbook' && bulkSplit && !splitPreview)} type="submit"
              className="flex-1 md:flex-none flex items-center justify-center gap-2 px-8 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-bold text-[13px] uppercase tracking-wider shadow-lg shadow-indigo-200/50 transition-all active:scale-[0.98] disabled:opacity-50">
              {loading
                ? <><RefreshCw size={18} className="animate-spin" /> Processing...</>
                : isUrlImport
                  ? <><Globe size={18} /> Import Book{detected?.count ? ` (${detected.count})` : ''}</>
                  : <><Upload size={18} /> Upload Materials</>}
            </button>
          </div>
        </div>
        </div>{/* /LEFT main column */}
        </div>{/* /grid */}
      </form>
    </div>
  );
}
