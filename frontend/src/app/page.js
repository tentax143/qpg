'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { 
  Eye, EyeOff, Lock, User, Zap, ArrowRight, Sparkles
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function RootPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  
  // Auth Form State
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    if (token) {
      router.push('/dashboard');
    }
    setLoading(false);
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setLoginLoading(true);

    try {
      const response = await apiClient.post('/auth/login/', formData);
      localStorage.setItem('authToken', response.data.token);
      localStorage.setItem('user', JSON.stringify(response.data.user));
      // Store login timestamp
      localStorage.setItem('loginTimestamp', Date.now().toString());
      
      setSuccess('Redirecting to dashboard...');
      setTimeout(() => {
        router.push('/dashboard');
      }, 800);
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally {
      setLoginLoading(false);
    }
  };

  if (loading) return (
    <div className="min-h-screen mesh-gradient flex items-center justify-center">
      <div className="w-12 h-12 border-4 border-blue-600/30 border-t-blue-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 relative overflow-hidden">
      <div className="mesh-gradient"></div>
      <div className="absolute top-10 left-10 text-blue-200/20 animate-pulse"><Sparkles size={120} /></div>
      
      <div className="w-full max-w-md relative z-10 lg:-translate-x-24 animate-in fade-in zoom-in-95 duration-500">
        <div className="glass-card p-10 shadow-2xl shadow-blue-900/20">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl shadow-xl shadow-blue-500/30 mb-6 group hover:rotate-12 transition-transform">
              <Zap className="text-white w-10 h-10" />
            </div>
            <h1 className="text-3xl font-black text-gray-900 mb-2">QPG System</h1>
            <p className="text-gray-500 font-medium tracking-tight">Professional AI Question Generator</p>
          </div>

          {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
          {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

          <form onSubmit={handleLogin} className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1 uppercase tracking-wider">Username</label>
              <div className="relative group">
                <div className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
                  <User size={20} />
                </div>
                <input
                  type="text"
                  placeholder="Your username"
                  className="w-full pl-12 pr-4 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                  value={formData.username}
                  onChange={(e) => setFormData({...formData, username: e.target.value})}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1 uppercase tracking-wider">Password</label>
              <div className="relative group">
                <div className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
                  <Lock size={20} />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Your password"
                  className="w-full pl-12 pr-12 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                  value={formData.password}
                  onChange={(e) => setFormData({...formData, password: e.target.value})}
                  required
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400 hover:text-blue-600">
                  {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loginLoading}
              className="w-full py-4 bg-blue-600 hover:bg-blue-700 text-white font-black rounded-2xl shadow-lg shadow-blue-200 transition-all transform hover:scale-[1.02] active:scale-[0.98] flex items-center justify-center gap-2"
            >
              {loginLoading ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> : <><span>Get Started</span> <ArrowRight size={20} /></>}
            </button>
          </form>

          <div className="mt-10 pt-8 border-t border-gray-100 text-center">
            <p className="text-gray-500 font-medium tracking-tight">Don't have an account? <Link href="/register" className="text-blue-600 font-bold hover:underline">Register Now</Link></p>
          </div>
        </div>
      </div>
    </div>
  );
}