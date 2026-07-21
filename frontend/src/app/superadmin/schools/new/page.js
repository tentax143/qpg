'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { ArrowLeft, Sparkles, Building2, Check, DollarSign, Database, Loader2 } from 'lucide-react';

export default function NewSchoolPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: '',
    address: '',
    phone: '',
    email: '',
    monthly_token_budget: '',
    is_active: true,
    access_shared_vector_store: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') router.replace('/dashboard');
  }, [router]);

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!form.name.trim()) { setError('School name is required'); return; }
    try {
      setLoading(true);
      const payload = {
        ...form,
        monthly_token_budget: form.monthly_token_budget ? parseInt(form.monthly_token_budget) : 0,
      };
      const r = await apiClient.post('/admin/schools/', payload);
      router.push(`/superadmin/schools/${r.data.id}`);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to create school');
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
      <div className="mb-10 max-w-2xl mx-auto">
        <Link href="/superadmin/schools" className="inline-flex items-center gap-2 px-4 py-2 bg-white/80 border border-slate-200/60 rounded-full text-[12px] font-bold text-slate-500 hover:text-indigo-600 hover:border-indigo-200 transition-all shadow-sm mb-6 group">
          <ArrowLeft size={14} className="group-hover:-translate-x-1 transition-transform" />
          Back to Directory
        </Link>
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-white border border-slate-200/60 shadow-lg rounded-2xl flex items-center justify-center text-indigo-600">
            <Building2 size={24} strokeWidth={2} />
          </div>
          <div>
            <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-2">
              <Sparkles size={12} className="text-amber-500" />
              <span className="text-[10px] font-bold text-slate-700 uppercase tracking-widest">Provisioning</span>
            </div>
            <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight">New Tenant</h1>
          </div>
        </div>
      </div>

      <div className="max-w-2xl mx-auto">
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[32px] p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
          {error && (
            <div className="mb-8 bg-red-50 border border-red-100 rounded-2xl px-6 py-4 text-[13px] font-bold text-red-600 text-center">
              {error}
            </div>
          )}
          
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">School Name *</label>
              <input
                type="text"
                name="name"
                value={form.name}
                onChange={handleChange}
                placeholder="e.g. Sunrise Public School"
                className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
                required
              />
            </div>

            <div>
              <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">Address</label>
              <textarea
                name="address"
                value={form.address}
                onChange={handleChange}
                rows={3}
                placeholder="Full address"
                className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow resize-none"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">Phone Number</label>
                <input
                  type="text"
                  name="phone"
                  value={form.phone}
                  onChange={handleChange}
                  placeholder="+91 XXXXX XXXXX"
                  className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
                />
              </div>
              <div>
                <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2">Admin Email</label>
                <input
                  type="email"
                  name="email"
                  value={form.email}
                  onChange={handleChange}
                  placeholder="admin@school.edu"
                  className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
                />
              </div>
            </div>

            <div className="pt-4 border-t border-slate-100">
              <label className="block text-[12px] font-bold text-slate-500 uppercase tracking-wider ml-1 mb-2 flex items-center gap-2">
                <DollarSign size={14} /> Monthly Token Budget
              </label>
              <input
                type="number"
                name="monthly_token_budget"
                value={form.monthly_token_budget}
                onChange={handleChange}
                placeholder="0 = unlimited"
                min="0"
                className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-indigo-500 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm transition-shadow"
              />
              <p className="mt-2 text-[11px] font-medium text-slate-400 ml-1">Leave 0 to grant unlimited access to API generation.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
              <label className={`flex flex-col p-5 rounded-2xl border-2 cursor-pointer transition-all ${form.is_active ? 'bg-emerald-50/50 border-emerald-500 shadow-md shadow-emerald-500/10' : 'bg-slate-50 border-slate-200 hover:border-slate-300'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[14px] font-extrabold text-slate-900">Tenant Active</span>
                  <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${form.is_active ? 'bg-emerald-500 border-emerald-500' : 'bg-white border-slate-300'}`}>
                    {form.is_active && <Check size={14} className="text-white" />}
                  </div>
                </div>
                <p className="text-[11px] font-medium text-slate-500">Allow members to log in and use the platform.</p>
                <input
                  type="checkbox"
                  name="is_active"
                  checked={form.is_active}
                  onChange={handleChange}
                  className="hidden"
                />
              </label>

              <label className={`flex flex-col p-5 rounded-2xl border-2 cursor-pointer transition-all ${form.access_shared_vector_store ? 'bg-indigo-50/50 border-indigo-500 shadow-md shadow-indigo-500/10' : 'bg-slate-50 border-slate-200 hover:border-slate-300'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[14px] font-extrabold text-slate-900 flex items-center gap-1.5"><Database size={14} className={form.access_shared_vector_store ? 'text-indigo-600' : 'text-slate-400'}/> Shared Context</span>
                  <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${form.access_shared_vector_store ? 'bg-indigo-600 border-indigo-600' : 'bg-white border-slate-300'}`}>
                    {form.access_shared_vector_store && <Check size={14} className="text-white" />}
                  </div>
                </div>
                <p className="text-[11px] font-medium text-slate-500">Grant instant access to global RAG textbook data.</p>
                <input
                  type="checkbox"
                  name="access_shared_vector_store"
                  checked={form.access_shared_vector_store}
                  onChange={handleChange}
                  className="hidden"
                />
              </label>
            </div>

            <div className="flex gap-4 pt-8">
              <button
                type="submit"
                disabled={loading}
                className="flex-1 py-4 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 disabled:opacity-60 text-white text-[14px] font-bold rounded-2xl shadow-lg shadow-indigo-200/50 transition-all flex items-center justify-center gap-2 active:scale-[0.98]"
              >
                {loading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <>
                    <Building2 size={18} />
                    Provision School
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
