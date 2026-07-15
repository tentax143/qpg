'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Plus, FileText, Download, Trash2, Edit, ExternalLink,
  Layers, Settings, Wand2, Calculator, Info,
  Search, Filter, RefreshCw, ChevronRight, BookOpen, 
  Layout, Bookmark, User, Clock, CheckCircle, Hash,
  Hammer, MoreVertical, Copy, Activity, Zap, ClipboardList
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
      
      // Use leading slashes to be consistent with other pages
      const templatesRes = await apiClient.get('/templates/');
      const blueprintsRes = await apiClient.get('/blueprints/');

      console.log('Templates data:', templatesRes.data);
      console.log('Blueprints data:', blueprintsRes.data);

      const templateData = templatesRes.data?.results || (Array.isArray(templatesRes.data) ? templatesRes.data : []);
      const blueprintData = blueprintsRes.data?.results || (Array.isArray(blueprintsRes.data) ? blueprintsRes.data : []);
      
      setTemplates(templateData);
      setBlueprints(blueprintData);
    } catch (err) {
      if (err.response?.status !== 401 && err.response?.status !== 403) {
        console.error("Failed to fetch blueprint data", err);
      }
      // Don't show error if it's just a 404 on one of them
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
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Management</span>
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight">Blueprint Management</h1>
          <p className="text-gray-600 font-medium text-lg mt-1 tracking-tight">Manage templates and detailed structures for exam generation.</p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/blueprints/detailed-builder" className="flex items-center gap-2 bg-cyan-500 text-white px-5 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-cyan-200 hover:bg-cyan-600 hover:shadow-xl hover:shadow-cyan-300 transition-all hover:-translate-y-1 active:scale-95 duration-300">
            <Hammer size={16} />
            Detailed Builder
          </Link>
          <Link href="/blueprints/ai-create" className="flex items-center gap-2 bg-amber-500 text-white px-5 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-amber-200 hover:bg-amber-600 hover:shadow-xl hover:shadow-amber-300 transition-all hover:-translate-y-1 active:scale-95 duration-300">
            AI Create from Text
          </Link>
          <Link href="/blueprints/create-template" className="flex items-center gap-2 bg-blue-800 text-white px-5 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-blue-200 hover:bg-blue-900 hover:shadow-xl hover:shadow-blue-300 transition-all hover:-translate-y-1 active:scale-95 duration-300">
            <Plus size={16} />
            Create Template
          </Link>
          <Link href="/blueprints/create-exam" className="flex items-center gap-2 bg-[#1e293b] text-white px-5 py-3 rounded-xl font-black text-xs uppercase tracking-wider shadow-lg shadow-slate-200 hover:bg-slate-800 transition-all hover:-translate-y-0.5 active:translate-y-0">
            <ClipboardList size={16} />
            Create Blueprint
          </Link>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Blueprint Templates Section */}
      <div className="glass-card mb-12 overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold">
              <Layout size={18} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-black text-gray-900">Blueprint Templates</h2>
                <span className="px-2 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-black rounded-full">{templates.length}</span>
              </div>
              <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Reusable templates for creating blueprints</p>
            </div>
          </div>
        </div>

        <div className="p-8">
          {templates.length === 0 ? (
            <div className="text-center py-16 bg-gray-50/50 rounded-[40px] border-2 border-dashed border-gray-200">
              <div className="w-16 h-16 bg-white rounded-3xl shadow-sm flex items-center justify-center mx-auto mb-4">
                <Layout size={32} className="text-gray-300" />
              </div>
              <p className="text-gray-500 font-bold">No blueprint templates found</p>
              <Link href="/blueprints/create-template" className="mt-4 inline-flex items-center gap-2 bg-blue-600 text-white px-6 py-3 rounded-2xl font-black text-xs uppercase tracking-wider transition-all hover:bg-blue-700 active:scale-95">
                <Plus size={16} />
                Create First Template
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {templates.map((template) => (
                <div key={template.id} className="p-6 bg-white border border-gray-100 rounded-[30px] hover:border-blue-200 hover:shadow-xl hover:shadow-blue-500/5 transition-all group relative">
                  <div className="flex justify-between items-start mb-4">
                    <div className="shrink-0">
                      <h3 className="text-lg font-black text-gray-900 leading-tight mb-1 group-hover:text-blue-600 transition-colors uppercase tracking-tight">{template.name}</h3>
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">{template.class_name} • {template.subject}</p>
                    </div>
                    <div className="relative group/menu">
                      <button className="p-2 text-gray-400 hover:text-gray-900 hover:bg-gray-50 rounded-xl transition-all">
                        <MoreVertical size={18} />
                      </button>
                      <div className="absolute right-0 top-full mt-2 w-48 bg-white rounded-2xl shadow-2xl border border-gray-100 py-2 opacity-0 invisible group-hover/menu:opacity-100 group-hover/menu:visible transition-all z-20">
                        <Link href={`/blueprints/template-edit/${template.id}`} className="flex items-center gap-3 px-4 py-2 text-sm font-bold text-gray-600 hover:bg-blue-50 hover:text-blue-600">
                          <Edit size={16} /> Edit Template
                        </Link>
                        <Link href={`/blueprints/create-exam?template=${template.id}`} className="flex items-center gap-3 px-4 py-2 text-sm font-bold text-gray-600 hover:bg-emerald-50 hover:text-emerald-600">
                          <ClipboardList size={16} /> Create Blueprint
                        </Link>
                        <hr className="my-2 border-gray-50" />
                        <button 
                          onClick={() => handleDelete(template.id, 'template')}
                          className="w-full flex items-center gap-3 px-4 py-2 text-sm font-bold text-red-600 hover:bg-red-50"
                        >
                          <Trash2 size={16} /> Delete Template
                        </button>
                      </div>
                    </div>
                  </div>

                  {template.description && (
                    <p className="text-xs font-bold text-gray-700 line-clamp-2 mb-6 leading-relaxed">
                      {template.description}
                    </p>
                  )}

                  <div className="mb-6">
                    <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">Sections Structure:</p>
                    <div className="flex flex-wrap gap-2">
                      {(() => {
                        const blueprint = template.blueprint || {};
                        const sections = blueprint.sections || blueprint;
                        
                        if (Array.isArray(sections)) {
                          return sections.map((section, idx) => (
                            <span key={idx} className="px-3 py-1 bg-cyan-50 text-cyan-600 text-[10px] font-black uppercase rounded-lg border border-cyan-100">
                              {section.name || section.id || `Unit ${idx+1}`}: {section.marks}m
                            </span>
                          ));
                        } else if (sections && typeof sections === 'object') {
                          return Object.entries(sections).map(([key, section]) => {
                            if (!section || typeof section !== 'object') return null;
                            
                            // Calculate total marks for this section from subsections
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
                              <span key={key} className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase rounded-lg border border-blue-100">
                                {section.title || key}: {marks}m
                              </span>
                            );
                          });
                        }
                        return <span className="text-[10px] text-gray-500 font-bold uppercase italic">No structure defined</span>;
                      })()}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-4 border-t border-gray-50">
                    <div className="flex gap-2">
                       {template.is_default && <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 text-[8px] font-black uppercase rounded border border-emerald-100">Default</span>}
                       {!template.is_active && <span className="px-2 py-0.5 bg-gray-50 text-gray-500 text-[8px] font-black uppercase rounded border border-gray-100">Inactive</span>}
                    </div>
                    <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">{new Date(template.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Blueprints Section */}
      <div className="glass-card mb-12 overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white/50">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-emerald-600 text-white rounded-lg flex items-center justify-center font-bold">
              <FileText size={18} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-black text-gray-900">Blueprints</h2>
                <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 text-[10px] font-black rounded-full">{blueprints.length}</span>
              </div>
              <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Specific blueprints for your exams</p>
            </div>
          </div>
        </div>

        <div>
          {blueprints.length === 0 ? (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-gray-50 rounded-3xl flex items-center justify-center mx-auto mb-4 border border-gray-100">
                <FileText size={32} className="text-gray-300" />
              </div>
              <h3 className="text-lg font-black text-gray-900 mb-1">No blueprints found</h3>
              <p className="text-sm text-gray-400 font-medium mb-8">Create your first blueprint from a template!</p>
              <Link href="/blueprints/create-exam" className="inline-flex items-center gap-2 bg-emerald-600 text-white px-8 py-4 rounded-2xl font-black text-xs uppercase tracking-wider shadow-xl shadow-emerald-200 hover:bg-emerald-700 transition-all active:scale-95">
                <Plus size={18} />
                Create First Blueprint
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-gray-50/50 text-[10px] font-black uppercase text-gray-400 tracking-widest border-b border-gray-100">
                  <tr>
                    <th className="px-8 py-5">Academic Info</th>
                    <th className="px-6 py-5">Code</th>
                    <th className="px-6 py-5">Structure</th>
                    <th className="px-6 py-5">Source</th>
                    <th className="px-8 py-5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 bg-white/30">
                  {blueprints.map((blueprint) => (
                    <tr key={blueprint.id} className="hover:bg-emerald-50/20 transition-colors group">
                      <td className="px-8 py-6">
                        <div className="flex items-center gap-4">
                          <div className="w-10 h-10 bg-white border border-gray-100 rounded-xl flex items-center justify-center text-emerald-600 font-black shadow-sm group-hover:scale-110 transition-transform">
                            {blueprint.class_name}
                          </div>
                          <div>
                            <p className="font-black text-gray-900 leading-tight mb-1">{blueprint.subject}</p>
                            <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{blueprint.class_name}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-6 font-mono text-xs font-bold text-gray-400 uppercase tracking-widest">
                        {blueprint.code || '—'}
                      </td>
                      <td className="px-6 py-6">
                        <div className="flex flex-wrap gap-1">
                          {blueprint.blueprint?.sections?.map((section, idx) => (
                            <span key={idx} className="px-2 py-0.5 bg-gray-100 text-gray-500 text-[9px] font-bold uppercase rounded-lg border border-gray-200">
                              {section.name}: {section.marks}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-6 py-6">
                        <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">
                          {blueprint.template_name || 'Custom Build'}
                        </span>
                      </td>
                      <td className="px-8 py-6 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Link 
                            href={`/blueprints/edit/${blueprint.id}`}
                            className="p-2 text-gray-400 hover:text-emerald-600 hover:bg-white rounded-lg transition-all"
                            title="Edit"
                          >
                            <Edit size={18} />
                          </Link>
                          <button 
                            onClick={() => handleDelete(blueprint.id, 'blueprint')}
                            className="p-2 text-gray-400 hover:text-red-500 hover:bg-white rounded-lg transition-all"
                            title="Delete"
                          >
                            <Trash2 size={18} />
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
      <div className="glass-card p-8">
        <h3 className="text-xl font-black text-gray-900 mb-8 flex items-center gap-3">
          <Lightbulb className="text-amber-500" size={24} />
          Understanding Blueprints
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
          <div className="flex items-start gap-5 group">
            <div className="w-14 h-14 bg-blue-50 text-blue-600 rounded-3xl flex items-center justify-center shrink-0 shadow-lg shadow-blue-500/5 group-hover:scale-110 transition-transform duration-500">
              <Layout size={28} />
            </div>
            <div>
              <h4 className="font-black text-gray-900 text-lg mb-2">Blueprint Templates</h4>
              <p className="text-gray-500 font-medium text-sm leading-relaxed">
                Reusable templates that define the structure and question types for different subjects and classes. Create once, use many times.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-5 group">
            <div className="w-14 h-14 bg-emerald-50 text-emerald-600 rounded-3xl flex items-center justify-center shrink-0 shadow-lg shadow-emerald-500/5 group-hover:scale-110 transition-transform duration-500">
              <FileText size={28} />
            </div>
            <div>
              <h4 className="font-black text-gray-900 text-lg mb-2">Blueprints</h4>
              <p className="text-gray-500 font-medium text-sm leading-relaxed">
                Specific blueprints created from templates for particular exams. Can be customized for specific weightage and chapter requirements.
              </p>
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
