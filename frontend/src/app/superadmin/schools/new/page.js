'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { ArrowLeft } from 'lucide-react';

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
    <div className="max-w-lg">
      <div className="flex items-center gap-3 mb-6">
        <Link href="/superadmin/schools" className="text-slate-400 hover:text-slate-600 transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-xl font-semibold text-slate-900">New School</h1>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">School Name *</label>
            <input
              type="text"
              name="name"
              value={form.name}
              onChange={handleChange}
              placeholder="e.g. Sunrise Public School"
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Address</label>
            <textarea
              name="address"
              value={form.address}
              onChange={handleChange}
              rows={2}
              placeholder="Full address"
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Phone</label>
              <input
                type="text"
                name="phone"
                value={form.phone}
                onChange={handleChange}
                placeholder="+91 XXXXX XXXXX"
                className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Email</label>
              <input
                type="email"
                name="email"
                value={form.email}
                onChange={handleChange}
                placeholder="admin@school.edu"
                className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Monthly Token Budget</label>
            <input
              type="number"
              name="monthly_token_budget"
              value={form.monthly_token_budget}
              onChange={handleChange}
              placeholder="0 = unlimited"
              min="0"
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="mt-1 text-xs text-slate-400">Leave 0 for no limit</p>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_active"
              name="is_active"
              checked={form.is_active}
              onChange={handleChange}
              className="w-4 h-4 text-blue-600 border-slate-300 rounded"
            />
            <label htmlFor="is_active" className="text-sm text-slate-700">Active</label>
          </div>

          <div className="border border-blue-100 bg-blue-50 rounded-lg p-4 space-y-1">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="access_shared_vector_store"
                name="access_shared_vector_store"
                checked={form.access_shared_vector_store}
                onChange={handleChange}
                className="w-4 h-4 text-blue-600 border-slate-300 rounded"
              />
              <label htmlFor="access_shared_vector_store" className="text-sm font-medium text-slate-700">
                Grant access to shared content
              </label>
            </div>
            <p className="text-xs text-slate-500 ml-6">
              This school will read the shared (superadmin) vector store — all shared textbooks and chapters — alongside its own materials. Takes effect immediately; nothing is copied. You can change this anytime from the school&apos;s page.
            </p>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center"
            >
              {loading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : 'Create School'}
            </button>
            <Link
              href="/superadmin/schools"
              className="px-4 py-2.5 border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 transition-colors text-center"
            >
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
