'use client';

import { useState, useEffect } from 'react';
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
  }, []);

  const fetchDashboardData = async () => {
    try {
      const papersRes = await apiClient.get('/papers/?page_size=100');
      const papers = papersRes.data.results || [];
      
      const total = papers.length;
      const now = new Date();
      const firstDayOfMonth = new Date(now.getFullYear(), now.getMonth(), 1);
      const thisMonth = papers.filter(p => new Date(p.created_at) >= firstDayOfMonth).length;
      const successCount = papers.filter(p => p.status === 'completed' || p.status === 'Generated').length;
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
    <div className="w-full relative py-6">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-10 mb-16">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_12px_rgba(16,185,129,0.5)]"></div>
            <span className="text-xs font-black text-gray-400 uppercase tracking-[0.2em]">Active Session</span>
          </div>
          <h1 className="text-5xl font-black text-gray-900 leading-tight tracking-tight">
            Hi, <span className="text-blue-600">{user?.username || 'Professor'}</span>!
          </h1>
          <p className="text-gray-500 font-medium text-lg tracking-tight max-w-xl">
            Your intelligence-backed assessment headquarters is ready.
          </p>
        </div>
        
        <div className="flex items-center gap-4">
          <Link href="/generator" className="group flex items-center gap-4 bg-gray-900 text-white pl-8 pr-4 py-5 rounded-[24px] font-black shadow-2xl shadow-blue-900/10 hover:bg-black transition-all hover:-translate-y-1 active:scale-95">
            <span className="text-sm tracking-widest uppercase">Generate New Paper</span>
            <div className="w-12 h-12 bg-white/10 rounded-xl flex items-center justify-center group-hover:bg-blue-600 transition-colors duration-500">
              <Plus size={24} className="group-hover:rotate-90 transition-transform duration-500" />
            </div>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
        {[
          { label: 'Total Papers', value: stats.total_papers, icon: FileText, color: 'text-blue-600', bg: 'bg-blue-500/10', sub: 'Lifetime generations' },
          { label: 'This Month', value: stats.this_month, icon: Clock, color: 'text-indigo-600', bg: 'bg-indigo-500/10', sub: 'New this month' },
          { label: 'Success Rate', value: stats.success_rate, icon: Activity, color: 'text-emerald-600', bg: 'bg-emerald-500/10', sub: 'Generation accuracy' },
        ].map((stat, i) => (
          <div key={i} className="bg-white/80 backdrop-blur-xl p-8 rounded-[40px] shadow-2xl shadow-blue-500/5 border border-white/20 group relative overflow-hidden transition-all duration-500 hover:shadow-blue-500/10 hover:-translate-y-1">
            <div className="relative z-10 flex justify-between items-start">
              <div className="space-y-1">
                <p className="text-gray-400 font-black text-[10px] uppercase tracking-[0.2em]">{stat.label}</p>
                <h3 className="text-5xl font-black text-gray-900 tracking-tight">{stat.value}</h3>
                <p className="text-xs font-bold text-gray-400 tracking-tight pt-2">{stat.sub}</p>
              </div>
              <div className={`w-16 h-16 ${stat.bg} ${stat.color} rounded-2xl flex items-center justify-center shadow-inner group-hover:scale-110 group-hover:rotate-6 transition-all duration-500`}>
                <stat.icon size={28} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}
      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
        <div className="lg:col-span-2 space-y-8">
          <div className="glass-card overflow-hidden">
            <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold">
                  <Layers size={18} />
                </div>
                <h2 className="text-xl font-black text-gray-900">Recent Question Papers</h2>
              </div>
              <div className="flex items-center gap-2">
                {selectedPapers.length > 0 && (
                  <button 
                    onClick={handleBulkDelete}
                    className="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-600 rounded-xl text-sm font-bold hover:bg-red-100 transition-colors"
                  >
                    <Trash2 size={16} />
                    <span>Delete Selected ({selectedPapers.length})</span>
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
                <tbody className="divide-y divide-gray-50">
                  {stats.recent_activity.length > 0 ? stats.recent_activity.map((paper) => (
                    <tr key={paper.id} className="hover:bg-blue-50/30 transition-colors group">
                      <td className="px-6 py-5">
                        <input 
                          type="checkbox" 
                          className="rounded border-gray-300 text-[#1e293b] focus:ring-[#1e293b]"
                          checked={selectedPapers.includes(paper.id)}
                          onChange={() => toggleSelectPaper(paper.id)}
                        />
                      </td>
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-4">
                          <div className="w-10 h-10 bg-white border border-gray-100 rounded-xl flex items-center justify-center text-blue-600 font-bold shadow-sm">
                            {paper.class_name}
                          </div>
                          <div>
                            <p className="font-bold text-gray-900 leading-tight mb-1 group-hover:text-blue-600 transition-colors">{paper.subject}</p>
                            <p className="text-[10px] text-gray-400 font-bold uppercase tracking-wider">Created: {new Date(paper.created_at).toLocaleDateString()}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-5">
                        <span className="px-3 py-1 bg-gray-100 text-gray-600 text-[10px] font-black uppercase tracking-wider rounded-lg">
                          {paper.pattern_name || 'Standard'}
                        </span>
                      </td>
                      <td className="px-6 py-5">
                        {paper.status === 'done' ? (
                          <div className="flex items-center gap-1.5 text-emerald-600 font-bold text-xs bg-emerald-50 px-3 py-1.5 rounded-full w-fit">
                            <CheckCircle size={14} /> <span>Completed</span>
                          </div>
                        ) : paper.status === 'failed' ? (
                          <div className="flex items-center gap-1.5 text-red-600 font-bold text-xs bg-red-50 px-3 py-1.5 rounded-full w-fit">
                            <Activity size={14} /> <span>Failed</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-blue-600 font-bold text-xs bg-blue-50 px-3 py-1.5 rounded-full w-fit">
                            <RefreshCw size={14} className="animate-spin" /> <span>Gen...</span>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {paper.file && (
                            <a 
                              href={paper.file} 
                              target="_blank"
                              className="p-2 text-gray-500 hover:text-blue-600 hover:bg-white rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                              title="Download"
                            >
                              <Download size={18} />
                            </a>
                          )}
                          {paper.status === 'failed' && (
                            <button 
                              onClick={() => handleRetry(paper.id)}
                              className="p-2 text-gray-500 hover:text-emerald-600 hover:bg-white rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                              title="Retry"
                            >
                              <RefreshCw size={18} />
                            </button>
                          )}
                          <button 
                            onClick={() => handleDelete(paper.id)}
                            className="p-2 text-gray-500 hover:text-red-500 hover:bg-white rounded-lg transition-all duration-300 hover:scale-110 active:scale-90"
                            title="Delete"
                          >
                            <Trash2 size={18} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )) : (
                    <tr>
                      <td colSpan="5" className="py-20 text-center">
                        <div className="flex flex-col items-center gap-4">
                          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center text-gray-300">
                            <FileText size={32} />
                          </div>
                          <div>
                            <p className="text-gray-900 font-bold">No papers found</p>
                            <p className="text-sm text-gray-500 font-medium tracking-tight">Generate your first question paper to see it here.</p>
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
              <Briefcase className="text-blue-600" size={24} />
              Quick Workflows
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {[
                { title: 'New Blueprint', sub: 'Create structure', icon: FileSignature, color: 'text-purple-600', bg: 'bg-purple-50', link: '/blueprints' },
                { title: 'Upload Material', sub: 'Add resources', icon: Upload, color: 'text-blue-600', bg: 'bg-blue-50', link: '/materials' },
                { title: 'Manage Patterns', sub: 'Edit exam structures', icon: Settings, color: 'text-emerald-600', bg: 'bg-emerald-50', link: '/patterns' },
              ].map((action, i) => (
                <Link key={i} href={action.link} className="glass-card p-6 flex items-center gap-4 hover:bg-white transition-all duration-300 group active:scale-[0.98] hover:shadow-2xl hover:-translate-y-1">
                  <div className={`w-12 h-12 ${action.bg} ${action.color} rounded-xl flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform duration-300`}>
                    <action.icon size={22} />
                  </div>
                  <div>
                    <h4 className="font-bold text-gray-900 leading-tight">{action.title}</h4>
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest mt-1">{action.sub}</p>
                  </div>
                  <ChevronRight size={18} className="ml-auto text-gray-400 group-hover:text-blue-600 group-hover:translate-x-1 transition-all duration-300" />
                </Link>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-8">
          <div className="glass-card p-8 border-none bg-blue-600 text-white shadow-2xl shadow-blue-200 relative overflow-hidden group">
            <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full translate-x-10 -translate-y-10 group-hover:scale-125 transition-transform duration-700"></div>
            <div className="relative z-10">
              <div className="flex items-center gap-3 mb-6">
                <Settings className="text-blue-200 animate-spin-slow" size={20} />
                <h3 className="text-lg font-black tracking-tight">AI Configuration</h3>
              </div>
              <div className="space-y-6">
                <div className="flex items-center justify-between p-4 bg-white/10 backdrop-blur-md rounded-2xl border border-white/10">
                  <div>
                    <p className="text-blue-100 text-[10px] font-black uppercase tracking-widest mb-1">Inference Source</p>
                    <p className="font-black text-lg">{modelSource === 'local' ? 'Local Compute' : 'AWS Cloud'}</p>
                  </div>
                  <button 
                    onClick={handleToggleModel}
                    className={`w-14 h-8 rounded-full transition-all relative ${modelSource === 'aws' ? 'bg-emerald-400' : 'bg-blue-400'}`}
                  >
                    <div className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-lg transition-all ${modelSource === 'aws' ? 'left-7' : 'left-1'}`}></div>
                  </button>
                </div>
                <p className="text-xs text-blue-100/70 font-medium leading-relaxed">
                  Toggle between local execution and cloud-based AWS inference for cost optimization.
                </p>
              </div>
            </div>
          </div>

          <div className="glass-card p-8">
            <h3 className="text-lg font-black text-gray-900 mb-6 flex items-center gap-3">
              <ShieldCheck className="text-emerald-500" size={20} />
              System Health
            </h3>
            <div className="space-y-6">
              {[
                { label: 'AI Service', status: 'Online', color: 'text-emerald-500', icon: Zap },
                { label: 'Vector DB', status: 'Healthy', color: 'text-emerald-500', icon: Database },
                { label: 'Job Queue', status: 'Ready', color: 'text-blue-500', icon: Server },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between group">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-gray-50 flex items-center justify-center text-gray-400 group-hover:text-blue-600 transition-colors">
                      <item.icon size={16} />
                    </div>
                    <span className="text-sm font-bold text-gray-500">{item.label}</span>
                  </div>
                  <span className={`text-[10px] font-black uppercase tracking-widest ${item.color} bg-gray-50 px-2 py-1 rounded`}>{item.status}</span>
                </div>
              ))}
            </div>
            <div className="mt-8 pt-6 border-t border-gray-100">
              <button className="w-full py-3 bg-gray-50 text-gray-900 text-xs font-black uppercase tracking-widest rounded-xl hover:bg-gray-100 transition-all">
                Run Diagnostics
              </button>
            </div>
          </div>

          <div className="glass-card p-8 bg-[#0f172a] text-white relative overflow-hidden group">
            <Sparkles className="absolute -right-6 -bottom-6 w-40 h-40 text-blue-500/10 group-hover:scale-125 transition-transform duration-1000" />
            <div className="relative z-10">
              <h3 className="text-2xl font-black mb-3">Optimize Prep</h3>
              <p className="text-gray-400 font-medium mb-8 leading-relaxed">Your AI models are learning from your recent papers to improve accuracy.</p>
              <button className="flex items-center gap-2 text-blue-400 font-black text-sm group-hover:gap-3 transition-all">
                <span>View Insights</span>
                <ArrowRight size={18} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
