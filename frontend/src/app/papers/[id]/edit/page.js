'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import {
  ArrowLeft, Save, FileDown, Loader2, ImagePlus,
  Sparkles, Send, CheckCircle, AlertCircle, X, RotateCcw, Eye, Pencil
} from 'lucide-react';

export default function EditPaperPage() {
  const { id } = useParams();

  const [paper, setPaper]       = useState(null);
  const [loading, setLoading]   = useState(true);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState(null);
  const [saving, setSaving]     = useState(false);
  const [exporting, setExporting] = useState(false);
  const [mode, setMode]         = useState('view');

  const [aiInput, setAiInput]         = useState('');
  const [aiLoading, setAiLoading]     = useState(false);
  const [aiStatus, setAiStatus]       = useState('');  // 'correcting' | 'rendering' | ''
  const [history, setHistory]         = useState([]);
  const [docText, setDocText]         = useState('');   // properly-ordered text from backend

  const [imgUploading, setImgUploading] = useState(false);
  const fileRef      = useRef(null);
  const containerRef = useRef(null);   // div that holds the iframe

  const [toast, setToast] = useState(null);

  // ── helpers ────────────────────────────────────────────────────────────────
  const getIframe = () => containerRef.current?.querySelector('iframe');
  const getIDoc   = () => {
    const f = getIframe();
    return f?.contentDocument || f?.contentWindow?.document;
  };
  const getIframeText = () => getIDoc()?.body?.innerText || '';

  const showToast = (type, msg) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 4000);
  };

  const resizeIframe = (iDoc) => {
    const iframe = getIframe();
    if (!iframe) return;
    const h = iDoc.documentElement.scrollHeight;
    if (h > 100) iframe.style.height = h + 'px';
  };

  // ── render blob into the iframe ────────────────────────────────────────────
  const renderBlob = useCallback(async (blob, editable = false) => {
    if (!containerRef.current || !blob) return;
    try {
      setRendering(true);
      setRenderError(null);
      containerRef.current.innerHTML = '';

      const iframe = document.createElement('iframe');
      iframe.style.cssText = 'width:100%;border:none;display:block;min-height:600px;';
      containerRef.current.appendChild(iframe);

      const iDoc = iframe.contentDocument || iframe.contentWindow.document;
      iDoc.open();
      iDoc.write('<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        + '<body style="margin:0;padding:0;background:#e5e7eb;"></body></html>');
      iDoc.close();

      const { renderAsync } = await import('docx-preview');
      await renderAsync(blob, iDoc.body, iDoc.head, {
        className: 'docx',
        inWrapper: true,
        ignoreWidth: false,
        ignoreHeight: false,
        ignoreFonts: false,
        breakPages: true,
        ignoreLastRenderedPageBreak: true,
        experimental: true,
        trimXmlDeclaration: true,
      });

      if (editable) applyEditable(iDoc);

      resizeIframe(iDoc);
      setTimeout(() => resizeIframe(iDoc), 600);
    } catch (e) {
      console.error('docx-preview', e);
      setRenderError(e?.message || 'Render failed');
    } finally {
      setRendering(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyEditable = (iDoc) => {
    iDoc.body.contentEditable = 'true';
    iDoc.body.style.outline = 'none';
    iDoc.body.style.cursor  = 'text';
    // thin blue inset ring so the user knows they're editing
    iDoc.body.style.boxShadow = 'inset 0 0 0 3px rgba(59,130,246,0.25)';
  };

  const removeEditable = (iDoc) => {
    iDoc.body.contentEditable = 'false';
    iDoc.body.style.cursor    = 'default';
    iDoc.body.style.boxShadow = 'none';
  };

  // ── load ───────────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    try {
      setLoading(true);
      const paperRes = await apiClient.get(`/papers/${id}/`);
      setPaper(paperRes.data);

      if (paperRes.data.file) {
        // Fetch DOCX blob and properly-ordered text in parallel
        const [fileRes, contentRes] = await Promise.all([
          apiClient.get(`/papers/${id}/docx_file/`, { responseType: 'blob' }),
          apiClient.get(`/papers/${id}/get_content/`),
        ]);
        containerRef._blob = fileRes.data;
        setDocText(contentRes.data.content || '');
        await renderBlob(fileRes.data, false);   // start in view mode
      }
    } catch (e) {
      showToast('error', `Failed to load: ${e?.response?.status ?? e.message}`);
    } finally {
      setLoading(false);
    }
  }, [id, renderBlob]);

  useEffect(() => { load(); }, [load]);

  // ── mode switch — no re-render, just toggle contentEditable ───────────────
  const switchMode = (newMode) => {
    if (newMode === mode) return;
    const iDoc = getIDoc();
    if (iDoc?.body) {
      if (newMode === 'edit') applyEditable(iDoc);
      else                    removeEditable(iDoc);
    }
    setMode(newMode);
  };

  // ── save ───────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    try {
      setSaving(true);
      // Prefer docText (backend-ordered); only fall back to iframe if user typed directly in edit mode
      const content = docText || getIframeText();
      await apiClient.post(`/papers/${id}/save_content/`, { content });
      showToast('success', 'Saved');
    } catch {
      showToast('error', 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  // ── export — save text → rerender DOCX → refresh iframe ───────────────────
  const handleExport = async () => {
    try {
      setExporting(true);
      const content = docText || getIframeText();
      await apiClient.post(`/papers/${id}/save_content/`, { content });
      const res = await apiClient.post(`/papers/${id}/rerender/`);
      if (res.data.file) {
        const fileRes = await apiClient.get(`/papers/${id}/docx_file/`, { responseType: 'blob' });
        containerRef._blob = fileRes.data;
        await renderBlob(fileRes.data, mode === 'edit');
        window.open(res.data.file, '_blank');
        showToast('success', 'DOCX exported');
      }
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  // ── AI correction → regenerate DOCX → re-render iframe ──────────────────
  const handleAiCorrect = async () => {
    const instruction = aiInput.trim();
    const currentText = docText || getIframeText();
    if (!instruction || !currentText) return;

    // Save undo snapshot before anything changes
    const iDoc = getIDoc();
    if (iDoc?.body) {
      setHistory(h => [{ instruction, prevBlob: containerRef._blob, prevText: currentText }, ...h.slice(0, 4)]);
    }

    try {
      setAiLoading(true);

      // Step 1 — ask AI to apply the correction
      setAiStatus('correcting');
      const aiRes = await apiClient.post(`/papers/${id}/ai_correct/`, {
        content: currentText,
        instruction,
      });
      const corrected = aiRes.data.corrected_content;
      setDocText(corrected);

      // Step 2 — regenerate a properly-formatted DOCX from the corrected text
      setAiStatus('rendering');
      await apiClient.post(`/papers/${id}/render_edited_docx/`, { content: corrected });

      // Step 3 — fetch the new DOCX blob and re-render the iframe
      const fileRes = await apiClient.get(`/papers/${id}/docx_file/`, { responseType: 'blob' });
      containerRef._blob = fileRes.data;
      await renderBlob(fileRes.data, mode === 'edit');

      setAiInput('');
      showToast('success', 'Correction applied — document updated');
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'AI correction failed');
    } finally {
      setAiLoading(false);
      setAiStatus('');
    }
  };

  const handleUndo = async (item) => {
    if (item.prevBlob) {
      containerRef._blob = item.prevBlob;
      await renderBlob(item.prevBlob, mode === 'edit');
    }
    if (item.prevText) setDocText(item.prevText);
    setHistory(h => h.filter(x => x !== item));
    showToast('success', 'Undone');
  };

  // ── image upload — inserts at cursor in the iframe ─────────────────────────
  const handleImageUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setImgUploading(true);
      const form = new FormData();
      form.append('image', file);
      const res = await apiClient.post(`/papers/${id}/upload_image/`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      const iDoc = getIDoc();
      if (iDoc) {
        const img = iDoc.createElement('img');
        img.src = window.location.origin + res.data.url;
        img.style.cssText = 'max-width:100%;margin:8px 0;display:block;';

        const sel = iDoc.getSelection?.();
        if (sel?.rangeCount) {
          const range = sel.getRangeAt(0);
          range.collapse(false);
          range.insertNode(img);
        } else {
          iDoc.body.appendChild(img);
        }
        setTimeout(() => resizeIframe(iDoc), 100);
      }
      showToast('success', 'Image inserted');
    } catch {
      showToast('error', 'Upload failed');
    } finally {
      setImgUploading(false);
      e.target.value = '';
    }
  };

  // ── render ─────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-200">
        <div className="text-center">
          <Loader2 className="w-10 h-10 text-blue-600 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Loading document…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-200 overflow-hidden">

      {/* ── Toolbar ── */}
      <header className="flex-none bg-white border-b border-slate-200 px-4 py-2.5 flex items-center justify-between shadow-sm z-10">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/dashboard" className="p-1.5 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors shrink-0">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-slate-900 truncate">{paper?.subject} · Class {paper?.class_name}</h1>
            <p className="text-xs text-slate-400 truncate">{paper?.pattern?.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* View / Edit toggle */}
          <div className="flex items-center bg-slate-100 rounded-lg p-0.5">
            <button
              onClick={() => switchMode('view')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                ${mode === 'view' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
            >
              <Eye className="w-3.5 h-3.5" /> Preview
            </button>
            <button
              onClick={() => switchMode('edit')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                ${mode === 'edit' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
            >
              <Pencil className="w-3.5 h-3.5" /> Edit
            </button>
          </div>

          {mode === 'edit' && (
            <>
              <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleImageUpload} />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={imgUploading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50"
              >
                {imgUploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />}
                Add Image
              </button>
            </>
          )}

          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg transition-colors disabled:opacity-50">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>

          <button onClick={handleExport} disabled={exporting}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50 shadow-sm">
            {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
            Export DOCX
          </button>
        </div>
      </header>

      {/* ── Toast ── */}
      {toast && (
        <div className={`fixed top-14 right-5 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg text-sm font-medium
          ${toast.type === 'success' ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.type === 'success' ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          {toast.msg}
          <button onClick={() => setToast(null)} className="ml-1 opacity-70 hover:opacity-100"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* ── Document area ── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {rendering && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-7 h-7 text-blue-500 animate-spin mr-2" />
            <span className="text-sm text-slate-500">Rendering document…</span>
          </div>
        )}
        {renderError && !rendering && (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <AlertCircle className="w-8 h-8 text-red-400" />
            <p className="text-sm text-red-600 font-medium">Could not render document</p>
            <p className="text-xs text-slate-400 max-w-sm text-center">{renderError}</p>
          </div>
        )}
        {/* Single container — iframe lives here for both view and edit */}
        <div ref={containerRef} className={rendering || renderError ? 'hidden' : 'block'} />
      </div>

      {/* ── AI Correction bar ── */}
      <div className="flex-none bg-slate-800 border border-slate-700 shadow-[0_-4px_20px_rgba(0,0,0,0.25)] mb-6 mx-6 rounded-2xl">
        {history.length > 0 && (
          <div className="px-4 pt-3 flex flex-wrap gap-2">
            {history.map((item, i) => (
              <div key={i} className="flex items-center gap-1.5 bg-slate-700 border border-slate-600 rounded-full px-2.5 py-1 text-xs text-slate-300">
                <span className="truncate max-w-[220px]">{item.instruction}</span>
                <button onClick={() => handleUndo(item)} title="Undo" className="shrink-0 text-slate-400 hover:text-white">
                  <RotateCcw className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3 px-4 py-3">
          <Sparkles className="w-4 h-4 text-violet-400 shrink-0" />
          <input
            type="text"
            value={aiInput}
            onChange={e => setAiInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAiCorrect(); } }}
            placeholder="Tell me your correction and I will apply it… e.g. Change Q3 marks to 5, fix spelling in Q7"
            className="flex-1 text-sm text-slate-200 placeholder-slate-500 focus:outline-none bg-transparent"
            disabled={aiLoading}
          />
          <button
            onClick={handleAiCorrect}
            disabled={aiLoading || !aiInput.trim()}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 rounded-xl transition-colors disabled:opacity-40 shrink-0 min-w-[110px] justify-center"
          >
            {aiLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {aiStatus === 'correcting' ? 'Correcting…' : aiStatus === 'rendering' ? 'Rendering…' : aiLoading ? 'Working…' : 'Apply'}
          </button>
        </div>
      </div>
    </div>
  );
}
