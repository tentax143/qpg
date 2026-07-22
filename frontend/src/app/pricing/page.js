'use client';

import Link from 'next/link';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { BadgeCheck, ArrowRight, ArrowLeft } from 'lucide-react';
import { DM_Sans, Playfair_Display } from 'next/font/google';

/* ─── Fonts ─────────────────────────────────────────────── */
const display = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-display',
  weight: ['600', '700', '800'],
});

const body = DM_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  weight: ['400', '500', '600', '700'],
});

/* ─── Ease ───────────────────────────────────────────────── */
const EASE = [0.16, 1, 0.3, 1];

const PRICING = [
  {
    tier: 'Trial',
    price: 'Free',
    desc: 'Perfect for teachers testing the platform.',
    features: [
      'Generate up to 5 papers',
      'Basic blueprint creation',
      'Export to PDF',
      'Standard support'
    ],
    button: 'Start Free',
    accent: '#9c9590'
  },
  {
    tier: 'School',
    price: '$99/mo',
    desc: 'For single campuses wanting strict standardisation.',
    features: [
      'Unlimited generation',
      'Upload 10 textbooks',
      'Team review workflows',
      'Role-based access'
    ],
    button: 'Upgrade School',
    accent: '#c9b99a',
    popular: true
  },
  {
    tier: 'Institutional',
    price: 'Custom',
    desc: 'For school chains and large educational groups.',
    features: [
      'Unlimited vector stores',
      'Multi-campus sharing',
      'Custom API access',
      'Dedicated success manager'
    ],
    button: 'Contact Sales',
    accent: '#0f0e0d'
  }
];

/* ─── Pricing Card (Premium) ───────────────────────────── */
function PricingCard({ plan, i }) {
  const [hovered, setHovered] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 40, scale: 0.95 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.8, delay: i * 0.1, ease: EASE }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="landing-card-shine"
      style={{
        position: 'relative',
        padding: '3rem 2.5rem',
        borderRadius: 32,
        backgroundColor: plan.popular ? '#ffffff' : '#faf9f7',
        backgroundImage: hovered
          ? `linear-gradient(135deg, rgba(255,255,255,1), ${plan.accent}15)`
          : `linear-gradient(135deg, rgba(255,255,255,0.8), transparent)`,
        border: plan.popular ? `2px solid ${plan.accent}80` : '1px solid #e8e5e0',
        boxShadow: hovered 
          ? `0 30px 60px rgba(15,14,13,0.08), 0 0 0 4px ${plan.accent}20` 
          : plan.popular 
            ? '0 20px 40px rgba(0,0,0,0.06)' 
            : '0 4px 12px rgba(0,0,0,0.03)',
        display: 'flex',
        flexDirection: 'column',
        transform: hovered ? 'translateY(-8px)' : 'translateY(0)',
        transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)',
        overflow: 'hidden',
        zIndex: hovered ? 10 : 1,
      }}
    >
      {/* Background glow accent on hover */}
      <div style={{
        position: 'absolute',
        top: 0, right: 0,
        width: '150px', height: '150px',
        background: `radial-gradient(circle, ${plan.accent}40 0%, transparent 70%)`,
        opacity: hovered ? 1 : 0,
        transition: 'opacity 0.6s ease',
        transform: 'translate(30%, -30%)',
        pointerEvents: 'none',
      }} />

      {plan.popular && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          background: `linear-gradient(90deg, ${plan.accent}, #0f0e0d)`,
          color: '#fff',
          padding: '0.4rem 1.2rem',
          borderRadius: '0 0 12px 12px',
          fontSize: '0.75rem',
          fontWeight: 800,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          fontFamily: 'var(--font-body)',
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
        }}>
          Most Popular
        </div>
      )}
      
      <div style={{ marginBottom: '2.5rem', position: 'relative', zIndex: 2 }}>
        <h3 style={{ 
          fontFamily: 'var(--font-body)', 
          fontSize: '1rem', 
          fontWeight: 700, 
          color: plan.accent, 
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: '1rem' 
        }}>
          {plan.tier}
        </h3>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.25rem', marginBottom: '1rem' }}>
          <span style={{ 
            fontSize: '3.5rem', 
            fontWeight: 800, 
            fontFamily: 'var(--font-display)', 
            color: '#0f0e0d', 
            letterSpacing: '-0.04em',
            lineHeight: 1
          }}>
            {plan.price}
          </span>
        </div>
        <p style={{ fontSize: '1rem', color: '#6b6560', lineHeight: 1.6, fontFamily: 'var(--font-body)' }}>
          {plan.desc}
        </p>
      </div>

      <ul style={{ listStyle: 'none', padding: 0, margin: 0, marginBottom: '3rem', flexGrow: 1, position: 'relative', zIndex: 2 }}>
        {plan.features.map((f, idx) => (
          <motion.li 
            key={f}
            initial={false}
            animate={{ x: hovered ? 4 : 0 }}
            transition={{ duration: 0.4, delay: idx * 0.05, ease: EASE }}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '1rem', 
              marginBottom: '1.25rem', 
              fontSize: '1rem', 
              color: '#3b3530', 
              fontWeight: 500,
              fontFamily: 'var(--font-body)' 
            }}
          >
            <span style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 24, height: 24,
              borderRadius: '50%',
              background: `${plan.accent}20`,
              color: plan.accent
            }}>
              <BadgeCheck size={14} strokeWidth={3} />
            </span>
            {f}
          </motion.li>
        ))}
      </ul>

      <Link
        href="/login"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '0.5rem',
          padding: '1.25rem',
          borderRadius: 16,
          background: plan.popular ? '#0f0e0d' : '#ffffff',
          border: plan.popular ? 'none' : '1px solid #e8e5e0',
          color: plan.popular ? '#ffffff' : '#0f0e0d',
          fontWeight: 700,
          fontSize: '1rem',
          fontFamily: 'var(--font-body)',
          textDecoration: 'none',
          transition: 'all 0.3s ease',
          boxShadow: plan.popular ? '0 10px 20px rgba(15,14,13,0.15)' : '0 2px 8px rgba(0,0,0,0.02)',
          position: 'relative',
          zIndex: 2,
        }}
        onMouseOver={e => {
          e.currentTarget.style.transform = 'translateY(-2px)';
          e.currentTarget.style.boxShadow = plan.popular ? '0 15px 30px rgba(15,14,13,0.2)' : '0 10px 20px rgba(0,0,0,0.05)';
        }}
        onMouseOut={e => {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.boxShadow = plan.popular ? '0 10px 20px rgba(15,14,13,0.15)' : '0 2px 8px rgba(0,0,0,0.02)';
        }}
      >
        {plan.button}
        <ArrowRight size={16} />
      </Link>
    </motion.div>
  );
}

