'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Eye, EyeOff, ArrowRight, AlertCircle, CheckCircle2, GraduationCap, Sparkles } from 'lucide-react';
import apiClient from '@/lib/api';
import { Playfair_Display, DM_Sans } from 'next/font/google';
import { motion, AnimatePresence } from 'framer-motion';

const serif = Playfair_Display({
  subsets: ['latin'],
  variable: '--l-serif',
  weight: ['700', '800'],
  style: ['normal', 'italic'],
});

const sans = DM_Sans({
  subsets: ['latin'],
  variable: '--l-sans',
  weight: ['400', '500', '600', '700'],
});

const EASE = [0.16, 1, 0.3, 1];

const staggerContainer = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.1 }
  }
};

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.8, ease: EASE } }
};

/* ─── Product UI Mockup ──────────────────────────────────── */
function ProductMockup() {
  return (
    <div style={{
      width: '100%',
      maxWidth: 580,
      background: 'rgba(255, 255, 255, 0.85)',
      backdropFilter: 'blur(20px)',
      border: '1px solid rgba(255, 255, 255, 0.6)',
      borderRadius: 24,
      overflow: 'hidden',
      boxShadow: '0 40px 100px rgba(15,14,13,0.15), inset 0 1px 0 rgba(255,255,255,0.9), 0 0 0 1px rgba(0,0,0,0.02)',
    }}>
      {/* Browser chrome */}
      <div style={{
        background: 'rgba(247, 245, 242, 0.7)',
        borderBottom: '1px solid rgba(236, 233, 228, 0.6)',
        padding: '14px 20px',
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <div style={{ display: 'flex', gap: 8 }}>
          {['#ff5f56','#ffbd2e','#27c93f'].map((c,i) => (
            <span key={i} style={{ width: 11, height: 11, borderRadius: '50%', background: c, boxShadow: `inset 0 0 2px rgba(0,0,0,0.1)` }} />
          ))}
        </div>
        <div style={{
          flex: 1, maxWidth: 260, margin: '0 auto',
          height: 26, background: '#ffffff',
          borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center',
          boxShadow: '0 1px 3px rgba(0,0,0,0.02), inset 0 1px 2px rgba(0,0,0,0.02)',
          border: '1px solid rgba(236, 233, 228, 0.6)'
        }}>
          <span style={{ fontSize: '0.6875rem', color: '#9c9590', fontFamily: 'var(--l-sans)', fontWeight: 500 }}>
            app.qforge.in / generator
          </span>
        </div>
      </div>

      {/* App UI */}
      <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', minHeight: 380 }}>
        {/* Sidebar */}
        <div style={{
          background: 'rgba(250, 249, 247, 0.5)',
          borderRight: '1px solid rgba(236, 233, 228, 0.6)',
          padding: '20px 14px',
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          <p style={{ fontSize: '0.55rem', fontWeight: 700, color: '#b0a99f', textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 12, fontFamily: 'var(--l-sans)', paddingLeft: 8 }}>
            Workspace
          </p>
          {[
            { label: 'Blueprints',  active: false },
            { label: 'Generator',   active: true  },
            { label: 'My Papers',   active: false },
            { label: 'Materials',   active: false },
            { label: 'Team',        active: false },
          ].map(({ label, active }) => (
            <div key={label} style={{
              padding: '9px 12px', borderRadius: 10,
              background: active ? '#0f0e0d' : 'transparent',
              fontSize: '0.8125rem',
              fontWeight: active ? 600 : 500,
              color: active ? '#fff' : '#7a756f',
              fontFamily: 'var(--l-sans)', cursor: 'default',
              transition: 'all 0.2s ease'
            }}>
              {label}
            </div>
          ))}
          <div style={{ flex: 1 }} />
          <div style={{ padding: '12px', background: '#fff', borderRadius: 14, border: '1px solid rgba(236, 233, 228, 0.8)', boxShadow: '0 4px 12px rgba(0,0,0,0.02)' }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg, #f3e6cd, #e8d5b7)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: 700, color: '#7a5c30', marginBottom: 8, boxShadow: '0 2px 5px rgba(0,0,0,0.05)' }}>M</div>
            <p style={{ fontSize: '0.6875rem', fontWeight: 600, color: '#0f0e0d', fontFamily: 'var(--l-sans)', margin: 0 }}>Meera Singh</p>
            <p style={{ fontSize: '0.625rem', color: '#9c9590', fontFamily: 'var(--l-sans)', margin: 0, marginTop: 2 }}>Coordinator</p>
          </div>
        </div>

        {/* Main */}
        <div style={{ padding: '24px 20px', display: 'flex', flexDirection: 'column', gap: 14, background: '#ffffff' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <p style={{ fontSize: '0.55rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.15em', fontFamily: 'var(--l-sans)', marginBottom: 6, margin: 0 }}>Paper Generator</p>
              <h2 style={{ fontSize: '1.125rem', fontWeight: 800, color: '#0f0e0d', letterSpacing: '-0.03em', fontFamily: 'var(--l-sans)', margin: 0 }}>
                Class X Maths — Final Term
              </h2>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <span style={{ padding: '4px 10px', background: '#dcfce7', borderRadius: 6, fontSize: '0.5625rem', fontWeight: 700, color: '#15803d', fontFamily: 'var(--l-sans)', border: '1px solid #bbf7d0' }}>Blueprint ✓</span>
              <span style={{ padding: '4px 10px', background: '#fef9ec', border: '1px solid #fde68a', borderRadius: 6, fontSize: '0.5625rem', fontWeight: 700, color: '#92400e', fontFamily: 'var(--l-sans)' }}>Draft</span>
            </div>
          </div>

          {/* Section tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10 }}>
            {[
              { s: 'Section A', d: '10 × 1 mark',  bg: '#fcfaf7', border: '#e8e5e0' },
              { s: 'Section B', d: '6 × 5 marks',  bg: '#f9fcfb', border: '#e0f0eb' },
              { s: 'Section C', d: '3 × 10 marks', bg: '#fdfbfa', border: '#f7ede6' },
            ].map(({ s, d, bg, border }) => (
              <div key={s} style={{ background: bg, border: `1px solid ${border}`, borderRadius: 12, padding: '12px', boxShadow: '0 2px 6px rgba(0,0,0,0.01)' }}>
                <p style={{ fontSize: '0.5rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--l-sans)', marginBottom: 4, margin: 0 }}>{s}</p>
                <p style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#0f0e0d', fontFamily: 'var(--l-sans)', margin: 0 }}>{d}</p>
              </div>
            ))}
          </div>

          {/* Coverage bars */}
          <div style={{ background: 'rgba(247, 245, 242, 0.4)', border: '1px solid rgba(236, 233, 228, 0.8)', borderRadius: 12, padding: '14px' }}>
            <p style={{ fontSize: '0.55rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.15em', fontFamily: 'var(--l-sans)', marginBottom: 12 }}>Chapter Coverage</p>
            {[['Algebra', 92], ['Geometry', 86], ['Statistics', 74]].map(([ch, pct]) => (
              <div key={ch} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                  <span style={{ fontSize: '0.6875rem', color: '#7a756f', fontWeight: 500, fontFamily: 'var(--l-sans)' }}>{ch}</span>
                  <span style={{ fontSize: '0.6875rem', color: '#0f0e0d', fontWeight: 700, fontFamily: 'var(--l-sans)' }}>{pct}%</span>
                </div>
                <div style={{ height: 4, background: '#e2ddd7', borderRadius: 999, overflow: 'hidden' }}>
                  <motion.div 
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 1.5, delay: 0.5, ease: EASE }}
                    style={{ height: '100%', background: 'linear-gradient(90deg, #0f0e0d, #3b3530)', borderRadius: 999 }} 
                  />
                </div>
              </div>
            ))}
          </div>

          {/* AI suggestion */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12,
            background: 'linear-gradient(135deg, #fffbf4, #fef5e7)', 
            border: '1px solid rgba(245, 230, 200, 0.8)',
            borderRadius: 12, padding: '12px 14px',
            boxShadow: '0 4px 12px rgba(212, 175, 55, 0.05)'
          }}>
            <div style={{ background: '#fef1dc', padding: 6, borderRadius: 8 }}>
              <Sparkles size={14} style={{ color: '#d97706', flexShrink: 0 }} />
            </div>
            <p style={{ fontSize: '0.6875rem', color: '#92400e', fontWeight: 500, lineHeight: 1.5, fontFamily: 'var(--l-sans)', flex: 1, margin: 0 }}>
              Replace 2 recall questions with application-based prompts from Algebra Ch. 3.
            </p>
            <motion.button 
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              style={{ padding: '6px 12px', background: '#0f0e0d', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: '0.625rem', fontWeight: 700, fontFamily: 'var(--l-sans)', whiteSpace: 'nowrap', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
              Apply
            </motion.button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Login Form ─────────────────────────────────────────── */
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
    setFormData(prev => ({ ...prev, [e.target.name]: e.target.value }));
    setError(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!formData.username || !formData.password) {
      setError('Please enter both username and password.');
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
      setSuccess('Login successful! Redirecting…');
      const dest = userData?.require_password_change
        ? '/change-password'
        : (userData?.role === 'superadmin' ? '/superadmin' : '/dashboard');
      setTimeout(() => { window.location.href = dest; }, 900);
    } catch (err) {
      const msg = err.response?.data?.detail ||
        err.response?.data?.non_field_errors?.[0] ||
        'Invalid username or password.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={`${serif.variable} ${sans.variable}`}
      style={{
        minHeight: '100vh',
        background: '#faf9f7',
        fontFamily: 'var(--l-sans)',
        display: 'flex',
        overflow: 'hidden',
      }}
    >
      {/* ══════════════════ LEFT — headline + form ══════════════════ */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '3rem 2rem 3rem 6vw', /* Added left padding to push content towards middle */
        borderRight: '1px solid rgba(0,0,0,0.06)',
        position: 'relative',
        zIndex: 10,
        background: '#ffffff',
      }}>
        {/* Subtle background glow on left */}
        <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', background: 'radial-gradient(circle at 0% 0%, rgba(201,169,110,0.05) 0%, transparent 50%)', pointerEvents: 'none' }} />

        <motion.div 
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          style={{ width: '100%', maxWidth: 420, position: 'relative', zIndex: 2 }}
        >
          {/* Logo */}
          <motion.div variants={fadeUp} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: '3rem' }}>
            <div style={{ width: 32, height: 32, background: 'linear-gradient(135deg, #1f1d1b, #0f0e0d)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(15,14,13,0.1)' }}>
              <GraduationCap size={16} style={{ color: '#faf9f7' }} />
            </div>
            <span style={{ fontSize: '1.125rem', fontWeight: 800, color: '#0f0e0d', letterSpacing: '-0.02em' }}>
              qForge AI
            </span>
          </motion.div>

          {/* Headline */}
          <motion.h1 variants={fadeUp} style={{
            fontFamily: 'var(--l-serif)',
            fontStyle: 'italic',
            fontWeight: 800,
            fontSize: 'clamp(2.5rem, 5vw, 3.75rem)',
            lineHeight: 1.05,
            letterSpacing: '-0.03em',
            color: '#0f0e0d',
            marginBottom: '1rem',
          }}>
            Build papers,<br />
            exam ready.
          </motion.h1>

          {/* Subtitle */}
          <motion.p variants={fadeUp} style={{
            fontSize: '1rem',
            color: '#6b6560',
            lineHeight: 1.6,
            marginBottom: '2.5rem',
          }}>
            Blueprint-first, AI-assisted,{' '}
            <span style={{ color: '#b68e45', fontWeight: 600 }}>built with qForge AI.</span>
          </motion.p>

          {/* Form card */}
          <motion.div variants={fadeUp} style={{
            background: '#ffffff',
            border: '1px solid rgba(0,0,0,0.06)',
            borderRadius: 20,
            padding: '2rem',
            boxShadow: '0 10px 40px rgba(15,14,13,0.04), 0 2px 10px rgba(15,14,13,0.02)',
            display: 'flex', flexDirection: 'column', gap: '1rem',
          }}>
            <AnimatePresence>
              {error && (
                <motion.div initial={{ opacity: 0, y: -10, height: 0 }} animate={{ opacity: 1, y: 0, height: 'auto' }} exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 12, padding: '0.875rem' }}>
                    <AlertCircle size={16} style={{ color: '#ef4444', flexShrink: 0, marginTop: 2 }} />
                    <p style={{ fontSize: '0.875rem', color: '#b91c1c', margin: 0, lineHeight: 1.5 }}>{error}</p>
                  </div>
                </motion.div>
              )}
              {success && (
                <motion.div initial={{ opacity: 0, y: -10, height: 0 }} animate={{ opacity: 1, y: 0, height: 'auto' }} exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 12, padding: '0.875rem' }}>
                    <CheckCircle2 size={16} style={{ color: '#16a34a', flexShrink: 0, marginTop: 2 }} />
                    <p style={{ fontSize: '0.875rem', color: '#15803d', margin: 0, lineHeight: 1.5 }}>{success}</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              
              {/* Username */}
              <div className="input-group" style={{ position: 'relative' }}>
                <input
                  type="text"
                  name="username"
                  autoComplete="username"
                  placeholder="Username"
                  value={formData.username}
                  onChange={handleChange}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '1rem 1.25rem',
                    background: '#faf9f7',
                    border: '1px solid #e2ddd7',
                    borderRadius: 12,
                    fontSize: '1rem',
                    color: '#0f0e0d',
                    outline: 'none',
                    fontFamily: 'var(--l-sans)',
                    transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                  onFocus={e => { e.target.style.background = '#ffffff'; e.target.style.borderColor = '#0f0e0d'; e.target.style.boxShadow = '0 4px 12px rgba(15,14,13,0.05), 0 0 0 3px rgba(15,14,13,0.05)'; }}
                  onBlur={e => { e.target.style.background = '#faf9f7'; e.target.style.borderColor = '#e2ddd7'; e.target.style.boxShadow = 'none'; }}
                />
              </div>

              {/* Password */}
              <div className="input-group" style={{ position: 'relative' }}>
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  autoComplete="current-password"
                  placeholder="Password"
                  value={formData.password}
                  onChange={handleChange}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '1rem 3rem 1rem 1.25rem',
                    background: '#faf9f7',
                    border: '1px solid #e2ddd7',
                    borderRadius: 12,
                    fontSize: '1rem',
                    color: '#0f0e0d',
                    outline: 'none',
                    fontFamily: 'var(--l-sans)',
                    transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                  onFocus={e => { e.target.style.background = '#ffffff'; e.target.style.borderColor = '#0f0e0d'; e.target.style.boxShadow = '0 4px 12px rgba(15,14,13,0.05), 0 0 0 3px rgba(15,14,13,0.05)'; }}
                  onBlur={e => { e.target.style.background = '#faf9f7'; e.target.style.borderColor = '#e2ddd7'; e.target.style.boxShadow = 'none'; }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  style={{
                    position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: '#9c9590', padding: 6, borderRadius: 8,
                    display: 'flex', alignItems: 'center', transition: 'all 0.2s',
                  }}
                  onMouseOver={e => { e.currentTarget.style.color = '#0f0e0d'; e.currentTarget.style.background = 'rgba(0,0,0,0.04)'; }}
                  onMouseOut={e => { e.currentTarget.style.color = '#9c9590'; e.currentTarget.style.background = 'none'; }}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>

              {/* Submit */}
              <motion.button
                whileHover={!loading ? { scale: 1.02, backgroundColor: '#2a2826' } : {}}
                whileTap={!loading ? { scale: 0.98 } : {}}
                type="submit"
                disabled={loading}
                style={{
                  width: '100%',
                  marginTop: '0.5rem',
                  padding: '1rem',
                  background: loading ? '#d4d0cb' : '#0f0e0d',
                  color: '#faf9f7',
                  border: 'none',
                  borderRadius: 12,
                  fontSize: '1rem',
                  fontWeight: 700,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
                  fontFamily: 'var(--l-sans)',
                  letterSpacing: '-0.01em',
                  boxShadow: '0 8px 24px rgba(15,14,13,0.15)',
                  transition: 'background-color 0.2s',
                }}
              >
                {loading
                  ? <div style={{ width: 20, height: 20, border: '2.5px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'lSpin 0.7s linear infinite' }} />
                  : <><ArrowRight size={18} /> Continue securely</>
                }
              </motion.button>
            </form>
          </motion.div>

          {/* Board strip */}
          <motion.div variants={fadeUp} style={{ marginTop: '2.5rem', width: '100%' }}>
            <p style={{ fontSize: '0.75rem', fontWeight: 600, color: '#b0a99f', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: '1rem', textAlign: 'center' }}>
              Trusted by schools across India
            </p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
              {['CBSE', 'ICSE', 'IB', 'State Boards'].map(b => (
                <span key={b} style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#c9c3bb', letterSpacing: '0.05em', fontFamily: 'var(--l-sans)' }}>{b}</span>
              ))}
            </div>
          </motion.div>
        </motion.div>
      </div>

      {/* ══════════════════ RIGHT — product mockup ══════════════════ */}
      <div
        className="login-right-panel"
        style={{
          flex: 1,
          display: 'none',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '4rem',
          background: 'linear-gradient(135deg, #f7f5f2 0%, #ede8de 100%)',
          position: 'relative',
          overflow: 'hidden',
          perspective: 1200,
        }}
      >
        {/* Dynamic ambient glows */}
        <motion.div 
          animate={{ scale: [1, 1.1, 1], opacity: [0.4, 0.6, 0.4] }}
          transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut' }}
          style={{ position: 'absolute', top: '10%', right: '10%', width: '40vw', height: '40vw', background: 'radial-gradient(circle, rgba(182,142,69,0.15) 0%, transparent 60%)', borderRadius: '50%', pointerEvents: 'none' }} 
        />
        <motion.div 
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.5, 0.3] }}
          transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut', delay: 2 }}
          style={{ position: 'absolute', bottom: '-10%', left: '20%', width: '30vw', height: '30vw', background: 'radial-gradient(circle, rgba(15,14,13,0.08) 0%, transparent 70%)', borderRadius: '50%', pointerEvents: 'none' }} 
        />

        {/* Floating 3D product card */}
        <motion.div 
          initial={{ opacity: 0, x: 100, rotateY: -20, rotateX: 10, scale: 0.9 }}
          animate={{ 
            opacity: 1, 
            x: 0, 
            y: [-15, 15, -15],
            rotateY: -15, 
            rotateX: 10, 
            scale: 1 
          }}
          transition={{ 
            opacity: { duration: 1.2 },
            x: { duration: 1.2, ease: [0.16, 1, 0.3, 1] },
            scale: { duration: 1.2, ease: [0.16, 1, 0.3, 1] },
            y: { duration: 6, repeat: Infinity, ease: "easeInOut" },
            rotateY: { duration: 1.2, ease: [0.16, 1, 0.3, 1] },
            rotateX: { duration: 1.2, ease: [0.16, 1, 0.3, 1] },
          }}
          style={{ width: '100%', maxWidth: 580, zIndex: 10, transformStyle: 'preserve-3d' }}
        >
          <ProductMockup />
        </motion.div>

        {/* Bottom tagline */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8, duration: 1 }}
          style={{ position: 'absolute', bottom: '3rem', right: '3.5rem', textAlign: 'right', zIndex: 20 }}
        >
          <p style={{
            fontFamily: 'var(--l-serif)',
            fontStyle: 'italic',
            fontSize: '1.5rem',
            fontWeight: 800,
            color: '#0f0e0d',
            lineHeight: 1.2,
            letterSpacing: '-0.02em',
            marginBottom: '0.375rem',
          }}>
            Question papers,<br />
            <span style={{ color: '#b68e45' }}>built with clarity.</span>
          </p>
          <p style={{ fontSize: '0.8125rem', fontWeight: 500, color: '#7a756f', fontFamily: 'var(--l-sans)' }}>
            qForge AI · Blueprint-first AI exam platform
          </p>
        </motion.div>
      </div>

      {/* ── Styles ── */}
      <style>{`
        @keyframes lSpin  { to { transform: rotate(360deg); } }
        input::placeholder { color: #b0a99f; }
        input:-webkit-autofill,
        input:-webkit-autofill:hover,
        input:-webkit-autofill:focus {
          -webkit-box-shadow: 0 0 0 1000px #faf9f7 inset !important;
          -webkit-text-fill-color: #0f0e0d !important;
          caret-color: #0f0e0d;
          transition: background-color 5000s ease-in-out 0s;
        }
        @media (min-width: 900px) {
          .login-right-panel { display: flex !important; }
        }
      `}</style>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#faf9f7' }}>
        <div style={{ width: 24, height: 24, border: '3px solid #e2ddd7', borderTopColor: '#0f0e0d', borderRadius: '50%', animation: 'lSpin 0.7s linear infinite' }} />
        <style>{`@keyframes lSpin { to { transform: rotate(360deg); } }`}</style>
      </div>
    }>
      <LoginForm />
    </Suspense>
  );
}
