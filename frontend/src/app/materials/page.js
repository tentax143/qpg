'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  FileText, Upload, Search, Filter, RefreshCw, 
  Trash2, Download, BookOpen, Clock, Calendar,
  ChevronRight, ExternalLink, GraduationCap,
  Layers, MoreVertical, CheckCircle, Info,
  AlertCircle, FileDown, Eye, X, Edit,
  CheckSquare, Square, ShieldCheck, Sparkles, FolderOpen
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

const VISIBILITY_BADGE = {
  shared:        { label: 'Shared',      cls: 'bg-amber-50 text-amber-700 border-amber-200/60' },
  private:       { label: 'Private',     cls: 'bg-slate-100 text-slate-600 border-slate-200/60' },
  institutional: { label: 'All Schools', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200/60' },
};

export default function MaterialsPage() {
  const [materials, setMaterials] = useState([]);
  const [groupedMaterials, setGroupedMaterials] = useState({});
  const [classes, setClasses] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [filters, setFilters] = useState({ class_name: '', subject: '', visibility: '' });
  const [selectedItems, setSelectedItems] = useState([]);

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    groupMaterials(materials);
  }, [materials, filters]);

  const fetchData = async (isFilter = false) => {
    try {
      setLoading(true);
      
      const params = new URLSearchParams();
      params.append('page_size', '1000');
      if (isFilter) {
        if (filters.class_name) params.append('class_name', filters.class_name);
        if (filters.subject) params.append('subject', filters.subject);
      }
      
      const res = await apiClient.get(`/materials/?${params.toString()}`);
      const data = res.data.results || [];
      setMaterials(data);
      
      if (!isFilter) {
        const uniqueClasses = [...new Set(data.map(m => m.class_name))].sort((a, b) => a - b);
        const uniqueSubjects = [...new Set(data.map(m => m.subject))].sort();
        setClasses(uniqueClasses);
        setSubjects(uniqueSubjects);
      }
    } catch (err) {
      console.error(err);
      setError('Failed to load learning materials');
    } finally {
      setLoading(false);
    }
  };

  const groupMaterials = (data) => {
    const filtered = data.filter(m => {
      const matchClass = filters.class_name === '' || String(m.class_name) === filters.class_name;
      const matchSubject = filters.subject === '' || String(m.subject) === filters.subject;
      const matchVis = filters.visibility === '' || (m.visibility || 'private') === filters.visibility;
      return matchClass && matchSubject && matchVis;
    });

    const groups = {};
    filtered.forEach(m => {
      const key = `${m.class_name}_${m.subject}`;
      if (!groups[key]) {
        groups[key] = {
          class_name: m.class_name,
          subject: m.subject,
          items: []
        };
      }
      groups[key].items.push(m);
    });
    setGroupedMaterials(groups);
  };

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this material? This action cannot be undone.')) return;
    try {
      await apiClient.delete(`/materials/${id}/`);
      setSuccess('Material deleted successfully');
      setMaterials(prev => prev.filter(m => m.id !== id));
      setSelectedItems(prev => prev.filter(item => item !== id));
    } catch (err) {
      setError('Failed to delete material');
    }
  };

  const handleBulkDelete = async () => {
    if (!selectedItems.length) return;
    if (!confirm(`Are you sure you want to delete ${selectedItems.length} selected material(s)? This action cannot be undone.`)) return;
    
    try {
      setLoading(true);
      await apiClient.post('/materials/bulk-delete/', { ids: selectedItems });
      setSuccess(`${selectedItems.length} material(s) deleted successfully`);
      setMaterials(prev => prev.filter(m => !selectedItems.includes(m.id)));
      setSelectedItems([]);
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to perform bulk delete');
    } finally {
      setLoading(false);
    }
  };

  const toggleSelection = (id) => {
    setSelectedItems(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  const toggleGroupSelection = (key, items, checked) => {
    const itemIds = items.map(i => i.id);
    if (checked) {
      setSelectedItems(prev => [...new Set([...prev, ...itemIds])]);
    } else {
      setSelectedItems(prev => prev.filter(id => !itemIds.includes(id)));
    }
  };

  const toggleAllSelections = (checked) => {
    if (checked) {
      const allIds = [];
      Object.values(groupedMaterials).forEach(group => {
        group.items.forEach(item => allIds.push(item.id));
      });
      setSelectedItems(allIds);
    } else {
      setSelectedItems([]);
    }
  };

  const isGroupSelected = (items) => {
    return items.length > 0 && items.every(item => selectedItems.includes(item.id));
  };

  const isAllSelected = () => {
    const allItemsCount = Object.values(groupedMaterials).reduce((acc, group) => acc + group.items.length, 0);
    return allItemsCount > 0 && selectedItems.length === allItemsCount;
  };

  if (loading && materials.length === 0) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );

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
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">Materials & Lessons</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Manage and organize your textbook resources for AI processing.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <Link href="/materials/upload" className="px-6 py-3.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-2xl font-bold text-[13px] shadow-lg shadow-indigo-200/50 transition-all duration-300 flex items-center gap-2 hover:shadow-indigo-300/50 hover:scale-[1.02] active:scale-[0.98]">
            <Upload size={16} strokeWidth={2.5} />
            Upload Material
          </Link>
        </div>
      </div>

      <div className="max-w-7xl mx-auto">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
        {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

        {/* Filter Section */}
        <div className="relative z-[50] bg-white/80 backdrop-blur-xl rounded-[28px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-slate-200/60 p-6 md:p-8 mb-8 transition-all duration-500">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-end">
            <div className="md:col-span-6 lg:col-span-3">
              <CustomSelect
                label="Filter by Class"
                icon={Filter}
                value={filters.class_name}
                onChange={(val) => setFilters(prev => ({ ...prev, class_name: val }))}
                options={classes.map(c => ({ label: `Class ${c}`, value: c }))}
                placeholder="All Classes"
              />
            </div>

            <div className="md:col-span-6 lg:col-span-3">
              <CustomSelect
                label="Filter by Subject"
                icon={BookOpen}
                value={filters.subject}
                onChange={(val) => setFilters(prev => ({ ...prev, subject: val }))}
                options={subjects.map(s => ({ label: s, value: s }))}
                placeholder="All Subjects"
              />
            </div>

            <div className="md:col-span-6 lg:col-span-3">
              <CustomSelect
                label="Filter by Scope"
                icon={ShieldCheck}
                value={filters.visibility}
                onChange={(val) => setFilters(prev => ({ ...prev, visibility: val }))}
                options={[
                  { label: 'Shared (global)', value: 'shared' },
                  { label: 'Private to school', value: 'private' },
                  { label: 'All schools', value: 'institutional' },
                ]}
                placeholder="All Scopes"
              />
            </div>

            <div className="md:col-span-6 lg:col-span-3 flex items-center gap-3 h-[52px]">
              <button 
                onClick={() => fetchData(true)}
                className="flex-1 h-full bg-slate-900 text-white rounded-2xl font-bold text-[13px] hover:bg-slate-800 transition-all flex items-center justify-center gap-2 shadow-sm"
              >
                <Search size={16} /> 
                Search
              </button>
              <button 
                onClick={() => {
                  setFilters({ class_name: '', subject: '', visibility: '' });
                  setSelectedItems([]);
                  fetchData(false);
                } }
                className="w-[52px] h-full bg-white text-slate-500 rounded-2xl border border-slate-200 hover:bg-slate-50 hover:text-slate-900 transition-all flex items-center justify-center"
                title="Clear Filters"
              >
                <X size={18} />
              </button>
            </div>
          </div>
        </div>

        {/* Main List Area */}
        {Object.keys(groupedMaterials).length === 0 ? (
          <div className="bg-white/80 backdrop-blur-xl rounded-[28px] border border-slate-200/60 p-16 text-center shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
            <div className="w-16 h-16 bg-white rounded-2xl border border-slate-100 shadow-sm flex items-center justify-center mx-auto mb-5">
              <FolderOpen size={28} className="text-slate-300" strokeWidth={1.5} />
            </div>
            <h3 className="text-[18px] font-bold text-slate-900 mb-2 tracking-tight">No materials found</h3>
            <p className="text-slate-500 mb-8 max-w-sm mx-auto font-medium text-[13px] leading-relaxed">
              Upload textbook chapters or notes to start generating question papers with AI.
            </p>
            <Link href="/materials/upload" className="inline-flex items-center gap-2 bg-indigo-600 text-white px-6 py-3 rounded-xl font-bold text-[13px] shadow-sm hover:bg-indigo-700 transition-all active:scale-[0.98]">
              <Upload size={16} />
              Upload First Material
            </Link>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Global Actions Bar (Floating) */}
            {selectedItems.length > 0 && (
              <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-[100] animate-in slide-in-from-bottom-5 fade-in duration-300">
                <div className="bg-slate-900 text-white px-5 py-3.5 rounded-2xl shadow-2xl flex items-center gap-5 border border-slate-700/50">
                  <p className="text-[13px] font-bold tracking-wide">
                    <span className="text-indigo-400 bg-indigo-900/40 px-2 py-0.5 rounded-md mr-1">{selectedItems.length}</span> Selected
                  </p>
                  <div className="w-[1px] h-5 bg-slate-700"></div>
                  <div className="flex items-center gap-2">
                    <button 
                      onClick={handleBulkDelete}
                      className="bg-red-500/10 hover:bg-red-500 text-red-400 hover:text-white px-3.5 py-2 rounded-xl text-[12px] font-bold transition-all flex items-center gap-2"
                    >
                      <Trash2 size={14} /> Bulk Delete
                    </button>
                    <button 
                      onClick={() => setSelectedItems([])}
                      className="bg-white/10 hover:bg-white/20 text-white px-3.5 py-2 rounded-xl text-[12px] font-bold transition-all"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              </div>
            )}

            {Object.entries(groupedMaterials).map(([key, group], groupIdx) => (
              <div key={key} className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
                {/* Group Header */}
                <div className="px-6 py-4 bg-slate-50/50 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center flex-wrap gap-4">
                    <div className="flex items-center gap-2.5">
                      <GraduationCap size={16} className="text-indigo-500" strokeWidth={2} />
                      <span className="text-[13px] font-semibold text-slate-500 uppercase tracking-wider">
                        Class <span className="font-bold text-slate-900">{group.class_name}</span>
                      </span>
                    </div>
                    <div className="w-1 h-1 rounded-full bg-slate-300 hidden sm:block"></div>
                    <div className="flex items-center gap-2.5">
                      <BookOpen size={16} className="text-indigo-500" strokeWidth={2} />
                      <span className="text-[13px] font-semibold text-slate-500 uppercase tracking-wider">
                        <span className="font-bold text-slate-900">{group.subject}</span>
                      </span>
                    </div>
                    <span className="px-2.5 py-1 bg-indigo-50 text-indigo-700 text-[10px] font-bold rounded-lg border border-indigo-100/50 uppercase tracking-wider ml-2">
                      {group.items.length} lesson{group.items.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 cursor-pointer select-none group/sel">
                      <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider group-hover/sel:text-slate-700 transition-colors">Select All</span>
                      <div 
                        onClick={() => toggleGroupSelection(key, group.items, !isGroupSelected(group.items))}
                        className={`w-5 h-5 rounded-md flex items-center justify-center transition-all ${isGroupSelected(group.items) ? 'bg-indigo-600 text-white' : 'bg-white border-2 border-slate-200 group-hover/sel:border-indigo-400'}`}
                      >
                        {isGroupSelected(group.items) && <CheckSquare size={14} />}
                      </div>
                    </label>
                  </div>
                </div>

                {/* Group Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-white text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                      <tr>
                        <th className="px-6 py-4 w-12 text-center">
                          <div 
                            onClick={() => toggleAllSelections(!isAllSelected())}
                            className={`w-4 h-4 rounded flex items-center justify-center transition-all mx-auto cursor-pointer ${isAllSelected() ? 'bg-indigo-600 text-white' : 'bg-slate-100 border border-slate-200'}`}
                          >
                            {isAllSelected() && <CheckSquare size={12} />}
                          </div>
                        </th>
                        <th className="px-4 py-4 min-w-[150px]">Lesson Code</th>
                        <th className="px-4 py-4 min-w-[250px]">Title</th>
                        <th className="px-4 py-4">Type</th>
                        <th className="px-4 py-4">Scope</th>
                        <th className="px-4 py-4">Uploaded</th>
                        <th className="px-6 py-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-50 bg-white/50">
                      {group.items.map((item, idx) => (
                        <tr key={item.id} className={`hover:bg-slate-50/80 transition-colors group/row ${selectedItems.includes(item.id) ? 'bg-indigo-50/30' : ''}`}>
                          <td className="px-6 py-4 text-center">
                            <div 
                              onClick={() => toggleSelection(item.id)}
                              className={`w-4 h-4 rounded flex items-center justify-center transition-all mx-auto cursor-pointer ${selectedItems.includes(item.id) ? 'bg-indigo-600 text-white shadow-sm' : 'bg-white border border-slate-300 hover:border-indigo-400'}`}
                            >
                              {selectedItems.includes(item.id) && <CheckSquare size={12} />}
                            </div>
                          </td>
                          <td className="px-4 py-4">
                            <p className="text-[13px] font-bold text-slate-900 uppercase">{item.unit || '-'}</p>
                          </td>
                          <td className="px-4 py-4">
                            <p className="text-[13px] font-semibold text-slate-600 truncate max-w-[300px]">{item.title}</p>
                          </td>
                          <td className="px-4 py-4">
                            <span className="px-2 py-1 bg-cyan-50 text-cyan-700 text-[10px] font-bold rounded-md border border-cyan-100/50 uppercase tracking-wider">
                              {item.type_display || 'Textbook'}
                            </span>
                          </td>
                          <td className="px-4 py-4">
                            {(() => {
                              const v = VISIBILITY_BADGE[item.visibility] || VISIBILITY_BADGE.private;
                              return (
                                <span className={`px-2 py-1 text-[10px] font-bold rounded-md border uppercase tracking-wider ${v.cls}`}>
                                  {v.label}
                                </span>
                              );
                            })()}
                          </td>
                          <td className="px-4 py-4">
                            <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                              {new Date(item.uploaded_at).toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' })}
                            </p>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover/row:opacity-100 transition-opacity">
                              <Link href={`/materials/edit/${item.id}`} className="p-2 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors" title="Edit">
                                <Edit size={16} />
                              </Link>
                              <button 
                                onClick={() => handleDelete(item.id)}
                                className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" 
                                title="Delete"
                              >
                                <Trash2 size={16} />
                              </button>
                              {item.file && (
                                <a href={item.file} target="_blank" className="p-2 text-slate-400 hover:text-emerald-500 hover:bg-emerald-50 rounded-lg transition-colors" title="View Document">
                                  <Eye size={16} />
                                </a>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
