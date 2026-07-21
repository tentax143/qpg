'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Plus, FileText, Download, Trash2, Edit, ExternalLink,
  Layers, Settings, Wand2, Calculator, Info,
  Search, Filter, RefreshCw, ChevronRight, BookOpen, 
  Layout, Bookmark, User, Clock, CheckCircle, Hash,
  Hammer, MoreVertical, Copy, Activity, Zap, ClipboardList,
  Sparkles, ArrowRight
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function BlueprintsPage() {
  const [templates, setTemplates] = useState([]);
  const [blueprints, setBlueprints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const templatesRes = await apiClient.get('/templates/');
      const blueprintsRes = await apiClient.get('/blueprints/');

      const templateData = templatesRes.data?.results || (Array.isArray(templatesRes.data) ? templatesRes.data : []);
      const blueprintData = blueprintsRes.data?.results || (Array.isArray(blueprintsRes.data) ? blueprintsRes.data : []);
      
      setTemplates(templateData);
      setBlueprints(blueprintData);
    } catch (err) {
      if (err.response?.status !== 401 && err.response?.status !== 403) {
        console.error("Failed to fetch blueprint data", err);
      }
      if (err.response?.status === 404) {
        console.warn("One of the endpoints was not found");
      } else if (err.response?.status !== 401 && err.response?.status !== 403) {
        setError('Failed to load blueprint management data. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id, type) => {
    if (!confirm(`Are you sure you want to delete this ${type}?`)) return;
    try {
      const endpoint = type === 'template' ? 'templates/' : 'blueprints/';
      await apiClient.delete(`${endpoint}${id}/`);
      setSuccess(`${type.charAt(0).toUpperCase() + type.slice(1)} deleted successfully`);
      fetchData();
    } catch (err) {
      setError(`Failed to delete ${type}`);
    }
  };

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full pb-12 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Management</span>
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Blueprint Builder</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Manage templates and detailed structures for precise exam generation.</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/blueprints/ai-create" className="px-5 py-3 bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-amber-200/50 hover:shadow-xl hover:shadow-amber-300/50 hover:-translate-y-0.5 active:scale-[0.98] transition-all flex items-center gap-2">
            <Wand2 size={16} strokeWidth={2.5} />
            AI Create
          </Link>
          <Link href="/blueprints/detailed-builder" className="px-5 py-3 bg-gradient-to-r from-cyan-500 to-blue-500 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-cyan-200/50 hover:shadow-xl hover:shadow-cyan-300/50 hover:-translate-y-0.5 active:scale-[0.98] transition-all flex items-center gap-2">
            <Hammer size={16} strokeWidth={2.5} />
            Detailed Builder
          </Link>
          <Link href="/blueprints/create-template" className="px-5 py-3 bg-slate-900 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-slate-200 hover:-translate-y-0.5 active:scale-[0.98] transition-all flex items-center gap-2">
            <Plus size={16} strokeWidth={2.5} />
            Create Template
          </Link>
          <Link href="/blueprints/create-exam" className="px-5 py-3 bg-white border border-slate-200 text-slate-700 rounded-2xl font-bold text-[13px] hover:bg-slate-50 hover:text-indigo-600 hover:border-indigo-200 transition-all active:scale-[0.98] flex items-center gap-2">
            <ClipboardList size={16} strokeWidth={2} />
            Create Blueprint
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto space-y-8">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
        {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

        {/* Blueprint Templates Section */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
                <Layout size={22} strokeWidth={2} />
              </div>
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Blueprint Templates</h2>
                  <span className="px-2.5 py-1 bg-slate-100 text-slate-600 text-[11px] font-bold rounded-lg">{templates.length}</span>
                </div>
                <p className="text-[12px] text-slate-500 font-medium">Reusable templates for creating blueprints</p>
              </div>
            </div>
          </div>

          <div className="p-8">
            {templates.length === 0 ? (
              <div className="text-center py-16 bg-slate-50/50 rounded-2xl border-2 border-dashed border-slate-200">
                <div className="w-16 h-16 bg-white rounded-2xl shadow-sm border border-slate-100 flex items-center justify-center mx-auto mb-4">
                  <Layout size={24} className="text-slate-300" strokeWidth={1.5} />
                </div>
                <h3 className="text-[16px] font-bold text-slate-900 mb-1">No templates found</h3>
                <p className="text-[13px] text-slate-500 mb-6">Create a blueprint template to standardize your exams.</p>
                <Link href="/blueprints/create-template" className="inline-flex items-center gap-2 bg-indigo-600 text-white px-6 py-3 rounded-xl font-semibold text-[13px] shadow-sm hover:bg-indigo-700 transition-all">
                  <Plus size={16} />
                  Create First Template
                </Link>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {templates.map((template) => (
                  <div key={template.id} className="p-6 bg-white border border-slate-200 rounded-2xl hover:border-indigo-300 hover:shadow-md transition-all group relative">
                    <div className="flex justify-between items-start mb-4">
                      <div className="shrink-0 max-w-[85%]">
                        <h3 className="text-[16px] font-bold text-slate-900 leading-tight mb-1 truncate group-hover:text-indigo-600 transition-colors">{template.name}</h3>
                        <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest truncate">{template.class_name} • {template.subject}</p>
                      </div>
                      <div className="relative group/menu">
                        <button className="w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-900 hover:bg-slate-50 rounded-lg transition-all">
                          <MoreVertical size={16} />
                        </button>
                        <div className="absolute right-0 top-full mt-1 w-48 bg-white rounded-xl shadow-xl border border-slate-100 py-1.5 opacity-0 invisible group-hover/menu:opacity-100 group-hover/menu:visible transition-all z-20">
                          <Link href={`/blueprints/template-edit/${template.id}`} className="flex items-center gap-3 px-4 py-2 text-[13px] font-semibold text-slate-600 hover:bg-slate-50 hover:text-indigo-600">
                            <Edit size={14} /> Edit Template
                          </Link>
                          <Link href={`/blueprints/create-exam?template=${template.id}`} className="flex items-center gap-3 px-4 py-2 text-[13px] font-semibold text-slate-600 hover:bg-slate-50 hover:text-emerald-600">
                            <ClipboardList size={14} /> Create Blueprint
                          </Link>
                          <div className="h-px bg-slate-100 my-1"></div>
                          <button 
                            onClick={() => handleDelete(template.id, 'template')}
                            className="w-full flex items-center gap-3 px-4 py-2 text-[13px] font-semibold text-red-600 hover:bg-red-50"
                          >
                            <Trash2 size={14} /> Delete Template
                          </button>
                        </div>
                      </div>
                    </div>

                    {template.description && (
                      <p className="text-[12px] text-slate-500 font-medium line-clamp-2 mb-5">
                        {template.description}
                      </p>
                    )}

                    <div className="mb-6">
                      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Sections Structure:</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(() => {
                          const blueprint = template.blueprint || {};
                          const sections = blueprint.sections || blueprint;
                          
                          if (Array.isArray(sections)) {
                            return sections.map((section, idx) => (
                              <span key={idx} className="px-2.5 py-1 bg-indigo-50 text-indigo-700 text-[10px] font-bold rounded-md border border-indigo-100/50">
                                {section.name || section.id || `Unit ${idx+1}`}: {section.marks}m
                              </span>
                            ));
                          } else if (sections && typeof sections === 'object') {
                            return Object.entries(sections).map(([key, section]) => {
                              if (!section || typeof section !== 'object') return null;
                              let marks = 0;
                              if (section.marks) {
                                marks = section.marks;
                              } else if (section.subsections && typeof section.subsections === 'object') {
                                marks = Object.values(section.subsections).reduce((sum, m) => sum + (typeof m === 'number' ? m : 0), 0);
                              } else if (typeof section === 'number') {
                                marks = section;
                              }
                              if (marks === 0 && !section.subsections) return null;
                              return (
                                <span key={key} className="px-2.5 py-1 bg-slate-100 text-slate-600 text-[10px] font-bold rounded-md border border-slate-200/60">
                                  {section.title || key}: {marks}m
                                </span>
                              );
                            });
                          }
                          return <span className="text-[11px] text-slate-400 font-semibold italic">No structure defined</span>;
                        })()}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                      <div className="flex gap-1.5">
                         {template.is_default && <span className="px-2 py-0.5 bg-emerald-50 text-emerald-700 text-[9px] font-bold uppercase tracking-wider rounded-md">Default</span>}
                         {!template.is_active && <span className="px-2 py-0.5 bg-slate-100 text-slate-500 text-[9px] font-bold uppercase tracking-wider rounded-md">Inactive</span>}
                      </div>
                      <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                        {new Date(template.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Blueprints Section */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center border border-emerald-100">
                <FileText size={22} strokeWidth={2} />
              </div>
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Active Blueprints</h2>
                  <span className="px-2.5 py-1 bg-slate-100 text-slate-600 text-[11px] font-bold rounded-lg">{blueprints.length}</span>
                </div>
                <p className="text-[12px] text-slate-500 font-medium">Specific blueprints created for exams</p>
              </div>
            </div>
          </div>

          <div>
            {blueprints.length === 0 ? (
              <div className="text-center py-16">
                <div className="w-16 h-16 bg-slate-50 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-slate-100">
                  <FileText size={24} className="text-slate-300" strokeWidth={1.5} />
                </div>
                <h3 className="text-[16px] font-bold text-slate-900 mb-1">No blueprints found</h3>
                <p className="text-[13px] text-slate-500 mb-6">Create your first blueprint from a template!</p>
                <Link href="/blueprints/create-exam" className="inline-flex items-center gap-2 bg-emerald-600 text-white px-6 py-3 rounded-xl font-semibold text-[13px] shadow-sm hover:bg-emerald-700 transition-all">
                  <Plus size={16} />
                  Create First Blueprint
                </Link>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-slate-50/50 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                    <tr>
                      <th className="px-8 py-4">Academic Info</th>
                      <th className="px-6 py-4">Code</th>
                      <th className="px-6 py-4">Structure</th>
                      <th className="px-6 py-4">Source</th>
                      <th className="px-8 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50 bg-white/50">
                    {blueprints.map((blueprint) => (
                      <tr key={blueprint.id} className="hover:bg-slate-50/50 transition-colors group">
                        <td className="px-8 py-5">
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 bg-slate-50 border border-slate-100 rounded-xl flex items-center justify-center text-slate-700 font-bold shadow-sm">
                              {blueprint.class_name}
                            </div>
                            <div>
                              <p className="font-bold text-slate-900 leading-tight mb-1">{blueprint.subject}</p>
                              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest">Class {blueprint.class_name}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-5 font-mono text-[12px] font-semibold text-slate-500 uppercase tracking-wider">
                          {blueprint.code || '—'}
                        </td>
                        <td className="px-6 py-5">
                          <div className="flex flex-wrap gap-1.5">
                            {blueprint.blueprint?.sections?.map((section, idx) => (
                              <span key={idx} className="px-2 py-0.5 bg-slate-100 text-slate-600 text-[10px] font-bold rounded-md border border-slate-200/60">
                                {section.name}: {section.marks}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-6 py-5">
                          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                            {blueprint.template_name || 'Custom Build'}
                          </span>
                        </td>
                        <td className="px-8 py-5 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <Link 
                              href={`/blueprints/edit/${blueprint.id}`}
                              className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                              title="Edit"
                            >
                              <Edit size={16} />
                            </Link>
                            <button 
                              onClick={() => handleDelete(blueprint.id, 'blueprint')}
                              className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                              title="Delete"
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Help Section */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-amber-50 border border-amber-100 flex items-center justify-center">
              <Lightbulb size={20} className="text-amber-500" strokeWidth={2} />
            </div>
            <h3 className="text-[18px] font-bold text-slate-900 tracking-tight">Understanding Blueprints</h3>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center shrink-0">
                <Layout size={20} strokeWidth={2} />
              </div>
              <div>
                <h4 className="font-bold text-slate-900 text-[15px] mb-1.5">Blueprint Templates</h4>
                <p className="text-slate-500 font-medium text-[13px] leading-relaxed">
                  Reusable templates that define the structure and question types for different subjects and classes. Create once, use many times.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-xl flex items-center justify-center shrink-0">
                <FileText size={20} strokeWidth={2} />
              </div>
              <div>
                <h4 className="font-bold text-slate-900 text-[15px] mb-1.5">Blueprints</h4>
                <p className="text-slate-500 font-medium text-[13px] leading-relaxed">
                  Specific blueprints created from templates for particular exams. Can be customized for specific weightage and chapter requirements.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Internal Lightbulb icon for the footer
function Lightbulb({ size, className }) {
  return (
    <svg 
      width={size} 
      height={size} 
      viewBox="0 0 24 24" 
      fill="none" 
      stroke="currentColor" 
      strokeWidth="3" 
      strokeLinecap="round" 
      strokeLinejoin="round" 
      className={className}
    >
      <path d="M15 14c.2-0.1.3-0.3.3-0.5 0.5-1.1 1.2-2.1 2.1-2.8a5 5 0 0 0 1.6-3.7 8 8 0 1 0-16 0 5 5 0 0 0 1.6 3.7c0.9.7 1.6 1.7 2.1 2.8 0 .2.1.4.3.5m4 4h4m-4 4h4m-6-12a3 3 0 1 1 6 0" />
    </svg>
  );
}
