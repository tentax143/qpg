'use client';

import { useState, useEffect, use } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import { 
  Save, FileText, ArrowLeft, Loader2, RefreshCw, 
  CheckCircle, AlertTriangle, FileDown 
} from 'lucide-react';

export default function EditPaperPage() {
  const params = useParams();
  const id = params?.id;
  const router = useRouter();
  
  const [content, setContent] = useState('');
  const [paper, setPaper] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    fetchPaperData();
  }, [id]);

  const fetchPaperData = async () => {
    try {
      setLoading(true);
      // Fetch paper details to get title/subject etc
      const paperRes = await apiClient.get(`/papers/${id}/`);
      setPaper(paperRes.data);

      // Fetch content
      const contentRes = await apiClient.get(`/papers/${id}/get_content/`);
      setContent(contentRes.data.content || '');
    } catch (err) {
      setError('Failed to load paper content');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (silent = false) => {
    try {
      setSaving(true);
      if (!silent) setSuccess(null);
      setError(null);
      
      await apiClient.post(`/papers/${id}/save_content/`, { content });
      
      if (!silent) {
        setSuccess('Changes saved successfully');
        setTimeout(() => setSuccess(null), 3000);
      }
      return true;
    } catch (err) {
      setError('Failed to save changes');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    try {
      if (!confirm('This will overwrite the existing PDF with your text changes. Continue?')) {
        return;
      }
      
      setRegenerating(true);
      setError(null);
      setSuccess(null);

      // Save first
      const saved = await handleSave(true);
      if (!saved) {
        throw new Error('Failed to save before generating');
      }

      await apiClient.post(`/papers/${id}/regenerate_pdf/`);
      
      setSuccess('PDF regenerated successfully! Redirecting...');
      setTimeout(() => {
        router.push('/papers');
      }, 2000);
    } catch (err) {
      setError(err?.response?.data?.error || 'Failed to regenerate PDF');
    } finally {
      setRegenerating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen p-4">
        <Loader2 className="w-12 h-12 text-blue-600 animate-spin mb-4" />
        <h2 className="text-xl font-semibold text-gray-700">Loading Paper Content...</h2>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm z-10">
        <div className="flex items-center gap-4">
          <Link 
            href="/papers"
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-full transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-800">
              Edit Paper: {paper?.title || 'Untitled'}
            </h1>
            <p className="text-sm text-gray-500">
              {paper?.subject} • {paper?.class_name} • {paper?.total_marks} Marks
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-400 mr-2 hidden md:block">
            <span className="flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" />
              Markdown/Text format supported
            </span>
          </div>
          
          <button
            onClick={() => handleSave(false)}
            disabled={saving || regenerating}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save Draft
          </button>
          
          <button
            onClick={handleRegenerate}
            disabled={saving || regenerating}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 shadow-sm transition-colors"
          >
            {regenerating ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FileDown className="w-4 h-4" />
            )}
            Save & Regenerate PDF
          </button>
        </div>
      </header>

      {/* Editor Area */}
      <main className="flex-1 overflow-hidden flex flex-col relative">
        {(error || success) && (
          <div className="absolute top-4 left-1/2 transform -translate-x-1/2 w-full max-w-lg z-20 px-4">
            {error && <ErrorAlert message={error} onClose={() => setError(null)} />}
            {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}
          </div>
        )}

        <div className="flex-1 p-6 overflow-hidden">
          <div className="h-full bg-white rounded-xl shadow-lg border border-gray-200 flex flex-col">
            <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 flex justify-between items-center text-xs text-gray-500">
              <span>Edit content below. Be careful with formatting.</span>
              <span>{content.length} characters</span>
            </div>
            
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="flex-1 w-full p-6 resize-none focus:outline-none focus:ring-0 font-mono text-sm leading-relaxed text-gray-800"
              placeholder="Paper content will appear here..."
              spellCheck="false"
            />
          </div>
        </div>
      </main>
    </div>
  );
}
