'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { 
  Plus, FileText, Download, Clock, CheckCircle, 
  ChevronRight, Trash2, RefreshCw,
  Settings, Server, Database, Activity, ShieldCheck,
  Upload, Layers, Briefcase, FileSignature, Sparkles, ArrowRight, Zap
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function DashboardPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState(null);
  const [stats, setStats] = useState({
    total_papers: 0,
    this_month: 0,
    success_rate: '0%',
    recent_activity: []
  });
  const [selectedPapers, setSelectedPapers] = useState([]);
  const [modelSource, setModelSource] = useState('local');
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const pollingIntervalRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    const userData = localStorage.getItem('user');
    
    if (!token) {
      router.push('/');
      return;
    }

    if (userData) setUser(JSON.parse(userData));
    fetchDashboardData();
    setLoading(false);

    // Cleanup interval on unmount
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

  // Set up polling when there are generating papers
  useEffect(() => {
    const hasGeneratingPapers = stats.recent_activity.some(p => 
      p.status === 'generating' || p.status === 'queued'
    );

    if (hasGeneratingPapers && !pollingIntervalRef.current) {
      // Start polling every 3 seconds
      pollingIntervalRef.current = setInterval(() => {
        fetchDashboardData();
      }, 3000);
    } else if (!hasGeneratingPapers && pollingIntervalRef.current) {
      // Stop polling when no papers are generating
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }

    return () => {
      if (pollingIntervalRef.current && !hasGeneratingPapers) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [stats.recent_activity]);

  const fetchDashboardData = async () => {
    try {
      const papersRes = await apiClient.get('/papers/?page_size=100');
      const papers = papersRes.data.results || [];
      
      const total = papers.length;
      const now = new Date();
      const firstDayOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      const thisMonth = papers.filter(p => new Date(p.created_at) >= firstDayOfMonth).length;
      const successCount = papers.filter(p => p.status === 'done').length;
      const successRate = total > 0 ? Math.round((successCount / total) * 100) : 0;

      setStats({
        total_papers: total,
        this_month: thisMonth,
        success_rate: `${successRate}%`,
        recent_activity: papers.slice(0, 10)
      });
      // Also fetch current model config
      try {
        const configRes = await apiClient.get('/config/model-choice/');
        if (configRes.data.model_choice) {
          setModelSource(configRes.data.model_choice);
        }
      } catch (e) {
        console.warn("Could not fetch model config", e);
      }
    } catch (err) {
      console.error("Failed to fetch dashboard data", err);
      if (err.response?.status === 401) {
        localStorage.removeItem('authToken');
        router.push('/');
      }
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this paper?')) return;
    try {
      await apiClient.delete(`/papers/${id}/`);
      setSuccess('Paper deleted successfully');
      fetchDashboardData();
    } catch (err) {
      setError('Failed to delete paper');
    }
  };

  const handleBulkDelete = async () => {
    if (!confirm(`Are you sure you want to delete ${selectedPapers.length} papers?`)) return;
    try {
      await apiClient.post('/papers/bulk-delete/', { ids: selectedPapers });
      setSuccess(`${selectedPapers.length} papers deleted`);
      setSelectedPapers([]);
      fetchDashboardData();
    } catch (err) {
      setError('Bulk delete failed');
    }
  };

  const handleRetry = async (id) => {
    try {
      await apiClient.post(`/papers/${id}/retry/`);
      setSuccess('Generation retried');
      fetchDashboardData();
    } catch (err) {
      setError('Retry failed');
    }
  };

  const handleToggleModel = async () => {
    const newSource = modelSource === 'local' ? 'aws' : 'local';
    
    try {
      // Use standard JSON API endpoint for configuration
      await apiClient.post('/config/model-choice/', { model_choice: newSource });
      
      setModelSource(newSource);
      setSuccess(`Model choice updated to ${newSource === 'aws' ? 'AWS' : 'Local'}`);
    } catch (err) {
      console.error("Failed to update model choice", err);
      // Revert UI state on failure
      setError("Failed to update AI configuration.");
    }
  };

  const toggleSelectPaper = (id) => {
    setSelectedPapers(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedPapers.length === stats.recent_activity.length) {
      setSelectedPapers([]);
    } else {
      setSelectedPapers(stats.recent_activity.map(p => p.id));
    }
  };

  if (loading) return (
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full relative py-8 px-2">
      {/* Header Section */}
      <div className="mb-12 animate-fade-in">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_12px_rgba(16,185,129,0.5)]"></div>
          <span className="text-xs font-black text-gray-400 uppercase tracking-[0.2em]">Assessment Dashboard</span>
        </div>
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6">
          <div>
            <h1 className="text-4xl lg:text-5xl font-black text-gray-900 leading-tight tracking-tight mb-2">
              Question Paper Management
            </h1>
            <p className="text-gray-500 font-medium text-base tracking-tight">
              Generate, manage, and track your AI-powered assessment papers
            </p>
          </div>
        </div>
      </div>

      {/* Stats Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
        {[
          { label: 'Total Papers', value: stats.total_papers, icon: FileText, color: 'text-blue-600', bg: 'bg-blue-500/10', sub: 'Lifetime generations' },
          { label: 'This Month', value: stats.this_month, icon: Clock, color: 'text-indigo-600', bg: 'bg-indigo-500/10', sub: 'New this month' },
        ].map((stat, i) => (
          <div 
            key={i} 
            className="bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-lg shadow-blue-500/5 border border-white/40 group relative overflow-hidden transition-all duration-500 hover:shadow-xl hover:shadow-blue-500/10 hover:-translate-y-0.5 active:scale-[0.98] animate-slide-up"
            style={{ animationDelay: `${i * 100}ms` }}
          >
            {/* Animated background blob */}
            <div className="absolute -right-8 -top-8 w-32 h-32 bg-gradient-to-br from-blue-400/10 to-transparent rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-700 blur-2xl"></div>
            
            <div className="relative z-10 flex justify-between items-start">
              <div className="space-y-2">
                <p className="text-gray-400 font-black text-[10px] uppercase tracking-[0.2em]">{stat.label}</p>
                <h3 className="text-5xl font-black text-gray-900 tracking-tight">
                  {stat.value}
                </h3>
                <p className="text-xs font-bold text-gray-400 tracking-tight pt-1">{stat.sub}</p>
              </div>
              <div className={`w-16 h-16 ${stat.bg} ${stat.color} rounded-2xl flex items-center justify-center shadow-inner group-hover:scale-110 group-hover:rotate-12 transition-all duration-500`}>
                <stat.icon size={28} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8 animate-slide-down" />}
      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8 animate-slide-down" />}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Main Content - Recent Papers */}
        <div className="lg:col-span-3 space-y-8 animate-fade-in" style={{ animationDelay: '200ms' }}>
          <div className="glass-card overflow-hidden shadow-lg hover:shadow-xl transition-shadow duration-500">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-white/80 to-white/40">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-lg flex items-center justify-center font-bold shadow-lg">
                  <Layers size={20} />
                </div>
                <div>
                  <h2 className="text-xl font-black text-gray-900">Recent Question Papers</h2>
                  <p className="text-xs text-gray-500 font-medium">View and manage your generated papers</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {selectedPapers.length > 0 && (
                  <button 
                    onClick={handleBulkDelete}
                    className="flex items-center gap-2 px-3 py-2 bg-red-50 text-red-600 rounded-xl text-sm font-bold hover:bg-red-100 transition-all duration-300 hover:shadow-lg active:scale-95"
                  >
                    <Trash2 size={16} />
                    <span>Delete ({selectedPapers.length})</span>
                  </button>
                )}
              </div>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-[#f8fafc] text-[10px] font-black uppercase text-gray-400 tracking-widest border-b border-gray-100">
                  <tr>
                    <th className="px-6 py-4 w-10">
                      <input 
                        type="checkbox" 
                        className="rounded border-gray-300 text-[#1e293b] focus:ring-[#1e293b]"
                        checked={selectedPapers.length === stats.recent_activity.length && stats.recent_activity.length > 0}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th className="px-6 py-4">Details</th>
                    <th className="px-5 py-4">Pattern</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {stats.recent_activity.length > 0 ? stats.recent_activity.map((paper, idx) => (
                    <tr key={paper.id} className="hover:bg-gradient-to-r hover:from-blue-50/50 hover:to-transparent transition-all duration-300 group relative" style={{ animationDelay: `${idx * 50}ms` }}>
                      <td className="px-6 py-5">
                        <input 
                          type="checkbox" 
                          className="rounded border-gray-300 text-[#1e293b] focus:ring-[#1e293b] cursor-pointer transition-all"
                          checked={selectedPapers.includes(paper.id)}
                          onChange={() => toggleSelectPaper(paper.id)}
                        />
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 bg-gradient-to-br from-blue-600/20 to-blue-400/20 border border-blue-200 rounded-lg flex items-center justify-center text-blue-600 font-black shadow-sm group-hover:from-blue-600/30 group-hover:to-blue-400/30 transition-all duration-300">
                            {paper.class_name}
                          </div>
                          <div>
                            <p className="font-bold text-gray-900 leading-tight mb-1 group-hover:text-blue-600 transition-colors duration-300">{paper.subject}</p>
                            <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">{new Date(paper.created_at).toLocaleDateString()}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-5">
                        <span className="px-3 py-1.5 bg-gray-100 text-gray-700 text-[10px] font-black uppercase tracking-wider rounded-lg group-hover:bg-gray-200 transition-colors duration-300">
                          {paper.pattern_name || 'Standard'}
                        </span>
                      </td>
                      <td className="px-6 py-5">
                        {paper.status === 'done' ? (
                          <div className="flex items-center gap-1.5 text-emerald-600 font-bold text-xs bg-emerald-50 px-3 py-1.5 rounded-full w-fit shadow-sm group-hover:shadow-md transition-shadow duration-300">
                            <CheckCircle size={14} className="animate-pulse" /> <span>Completed</span>
                          </div>
                        ) : paper.status === 'failed' ? (
                          <div className="flex items-center gap-1.5 text-red-600 font-bold text-xs bg-red-50 px-3 py-1.5 rounded-full w-fit shadow-sm group-hover:shadow-md transition-shadow duration-300">
                            <Activity size={14} /> <span>Failed</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-blue-600 font-bold text-xs bg-blue-50 px-3 py-1.5 rounded-full w-fit shadow-sm group-hover:shadow-md transition-shadow duration-300">
                            <RefreshCw size={14} className="animate-spin" /> <span>Generating</span>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {paper.file && (
                            <a 
                              href={paper.file} 
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-2.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                              title="Download"
                            >
                              <Download size={18} />
                            </a>
                          )}
                          {paper.status === 'failed' && (
                            <button 
                              onClick={() => handleRetry(paper.id)}
                              className="p-2.5 text-gray-500 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                              title="Retry"
                            >
                              <RefreshCw size={18} />
                            </button>
                          )}
                          <button 
                            onClick={() => handleDelete(paper.id)}
                            className="p-2.5 text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                            title="Delete"
                          >
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan="5" className="py-24 text-center">
                        <div className="flex flex-col items-center gap-4 animate-fade-in">
                          <div className="w-20 h-20 bg-gradient-to-br from-gray-100 to-gray-50 rounded-full flex items-center justify-center text-gray-300 shadow-inner">
                            <FileText size={40} />
                          </div>
                          <div>
                            <p className="text-gray-900 font-bold text-lg">No papers found</p>
                            <p className="text-sm text-gray-500 font-medium tracking-tight mt-1">Generate your first question paper to get started</p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h3 className="text-xl font-black text-gray-900 mb-6 flex items-center gap-3">
              <div className="w-6 h-6 bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-lg flex items-center justify-center">
                <Briefcase size={18} />
              </div>
              Quick Workflows
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { title: 'New Blueprint', sub: 'Create structure', icon: FileSignature, color: 'text-purple-600', bg: 'bg-purple-50', link: '/blueprints' },
                { title: 'Upload Material', sub: 'Add resources', icon: Upload, color: 'text-blue-600', bg: 'bg-blue-50', link: '/materials' },
                { title: 'Manage Patterns', sub: 'Edit exam structures', icon: Settings, color: 'text-emerald-600', bg: 'bg-emerald-50', link: '/patterns' },
              ].map((action, i) => (
                <Link 
                  key={i} 
                  href={action.link} 
                  className="glass-card p-6 flex flex-col items-start gap-4 hover:bg-white transition-all duration-300 group active:scale-[0.98] hover:shadow-lg hover:-translate-y-0.5 border border-white/40"
                >
                  <div className={`w-12 h-12 ${action.bg} ${action.color} rounded-xl flex items-center justify-center shadow-md group-hover:scale-110 group-hover:shadow-lg transition-all duration-300`}>
                    <action.icon size={20} />
                  </div>
                  <div className="flex-1">
                    <h4 className="font-bold text-gray-900 leading-tight">{action.title}</h4>
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mt-1">{action.sub}</p>
                  </div>
                  <ChevronRight size={16} className="text-gray-400 group-hover:text-blue-600 group-hover:translate-x-1 transition-all duration-300 self-end" />
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* Right Sidebar - Configuration & Health */}
        <div className="space-y-6">
          {/* AI Configuration Card */}
          <div className="glass-card p-6 border-none bg-gradient-to-br from-blue-600 to-blue-700 text-white shadow-xl shadow-blue-600/30 hover:shadow-2xl hover:shadow-blue-600/40 transition-all duration-500 relative overflow-hidden group">
            {/* Animated background elements */}
            <div className="absolute top-0 right-0 w-40 h-40 bg-white/5 rounded-full translate-x-16 -translate-y-16 group-hover:scale-150 transition-transform duration-700"></div>
            <div className="absolute bottom-0 left-0 w-32 h-32 bg-white/5 rounded-full -translate-x-12 translate-y-12 group-hover:scale-125 transition-transform duration-700"></div>
            
            <div className="relative z-10">
              <div className="flex items-center gap-2 mb-5">
                <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">
                  <Settings size={18} className="animate-[spin_4s_linear_infinite]" />
                </div>
                <h3 className="text-sm font-black tracking-tight">AI Configuration</h3>
              </div>
              
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 bg-white/10 backdrop-blur-sm rounded-xl border border-white/20 group-hover:bg-white/15 transition-all duration-300">
                  <div>
                    <p className="text-blue-100 text-[10px] font-black uppercase tracking-widest mb-1">Inference</p>
                    <p className="font-black text-base">{modelSource === 'local' ? 'Local' : 'AWS Cloud'}</p>
                  </div>
                  <button 
                    onClick={handleToggleModel}
                    className={`w-12 h-6 rounded-full transition-all relative shadow-lg focus:outline-none focus:ring-2 focus:ring-white/30 ${modelSource === 'aws' ? 'bg-emerald-400' : 'bg-blue-400'}`}
                  >
                    <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-all duration-300 ${modelSource === 'aws' ? 'left-6' : 'left-0.5'}`}></div>
                  </button>
                </div>
                <p className="text-xs text-blue-100/60 font-medium leading-relaxed">
                  Toggle between local and AWS for optimal performance and cost efficiency.
                </p>
              </div>
            </div>
          </div>

          {/* System Health Card */}
          <div className="glass-card p-6 border border-white/40 shadow-lg hover:shadow-xl transition-shadow duration-500">
            <h3 className="text-sm font-black text-gray-900 mb-5 flex items-center gap-2">
              <div className="w-6 h-6 rounded-lg bg-emerald-100 flex items-center justify-center">
                <ShieldCheck className="text-emerald-600" size={16} />
              </div>
              System Status
            </h3>
            
            <div className="space-y-4">
              {[
                { label: 'AI Service', status: 'Online', color: 'text-emerald-600', bg: 'bg-emerald-50', icon: Zap },
                { label: 'Vector DB', status: 'Healthy', color: 'text-emerald-600', bg: 'bg-emerald-50', icon: Database },
                { label: 'Job Queue', status: 'Ready', color: 'text-blue-600', bg: 'bg-blue-50', icon: Server },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 transition-all duration-300 group cursor-default">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-lg ${item.bg} flex items-center justify-center ${item.color}`}>
                      <item.icon size={16} />
                    </div>
                    <span className="text-sm font-bold text-gray-700">{item.label}</span>
                  </div>
                  <div className={`w-3 h-3 rounded-full ${item.color.replace('text-', 'bg-')}`}></div>
                </div>
              ))}
            </div>
            
            <button className="w-full mt-5 py-2.5 bg-gradient-to-r from-gray-100 to-gray-50 text-gray-900 text-xs font-black uppercase tracking-widest rounded-lg hover:from-gray-200 hover:to-gray-100 transition-all duration-300 hover:shadow-md active:scale-95">
              Run Diagnostics
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