export default function PricingPage() {
  return (
    <div className={`${display.variable} ${body.variable}`} style={{ minHeight: '100vh', backgroundColor: '#fcfbf9' }}>
      
      {/* ══════════════════════════════════════════
          NAVBAR
      ══════════════════════════════════════════ */}
      <nav style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
        background: 'rgba(252, 251, 249, 0.8)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(0,0,0,0.04)',
      }}>
        <div style={{
          maxWidth: 1200, margin: '0 auto', padding: '1rem 1.5rem',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center'
        }}>
          
          <Link href="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 32, height: 32, borderRadius: 8,
              background: '#0f0e0d', color: '#fff'
            }}>
              <BadgeCheck size={18} strokeWidth={3} />
            </div>
            <span style={{
              fontSize: '1.25rem', fontWeight: 800, color: '#0f0e0d',
              letterSpacing: '-0.02em', fontFamily: 'var(--font-body)',
            }}>
              qForge AI
            </span>
          </Link>

          <Link
            href="/"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: '#0f0e0d',
              textDecoration: 'none',
              padding: '0.625rem 1rem',
              borderRadius: 999,
              transition: 'background 0.2s',
              fontFamily: 'var(--font-body)'
            }}
            onMouseOver={e => e.currentTarget.style.background = 'rgba(0,0,0,0.04)'}
            onMouseOut={e => e.currentTarget.style.background = 'transparent'}
          >
            <ArrowLeft size={16} />
            Back to Home
          </Link>
        </div>
      </nav>

      {/* ══════════════════════════════════════════
          PRICING HERO
      ══════════════════════════════════════════ */}
      <main style={{ paddingTop: '8rem', paddingBottom: '6rem' }}>
        <section style={{ maxWidth: 1100, margin: '0 auto', padding: '0 1.5rem' }}>
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.65, ease: EASE }}
            style={{ marginBottom: '4rem', textAlign: 'center' }}
          >
            <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '0.875rem' }}>
              Pricing
            </p>
            <h1 style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(2.5rem, 5vw, 4rem)',
              fontWeight: 700,
              color: '#0f0e0d',
              lineHeight: 1.1,
              letterSpacing: '-0.02em',
              marginBottom: '1.5rem'
            }}>
              Simple plans for schools of all sizes.
            </h1>
            <p style={{
              fontFamily: 'var(--font-body)',
              fontSize: '1.125rem',
              color: '#6b6560',
              maxWidth: 600,
              margin: '0 auto',
              lineHeight: 1.6
            }}>
              Whether you are an individual teacher testing the waters or a large institution requiring strict standardisation, we have a plan for you.
            </p>
          </motion.div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: '2.5rem',
            alignItems: 'stretch',
            padding: '2rem 0'
          }}>
            {PRICING.map((plan, i) => (
              <PricingCard key={plan.tier} plan={plan} i={i} />
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
