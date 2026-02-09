'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Eye, EyeOff, Lock, User, Mail, Zap, ArrowRight, Sparkles, CheckCircle } from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

export default function RegisterPage() {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    password2: '',
  });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [focusedField, setFocusedField] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (formData.password !== formData.password2) {
      setError('Passwords do not match');
      return;
    }

    try {
      setLoading(true);
      const response = await apiClient.post('/auth/register/', {
        username: formData.username,
        email: formData.email,
        password: formData.password,
        password2: formData.password2,
      });

      localStorage.setItem('authToken', response.data.token);
      localStorage.setItem('user', JSON.stringify(response.data.user));

      setSuccess('Account created! Redirecting...');
      setTimeout(() => {
        window.location.href = '/';
      }, 1000);
    } catch (err) {
      const errorMsg = err.response?.data?.username?.[0] || 
                       err.response?.data?.email?.[0] || 
                       err.response?.data?.detail ||
                       'Registration failed. Please try again.';
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 relative overflow-hidden">
      {/* Mesh Gradient Background */}
      <div className="mesh-gradient"></div>

      {/* Decorative elements */}
      <div className="absolute top-1/4 right-1/4 text-indigo-200/20 animate-pulse">
        <Sparkles size={80} />
      </div>
      <div className="absolute bottom-1/4 left-1/4 text-blue-200/20 animate-pulse" style={{ animationDelay: '3s' }}>
        <Sparkles size={120} />
      </div>

      <div className="w-full max-w-lg relative z-10 lg:-translate-x-24 animate-in fade-in zoom-in-95 duration-500">
        {/* Glassmorphism Card */}
        <div className="glass-card p-10">
          {/* Header */}
          <div className="text-center mb-10">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600 rounded-2xl shadow-xl shadow-blue-500/30 mb-6 group hover:scale-110 transition-transform cursor-pointer">
              <Zap className="text-white w-10 h-10" />
            </div>
            <h1 className="text-4xl font-black text-gray-900 mb-2">Create Account</h1>
            <p className="text-gray-500 font-medium text-lg">Start your AI educator journey today</p>
          </div>

          {/* Alerts */}
          {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
          {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Username */}
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700 ml-1">Username</label>
                <div className={`relative group transition-all duration-300 ${focusedField === 'username' ? 'scale-[1.02]' : ''}`}>
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 transition-colors ${focusedField === 'username' ? 'text-blue-600' : 'text-gray-400'}`}>
                    <User size={20} />
                  </div>
                  <input
                    type="text"
                    name="username"
                    placeholder="Username"
                    className="w-full pl-12 pr-4 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                    onFocus={() => setFocusedField('username')}
                    onBlur={() => setFocusedField(null)}
                    value={formData.username}
                    onChange={handleChange}
                    required
                  />
                </div>
              </div>

              {/* Email */}
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700 ml-1">Email Address</label>
                <div className={`relative group transition-all duration-300 ${focusedField === 'email' ? 'scale-[1.02]' : ''}`}>
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 transition-colors ${focusedField === 'email' ? 'text-blue-600' : 'text-gray-400'}`}>
                    <Mail size={20} />
                  </div>
                  <input
                    type="email"
                    name="email"
                    placeholder="your@email.com"
                    className="w-full pl-12 pr-4 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                    onFocus={() => setFocusedField('email')}
                    onBlur={() => setFocusedField(null)}
                    value={formData.email}
                    onChange={handleChange}
                    required
                  />
                </div>
              </div>

              {/* Password */}
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700 ml-1">Password</label>
                <div className={`relative group transition-all duration-300 ${focusedField === 'password' ? 'scale-[1.02]' : ''}`}>
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 transition-colors ${focusedField === 'password' ? 'text-blue-600' : 'text-gray-400'}`}>
                    <Lock size={20} />
                  </div>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    placeholder="••••••••"
                    className="w-full pl-12 pr-12 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                    onFocus={() => setFocusedField('password')}
                    onBlur={() => setFocusedField(null)}
                    value={formData.password}
                    onChange={handleChange}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400 hover:text-blue-600"
                  >
                    {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                  </button>
                </div>
              </div>

              {/* Confirm Password */}
              <div className="space-y-2">
                <label className="text-sm font-bold text-gray-700 ml-1">Confirm Password</label>
                <div className={`relative group transition-all duration-300 ${focusedField === 'password2' ? 'scale-[1.02]' : ''}`}>
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 transition-colors ${focusedField === 'password2' ? 'text-blue-600' : 'text-gray-400'}`}>
                    <CheckCircle size={20} />
                  </div>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="password2"
                    placeholder="••••••••"
                    className="w-full pl-12 pr-4 py-4 bg-white/50 border border-white/50 rounded-2xl text-gray-900 focus:ring-2 focus:ring-blue-500 transition-all outline-none focus:bg-white"
                    onFocus={() => setFocusedField('password2')}
                    onBlur={() => setFocusedField(null)}
                    value={formData.password2}
                    onChange={handleChange}
                    required
                  />
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-4 mt-4 bg-blue-600 hover:bg-blue-700 text-white font-black rounded-2xl shadow-xl shadow-blue-200 transition-all transform hover:scale-[1.02] active:scale-[0.98] flex items-center justify-center gap-3 disabled:opacity-70 disabled:cursor-not-allowed group"
            >
              {loading ? (
                <div className="w-6 h-6 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              ) : (
                <>
                  <span>Create My Account</span>
                  <ArrowRight size={22} className="group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
          </form>

          {/* Footer */}
          <div className="mt-10 pt-8 border-t border-white/20 text-center">
            <p className="text-gray-500 font-medium text-lg">
              Already have an account?{' '}
              <Link href="/login" className="text-blue-600 font-black hover:underline underline-offset-4">
                Sign In
              </Link>
            </p>
          </div>
        </div>

        <p className="text-center mt-8 text-gray-400 text-sm font-medium">
          © 2024 Question Paper Generator System • Versio 2.0
        </p>
      </div>
    </div>
  );
}
