'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import {
  ArrowLeft, Save, FileDown, Loader2, ImagePlus,
  Sparkles, Send, CheckCircle, AlertCircle, X, RotateCcw, Eye, Pencil,
  History, Undo2, PanelRightClose, PanelRightOpen, Clock, RefreshCw
} from 'lucide-react';

export default function EditPaperPage() {
  const { id } = useParams();

  const [paper, setPaper]       = useState(null);
  const [loading, setLoading]   = useState(true);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState(null);
  const [saving, setSaving]     = useState(false);
  const [exporting, setExporting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [mode, setMode]         = useState('view');

  const [aiInput, setAiInput]         = useState('');
  const [aiLoading, setAiLoading]     = useState(false);
  const [aiStatus, setAiStatus]       = useState('');  // 'correcting' | 'rendering' | ''
  const [history, setHistory]         = useState([]);   // change log; newest first
  const [showLog, setShowLog]         = useState(true);  // right-side change-log panel
  const [docText, setDocText]         = useState('');   // properly-ordered text from backend

  const [imgUploading, setImgUploading] = useState(false);
  const fileRef      = useRef(null);
  const containerRef = useRef(null);   // div that holds the iframe
  const firstPersist = useRef(true);   // skip the very first change-log write (pre-hydration)

  const LOG_KEY = `paperChangeLog:${id}`;

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
        containerRef._originalBlob = fileRes.data;            // snapshot for "Restore original"
        containerRef._originalText = contentRes.data.content || '';
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

  // ── persist the change log per-paper so a reload doesn't lose it ───────────
  // Hydrate from localStorage on mount. The prev_data snapshots are JSON, so revert
  // still works after a reload (it restores server-side via /restore_data/).
  useEffect(() => {
    if (!id) return;
    try {
      const raw = localStorage.getItem(LOG_KEY);
      if (raw) setHistory(JSON.parse(raw));
    } catch { /* ignore corrupt/absent */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Save on every change (skipping the first run, which fires before hydration with []).
  useEffect(() => {
    if (!id) return;
    if (firstPersist.current) { firstPersist.current = false; return; }
    try {
      // Blobs aren't serializable — drop prevBlob; keep instruction/ts/prevData/prevText.
      const serializable = history.map(({ prevBlob, ...rest }) => rest);
      localStorage.setItem(LOG_KEY, JSON.stringify(serializable));
    } catch { /* quota or serialization issue — keep the in-memory log regardless */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, id]);

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

  // Pull the freshly-rendered DOCX + its text back into the view.
  const refreshFromServer = async () => {
    const fileRes = await apiClient.get(`/papers/${id}/docx_file/`, { responseType: 'blob' });
    containerRef._blob = fileRes.data;
    await renderBlob(fileRes.data, mode === 'edit');
    try {
      const c = await apiClient.get(`/papers/${id}/get_content/`);
      setDocText(c.data.content || '');
    } catch { /* non-fatal */ }
  };

  // ── Regenerate the whole paper from its existing config ────────────────────
  const handleRegenerate = async () => {
    if (!window.confirm(
      'Regenerate this paper from its pattern? This creates fresh questions and replaces the '
      + 'current content and any AI edits. The original pattern, class, subject and chapters are kept.'
    )) return;
    try {
      setRegenerating(true);
      await apiClient.post(`/papers/${id}/regenerate/`);
      showToast('success', 'Regenerating — this can take a minute…');

      const startedAt = Date.now();
      while (Date.now() - startedAt < 5 * 60 * 1000) {   // poll up to 5 min
        await new Promise(r => setTimeout(r, 3000));
        let st;
        try { st = (await apiClient.get(`/papers/${id}/status/`)).data; } catch { continue; }
        if (st.status === 'done') {
          setHistory([]);                                 // old edit log no longer applies
          try { localStorage.removeItem(LOG_KEY); } catch { /* ignore */ }
          await load();                                   // reload the freshly generated paper
          showToast('success', 'Paper regenerated');
          return;
        }
        if (st.status === 'failed') { showToast('error', 'Regeneration failed — try again'); return; }
      }
      showToast('error', 'Still generating — refresh in a moment to see the new paper');
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'Could not start regeneration');
    } finally {
      setRegenerating(false);
    }
  };

  // ── AI edit (targeted JSON flow) ───────────────────────────────────────────
  // Locate the question(s) the instruction refers to, edit ONLY those in paper_data,
  // splice back and re-render. Avoids the whole-paper text round-trip that truncated at
  // 4000 tokens and dropped images/structure. Falls back to the legacy text flow for
  // older papers that have no stored paper_data.
  const handleAiCorrect = async () => {
    const instruction = aiInput.trim();
    if (!instruction) return;
    const prevBlob = containerRef._blob;
    try {
      setAiLoading(true);
      setAiStatus('correcting');

      let res;
      try {
        res = await apiClient.post(`/papers/${id}/ai_edit/`, { instruction });
      } catch (err) {
        if (err?.response?.data?.error === 'no_paper_data') {
          await handleAiCorrectLegacy(instruction, prevBlob);
          return;
        }
        throw err;
      }

      // Log the change with the server-side paper_data snapshot (for revert).
      setHistory(h => [{ instruction, prevData: res.data.prev_data, prevBlob, ts: Date.now() }, ...h].slice(0, 15));

      setAiStatus('rendering');
      await refreshFromServer();

      setAiInput('');
      const n = (res.data.edited_qnums || []).join(', ');
      showToast('success', n ? `Updated question ${n}` : 'Edit applied');
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'AI edit failed');
    } finally {
      setAiLoading(false);
      setAiStatus('');
    }
  };

  // Legacy whole-paper text flow — only for papers without stored paper_data.
  const handleAiCorrectLegacy = async (instruction, prevBlob) => {
    const currentText = docText || getIframeText();
    if (!currentText) { showToast('error', 'No content to edit'); return; }
    setHistory(h => [{ instruction, prevBlob, prevText: currentText, ts: Date.now() }, ...h].slice(0, 15));
    setAiStatus('correcting');
    const aiRes = await apiClient.post(`/papers/${id}/ai_correct/`, { content: currentText, instruction });
    const corrected = aiRes.data.corrected_content;
    setDocText(corrected);
    setAiStatus('rendering');
    await apiClient.post(`/papers/${id}/render_edited_docx/`, { content: corrected });
    const fileRes = await apiClient.get(`/papers/${id}/docx_file/`, { responseType: 'blob' });
    containerRef._blob = fileRes.data;
    await renderBlob(fileRes.data, mode === 'edit');
    setAiInput('');
    showToast('success', 'Correction applied');
  };

  // Revert to the state BEFORE the change at `index` — undoes that change and every change
  // after it (history is newest-first). Restores the server-side paper_data snapshot when
  // available (JSON flow), else the visual blob (legacy flow).
  const handleRevert = async (index) => {
    const item = history[index];
    if (!item) return;
    try {
      if (item.prevData) {
        await apiClient.post(`/papers/${id}/restore_data/`, { paper_data: item.prevData });
        await refreshFromServer();
      } else if (item.prevBlob) {
        containerRef._blob = item.prevBlob;
        await renderBlob(item.prevBlob, mode === 'edit');
        if (item.prevText != null) setDocText(item.prevText);
      } else if (item.prevText != null) {
        // Legacy entry restored from localStorage (blob gone after reload) — rebuild from text.
        await apiClient.post(`/papers/${id}/render_edited_docx/`, { content: item.prevText });
        await refreshFromServer();
      }
      setHistory(h => h.slice(index + 1));   // drop this change and all newer ones
      showToast('success', history.length - index > 1 ? `Reverted ${history.length - index} changes` : 'Change reverted');
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'Revert failed');
    }
  };

  // Restore the document to before the first logged edit.
  const handleRestoreOriginal = async () => {
    if (history.length === 0) return;
    const oldest = history[history.length - 1];
    try {
      if (oldest.prevData) {
        await apiClient.post(`/papers/${id}/restore_data/`, { paper_data: oldest.prevData });
        await refreshFromServer();
      } else if (containerRef._originalBlob) {
        containerRef._blob = containerRef._originalBlob;
        await renderBlob(containerRef._originalBlob, mode === 'edit');
        setDocText(containerRef._originalText || '');
      }
      setHistory([]);
      showToast('success', 'Restored to original');
    } catch (e) {
      showToast('error', e?.response?.data?.error || 'Restore failed');
    }
  };

  const fmtTime = (ts) => {
    try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return ''; }
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

          <button onClick={handleRegenerate} disabled={regenerating || saving || exporting}
            title="Regenerate fresh questions using this paper's pattern, class, subject and chapters"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 hover:bg-amber-100 rounded-lg transition-colors disabled:opacity-50">
            {regenerating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            {regenerating ? 'Regenerating…' : 'Regenerate'}
          </button>

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

          {/* Change-log panel toggle */}
          <button onClick={() => setShowLog(v => !v)} title={showLog ? 'Hide change log' : 'Show change log'}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors border
              ${showLog ? 'bg-slate-800 text-white border-slate-800' : 'text-slate-600 bg-white border-slate-300 hover:bg-slate-50'}`}>
            {showLog ? <PanelRightClose className="w-3.5 h-3.5" /> : <PanelRightOpen className="w-3.5 h-3.5" />}
            {history.length > 0 && (
              <span className={`text-[10px] font-bold rounded-full px-1.5 ${showLog ? 'bg-white/20' : 'bg-violet-100 text-violet-700'}`}>{history.length}</span>
            )}
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

      {/* ── Main row: document (left) + change log (right) ── */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
      {/* Left column: document + AI correction bar */}
      <div className="flex-1 flex flex-col min-w-0">
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
      <div className="flex-none bg-slate-800 border border-slate-700 shadow-[0_-4px_20px_rgba(0,0,0,0.25)] mb-4 mx-4 rounded-2xl">
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
      </div>{/* end left column */}

      {/* ── Right: change log + revert ── */}
      {showLog && (
        <aside className="hidden md:flex flex-col w-72 flex-none border-l border-slate-300 bg-white">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-slate-500" />
              <h2 className="text-sm font-semibold text-slate-800">Change Log</h2>
              {history.length > 0 && <span className="text-[10px] font-bold text-slate-400">({history.length})</span>}
            </div>
            <button onClick={() => setShowLog(false)} title="Hide" className="p-1 text-slate-400 hover:text-slate-600 rounded">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {history.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center py-12 px-4 text-slate-400">
                <Sparkles className="w-6 h-6 mb-2 opacity-50" />
                <p className="text-xs font-medium">No changes yet</p>
                <p className="text-[11px] mt-1 leading-snug">AI edits you apply are logged here, newest first — each with a one-click revert.</p>
              </div>
            ) : (
              history.map((item, i) => (
                <div key={item.ts} className="rounded-xl border border-slate-200 bg-slate-50 hover:border-slate-300 transition-colors p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-bold uppercase tracking-wide text-violet-600">Edit #{history.length - i}</span>
                    <span className="flex items-center gap-1 text-[10px] text-slate-400"><Clock className="w-3 h-3" /> {fmtTime(item.ts)}</span>
                  </div>
                  <p className="text-xs text-slate-700 leading-snug mb-2 break-words">{item.instruction}</p>
                  <button
                    onClick={() => handleRevert(i)}
                    title="Revert this change and any applied after it"
                    className="flex items-center gap-1.5 w-full justify-center px-2 py-1.5 text-[11px] font-medium text-slate-600 bg-white border border-slate-300 rounded-lg hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors"
                  >
                    <Undo2 className="w-3 h-3" />
                    {i === 0 ? 'Revert this change' : `Revert to before this (${i + 1} changes)`}
                  </button>
                </div>
              ))
            )}
          </div>

          {history.length > 0 && (
            <div className="flex-none border-t border-slate-200 p-3">
              <button
                onClick={handleRestoreOriginal}
                className="flex items-center gap-1.5 w-full justify-center px-3 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Restore original
              </button>
            </div>
          )}
        </aside>
      )}
      </div>{/* end main row */}
    </div>
  );
}
