'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Eye, EyeOff, GraduationCap, Sparkles, LayoutTemplate, Printer } from 'lucide-react';
import { useGoogleLogin } from '@react-oauth/google';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

const FEATURES = [
  { icon: Sparkles,       text: 'AI-generated questions from your materials' },
  { icon: LayoutTemplate, text: 'Reusable blueprint templates' },
  { icon: Printer,        text: 'Print-ready PDFs in one click' },
];

function GoogleSignInButton({ setError, setSuccess }) {
  const [googleLoading, setGoogleLoading] = useState(false);

  const googleLogin = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      setError(null);
      setGoogleLoading(true);
      try {
        const response = await apiClient.post('/auth/google/', {
          access_token: tokenResponse.access_token,
        });
        const userData = response.data.user;
        localStorage.setItem('authToken', response.data.token);
        localStorage.setItem('user', JSON.stringify(userData));
        localStorage.setItem('loginTimestamp', Date.now().toString());
        setSuccess('Signed in with Google! Redirecting...');
        const dest = userData?.require_password_change
          ? '/change-password'
          : (userData?.role === 'superadmin' ? '/superadmin' : '/dashboard');
        setTimeout(() => { window.location.href = dest; }, 800);
      } catch (err) {
        setError(err.response?.data?.error || 'Google sign-in failed. Please try again.');
      } finally {
        setGoogleLoading(false);
      }
    },
    onError: () => setError('Google sign-in was cancelled or failed.'),
  });

  return (
    <button
      type="button"
      onClick={() => googleLogin()}
      disabled={googleLoading}
      className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 border border-slate-300 rounded-lg text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
    >
      {googleLoading ? (
        <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
      ) : (
        <GoogleLogo />
      )}
      Continue with Google
    </button>
  );
}

function GoogleLogo() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" aria-hidden="true">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
    </svg>
  );
}

function LoginForm() {
  const searchParams = useSearchParams();
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    if (searchParams.get('expired') === 'true') {
      setError('Your session has expired. Please sign in again.');
    }
  }, [searchParams]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!formData.username || !formData.password) {
      setError('Please enter both username and password');
      return;
    }
    try {
      setLoading(true);
      const response = await apiClient.post('/auth/login/', {
        username: formData.username,
        password: formData.password,
      });
      const userData = response.data.user;
      localStorage.setItem('authToken', response.data.token);
      localStorage.setItem('user', JSON.stringify(userData));
      localStorage.setItem('loginTimestamp', Date.now().toString());
      setSuccess('Login successful! Redirecting...');
      const dest = userData?.require_password_change
        ? '/change-password'
        : (userData?.role === 'superadmin' ? '/superadmin' : '/dashboard');
      setTimeout(() => { window.location.href = dest; }, 1000);
    } catch (err) {
      const errorMsg = err.response?.data?.detail ||
        err.response?.data?.non_field_errors?.[0] ||
        'Invalid username or password';
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">

      {/* ── Left panel — sign-in form ─────────────────────────────────── */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-sm">

          {/* Logo */}
          <div className="mb-8">
            <div className="inline-flex items-center justify-center w-10 h-10 bg-blue-600 rounded-xl mb-5">
              <GraduationCap className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-2xl font-semibold text-slate-900 tracking-tight">Welcome back</h1>
            <p className="text-sm text-slate-500 mt-1">Sign in to your Shiken account</p>
          </div>

          {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-4" />}
          {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-4" />}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Username</label>
              <input
                type="text"
                name="username"
                placeholder="Enter your username"
                className="w-full px-3.5 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm transition-shadow"
                value={formData.username}
                onChange={handleChange}
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  placeholder="Enter your password"
                  className="w-full px-3.5 py-2.5 bg-white border border-slate-300 rounded-lg text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm pr-10 transition-shadow"
                  value={formData.password}
                  onChange={handleChange}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : 'Sign in'}
            </button>
          </form>

          {/* Divider */}
          <div className="relative my-5">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-200" />
            </div>
            <div className="relative flex justify-center">
              <span className="bg-white px-2 text-xs text-slate-400">or</span>
            </div>
          </div>

          {/* Google button */}
          {GOOGLE_CLIENT_ID ? (
            <GoogleSignInButton setError={setError} setSuccess={setSuccess} />
          ) : (
            <button
              type="button"
              onClick={() => setError('Google sign-in is not configured yet. Add NEXT_PUBLIC_GOOGLE_CLIENT_ID to enable it.')}
              className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 border border-slate-300 rounded-lg text-slate-700 text-sm font-medium hover:bg-slate-50 transition-colors"
            >
              <GoogleLogo />
              Continue with Google
            </button>
          )}

          <p className="text-xs text-slate-400 text-center mt-6">
            Don&apos;t have an account?{' '}
            <a href="/register" className="text-blue-600 hover:underline font-medium">Register your school</a>
          </p>
        </div>
      </div>

      {/* ── Right panel — workflow video ──────────────────────────────── */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-slate-900">

        {/* Video — drop demo-video.mp4 into public/ to activate */}
        <video
          autoPlay
          loop
          muted
          playsInline
          className="absolute inset-0 w-full h-full object-cover opacity-40"
          src="/demo-video.mp4"
        />

        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-br from-blue-900/80 via-slate-900/60 to-slate-900/90" />

        {/* Content */}
        <div className="relative z-10 flex flex-col justify-between p-12 w-full">

          {/* Top — brand */}
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-white/10 backdrop-blur rounded-lg flex items-center justify-center">
              <GraduationCap className="w-4 h-4 text-white" />
            </div>
            <span className="text-white font-semibold tracking-tight">Shiken</span>
          </div>

          {/* Middle — headline */}
          <div>
            <h2 className="text-3xl font-bold text-white leading-snug mb-3">
              Generate question papers<br />in minutes, not hours
            </h2>
            <p className="text-slate-300 text-sm leading-relaxed mb-8 max-w-sm">
              Upload your materials, pick a blueprint, and let AI build a print-ready paper — aligned to your syllabus.
            </p>

            <ul className="space-y-3">
              {FEATURES.map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-md bg-blue-500/20 flex items-center justify-center shrink-0">
                    <Icon className="w-3.5 h-3.5 text-blue-300" />
                  </div>
                  <span className="text-slate-300 text-sm">{text}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Bottom — social proof */}
          <p className="text-slate-500 text-xs">
            Trusted by schools across India · Free plan available
          </p>
        </div>
      </div>

    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
      </div>
    }>
      <LoginForm />
    </Suspense>
  );
}
