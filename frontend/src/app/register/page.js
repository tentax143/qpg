'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { GraduationCap, ArrowRight, Loader2 } from 'lucide-react';
import apiClient from '@/lib/api';

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ school_name: '', admin_name: '', email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [serverError, setServerError] = useState('');

  function set(field, val) {
    setForm(f => ({ ...f, [field]: val }));
    setErrors(e => ({ ...e, [field]: '' }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setServerError('');
    setLoading(true);
    try {
      const res = await apiClient.post('/auth/register/', form);
      const { token, user, trial_ends_at, plan } = res.data;
      localStorage.setItem('authToken', token);
      localStorage.setItem('user', JSON.stringify(user));
      // Redirect to onboarding — they just created a fresh school
      router.replace('/onboarding');
    } catch (err) {
      if (err.response?.data && typeof err.response.data === 'object') {
        setErrors(err.response.data);
      } else {
        setServerError(err.response?.data?.error || 'Registration failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  }

  const fields = [
    { key: 'school_name', label: 'School Name', placeholder: 'e.g. Delhi Public School', type: 'text' },
    { key: 'admin_name',  label: 'Your Name',   placeholder: 'Full name', type: 'text' },
    { key: 'email',       label: 'Email',        placeholder: 'you@school.edu.in', type: 'email' },
    { key: 'password',    label: 'Password',     placeholder: 'Min. 8 characters', type: 'password' },
  ];

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-600 rounded-xl mb-3">
            <GraduationCap className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900">Start your free trial</h1>
          <p className="text-slate-500 text-sm mt-1">14 days Pro · No credit card required</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-2xl p-6 space-y-4 shadow-sm">
          {fields.map(({ key, label, placeholder, type }) => (
            <div key={key}>
              <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
              <input
                type={type}
                value={form[key]}
                onChange={e => set(key, e.target.value)}
                placeholder={placeholder}
                required
                className={`w-full px-3 py-2 text-sm border rounded-lg outline-none transition-colors
                  ${errors[key] ? 'border-red-400 bg-red-50' : 'border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-100'}`}
              />
              {errors[key] && <p className="text-red-600 text-xs mt-1">{errors[key]}</p>}
            </div>
          ))}

          {serverError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
              {serverError}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-2.5 rounded-lg transition-colors"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
            {loading ? 'Creating account…' : 'Create free account'}
          </button>
        </form>

        {/* Plan comparison nudge */}
        <div className="mt-4 bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-800">
          <p className="font-semibold mb-2">What&apos;s included in the free trial:</p>
          <ul className="space-y-1 text-blue-700 text-xs">
            <li>✓ 100 question papers / month (Pro)</li>
            <li>✓ Up to 15 teachers</li>
            <li>✓ All CBSE subjects &amp; classes</li>
            <li>✓ AI question generation with 10-gate validation</li>
          </ul>
          <p className="text-xs text-blue-500 mt-2">After 14 days: Free plan (5 papers/month) unless you upgrade.</p>
        </div>

        <p className="text-center text-sm text-slate-500 mt-4">
          Already have an account?{' '}
          <Link href="/login" className="text-blue-600 hover:underline font-medium">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
