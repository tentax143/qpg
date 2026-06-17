'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  FileText, Upload, Search, Filter, RefreshCw, 
  Trash2, Download, BookOpen, Clock, Calendar,
  ChevronRight, ExternalLink, GraduationCap,
  Layers, MoreVertical, CheckCircle, Info,
  AlertCircle, FileDown, Eye, X, Edit,
  CheckSquare, Square
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import CustomSelect from '@/components/CustomSelect';

export default function MaterialsPage() {
  const [materials, setMaterials] = useState([]);
  const [groupedMaterials, setGroupedMaterials] = useState({});
  const [classes, setClasses] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [filters, setFilters] = useState({ class_name: '', subject: '' });
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
      
      // Build query params
      const params = new URLSearchParams();
      params.append('page_size', '1000');
      if (isFilter) {
        if (filters.class_name) params.append('class_name', filters.class_name);
        if (filters.subject) params.append('subject', filters.subject);
      }
      
      const res = await apiClient.get(`/materials/?${params.toString()}`);
      const data = res.data.results || [];
      setMaterials(data);
      
      // Only update filter options on initial load to avoid options disappearing when filtered
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
      return matchClass && matchSubject;
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
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-2 mb-20 px-4">
      {/* Header */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-8 mb-12">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-white/80 backdrop-blur-md shadow-2xl shadow-blue-500/10 border border-white/50 rounded-2xl flex items-center justify-center group-hover:rotate-12 transition-all duration-500">
            <BookOpen size={28} className="text-blue-600" />
          </div>
          <div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight">Materials & Lessons</h1>
            <p className="text-gray-500 font-medium">Manage and organize your textbook resources</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <Link href="/materials/upload" className="flex items-center gap-2 bg-blue-600 text-white px-6 py-4 rounded-2xl font-bold text-sm tracking-tight hover:bg-blue-700 transition-all duration-300 shadow-xl shadow-blue-200 hover:shadow-blue-300 hover:-translate-y-1 active:scale-95">
            <Upload size={18} className="animate-bounce" />
            Upload Material
          </Link>
        </div>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

      {/* Filter Section */}
      <div className="bg-white/80 backdrop-blur-xl rounded-[32px] shadow-2xl shadow-blue-500/5 border border-white/20 p-8 mb-12 group transition-all duration-500 hover:shadow-blue-500/10">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-end">
          <div className="md:col-span-12 lg:col-span-5">
            <CustomSelect
              label="Filter by Class"
              icon={Filter}
              value={filters.class_name}
              onChange={(val) => setFilters(prev => ({ ...prev, class_name: val }))}
              options={classes.map(c => ({ label: `Class ${c}`, value: c }))}
              placeholder="All Classes"
            />
          </div>

          <div className="md:col-span-12 lg:col-span-4">
            <CustomSelect
              label="Filter by Subject"
              icon={BookOpen}
              value={filters.subject}
              onChange={(val) => setFilters(prev => ({ ...prev, subject: val }))}
              options={subjects.map(s => ({ label: s, value: s }))}
              placeholder="All Subjects"
            />
          </div>

          <div className="md:col-span-12 lg:col-span-3 flex items-center gap-3">
            <button 
              onClick={() => fetchData(true)}
              className="flex-1 bg-gray-900 text-white px-6 py-4 rounded-2xl font-bold text-sm tracking-tight hover:bg-black transition-all duration-300 flex items-center justify-center gap-2 group hover:-translate-y-1 active:scale-95 shadow-xl shadow-gray-200/50"
            >
              <Search size={18} className="group-hover:scale-110 transition-transform" /> 
              Search
            </button>
            <button 
              onClick={() => {
                setFilters({ class_name: '', subject: '' });
                setSelectedItems([]);
                fetchData(false);
              } }
              className="bg-white text-gray-700 p-4 rounded-2xl font-bold text-sm tracking-tight hover:bg-gray-50 border border-gray-100 transition-all duration-300 flex items-center justify-center gap-2 hover:-translate-y-1 active:scale-95 shadow-lg shadow-gray-100/50"
              title="Clear Filters"
            >
              <X size={20} />
            </button>
          </div>
        </div>
      </div>

      {/* Main List Area */}
      {Object.keys(groupedMaterials).length === 0 ? (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-20 text-center hover:shadow-xl transition-shadow duration-500">
          <div className="w-16 h-16 bg-gray-50 rounded-2xl border border-gray-100 flex items-center justify-center mx-auto mb-4 animate-bounce-slow">
            <FileText size={32} className="text-gray-400" />
          </div>
          <h3 className="text-xl font-black text-gray-900 mb-2">No materials found</h3>
          <p className="text-gray-600 mb-8 max-w-sm mx-auto font-medium">Upload textbook chapters or notes to start generating question papers with AI.</p>
          <Link href="/materials/upload" className="inline-flex items-center gap-2 bg-blue-600 text-white px-8 py-3.5 rounded-xl font-black text-xs uppercase tracking-widest transition-all duration-300 shadow-xl shadow-blue-200 hover:shadow-blue-300 hover:-translate-y-1 active:scale-95">
            <Upload size={18} />
            Upload First Material
          </Link>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Global Actions */}
          {selectedItems.length > 0 && (
            <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-5">
              <div className="bg-gray-900 text-white px-6 py-4 rounded-2xl shadow-2xl flex items-center gap-6">
                <p className="text-sm font-bold tracking-tight">
                  <span className="text-blue-400">{selectedItems.length}</span> Material(s) Selected
                </p>
                <div className="w-[1px] h-6 bg-gray-700"></div>
                <div className="flex items-center gap-2">
                  <button 
                    onClick={handleBulkDelete}
                    className="bg-red-500/10 hover:bg-red-500 text-red-400 hover:text-white px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2"
                  >
                    <Trash2 size={14} /> Bulk Delete
                  </button>
                  <button 
                    onClick={() => setSelectedItems([])}
                    className="bg-white/10 hover:bg-white/20 text-white px-4 py-2 rounded-xl text-xs font-bold transition-all"
                  >
                    Clear Selection
                  </button>
                </div>
              </div>
            </div>
          )}

          {Object.entries(groupedMaterials).map(([key, group], groupIdx) => (
            <div key={key} className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden group/card">
              <div className="p-4 bg-gray-50/50 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <GraduationCap size={18} className="text-blue-500" />
                    <span className="text-sm font-black text-gray-900 uppercase">Class: <span className="text-blue-600">{group.class_name}</span></span>
                  </div>
                  <div className="w-[1px] h-4 bg-gray-200"></div>
                  <div className="flex items-center gap-2">
                    <BookOpen size={18} className="text-blue-500" />
                    <span className="text-sm font-black text-gray-900 uppercase">Subject: <span className="text-blue-600">{group.subject}</span></span>
                  </div>
                  <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-black rounded-full border border-blue-200 uppercase">
                    {group.items.length} lesson{group.items.length !== 1 ? 's' : ''}
                  </span>
                </div>
                
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <span className="text-[10px] font-black text-gray-600 uppercase tracking-widest">Select All</span>
                    <div 
                      onClick={() => toggleGroupSelection(key, group.items, !isGroupSelected(group.items))}
                      className={`w-5 h-5 rounded flex items-center justify-center transition-all ${isGroupSelected(group.items) ? 'bg-[#1e293b] text-white' : 'bg-white border-2 border-gray-200'}`}
                    >
                      {isGroupSelected(group.items) && <CheckSquare size={14} />}
                    </div>
                  </label>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="bg-white text-[10px] font-black uppercase text-gray-500 tracking-widest border-b border-gray-50">
                    <tr>
                      <th className="px-6 py-4 w-12 text-center">
                        <div 
                          onClick={() => toggleAllSelections(!isAllSelected())}
                          className={`w-4 h-4 rounded flex items-center justify-center transition-all mx-auto cursor-pointer ${isAllSelected() ? 'bg-[#1e293b] text-white' : 'bg-white border border-gray-300'}`}
                        >
                          {isAllSelected() && <CheckSquare size={12} />}
                        </div>
                      </th>
                      <th className="px-4 py-4 w-12 text-center">#</th>
                      <th className="px-4 py-4 min-w-[200px]">Lesson/Chapter Name</th>
                      <th className="px-4 py-4 min-w-[200px]">Title</th>
                      <th className="px-4 py-4">Type</th>
                      <th className="px-4 py-4">Uploaded</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50 bg-white">
                    {group.items.map((item, idx) => (
                      <tr key={item.id} className={`hover:bg-gray-50/50 transition-colors group/row ${selectedItems.includes(item.id) ? 'bg-slate-50' : ''}`}>
                        <td className="px-6 py-4 text-center">
                          <div 
                            onClick={() => toggleSelection(item.id)}
                            className={`w-4 h-4 rounded flex items-center justify-center transition-all mx-auto cursor-pointer ${selectedItems.includes(item.id) ? 'bg-[#1e293b] text-white shadow-lg' : 'bg-white border border-gray-300'}`}
                          >
                            {selectedItems.includes(item.id) && <CheckSquare size={12} />}
                          </div>
                        </td>
                        <td className="px-4 py-4 text-center text-xs font-black text-gray-500">
                          {idx + 1}
                        </td>
                        <td className="px-4 py-4">
                          <p className="text-sm font-black text-gray-900 uppercase tracking-tight">{item.unit || '-'}</p>
                        </td>
                        <td className="px-4 py-4">
                          <p className="text-sm font-bold text-gray-500 truncate max-w-[250px]">{item.title}</p>
                        </td>
                        <td className="px-4 py-4">
                          <span className="px-2.5 py-1 bg-cyan-50 text-cyan-700 text-[9px] font-black rounded-lg border border-cyan-100 uppercase">
                            {item.type_display || 'Textbook'}
                          </span>
                        </td>
                        <td className="px-4 py-4">
                          <p className="text-[11px] font-bold text-gray-600 uppercase tracking-tight">
                            {new Date(item.uploaded_at).toLocaleDateString('en-US', { month: 'short', day: '2-digit', year: 'numeric' })}
                          </p>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <div className="flex items-center justify-end gap-1 opacity-0 group-hover/row:opacity-100 transition-opacity">
                            <Link href={`/materials/edit/${item.id}`} className="p-2 text-gray-400 hover:text-blue-600 hover:bg-white rounded-lg transition-all" title="Edit">
                              <Edit size={16} />
                            </Link>
                            <button 
                              onClick={() => handleDelete(item.id)}
                              className="p-2 text-gray-400 hover:text-red-500 hover:bg-white rounded-lg transition-all" 
                              title="Delete"
                            >
                              <Trash2 size={16} />
                            </button>
                            {item.file && (
                              <a href={item.file} target="_blank" className="p-2 text-gray-400 hover:text-emerald-500 hover:bg-white rounded-lg transition-all" title="View PDF">
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
  );
}
