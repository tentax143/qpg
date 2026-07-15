'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, useInView, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from 'framer-motion';
import Lenis from 'lenis';
import BorderGlow from '../components/BorderGlow';
import {
  ArrowRight,
  BadgeCheck,
  Bot,
  ClipboardList,
  FileOutput,
  FileText,
  GraduationCap,
  Layers3,
  Minus,
  Orbit,
  Plus,
  Settings2,
  Sparkles,
  WandSparkles,
} from 'lucide-react';
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

/* ─── Content ────────────────────────────────────────────── */
const HEADLINE = 'Build exam papers with the power of AI.';
const SUBTITLE =
  'Shiken is a complete platform for schools to generate syllabus-aligned question papers directly from their own textbooks, with built-in team approvals and usage tracking.';

const STATS = [
  { value: '3', suffix: '×', label: 'Faster first draft' },
  { value: '0', suffix: '%', label: 'Blueprint drift' },
  { value: '1', suffix: '', label: 'Unified workflow' },
  { value: '∞', suffix: '', label: 'Version history' },
];

const SIGNALS = [
  'CBSE-ready',
  'Blueprint-first',
  'AI-assisted drafting',
  'Teacher review loop',
  'Role-secured access',
  'Version-tracked export',
];

const FEATURES = [
  {
    icon: ClipboardList,
    title: 'Blueprint-first setup',
    body: 'Start from marks, chapters, and section balance. The interface stays anchored to the blueprint so nothing slips.',
    accent: '#c9b99a',
  },
  {
    icon: WandSparkles,
    title: 'Grounded in Your Syllabus',
    body: 'Upload your school\'s textbooks and notes. The AI strictly generates questions from the exact materials you provide.',
    accent: '#b8a990',
  },
  {
    icon: Settings2,
    title: 'Review & Role Control',
    body: 'Teachers, coordinators, and principals operate with clear permissions and an automatic audit trail for every paper.',
    accent: '#a8c4b8',
  },
  {
    icon: Layers3,
    title: 'Multi-Campus Sharing',
    body: 'Running multiple branches? Easily share approved question banks and test patterns across all your schools.',
    accent: '#c4b098',
  },
  {
    icon: FileOutput,
    title: 'Section Intelligence',
    body: 'Marks and chapter logic stay visible at all times, ensuring the AI never silently breaks your exam structure.',
    accent: '#b0c4d8',
  },
  {
    icon: Bot,
    title: 'Smart AI Budgets',
    body: 'Keep your school\'s usage in check. Admins can track token costs and set generation budgets for different departments.',
    accent: '#d4b898',
  },
];

const HOW_IT_WORKS = [
  {
    step: '01',
    title: 'Upload your syllabus',
    body: 'Provide your school\'s textbooks, notes, and past papers. The AI learns your exact curriculum.',
  },
  {
    step: '02',
    title: 'Define the blueprint',
    body: 'Set sections, marks, and chapter distribution. This acts as the strict rulebook for your exam.',
  },
  {
    step: '03',
    title: 'Generate & Refine',
    body: 'Shiken produces a draft instantly. Swap out any question you don\'t like without breaking the total marks.',
  },
  {
    step: '04',
    title: 'Review & Export',
    body: 'Coordinators approve the final paper. Export it with confidence, knowing every change was tracked.',
  },
];

const FAQ = [
  {
    q: 'Who is Shiken built for?',
    a: 'Shiken is built for schools — teachers, subject coordinators, academic admins, and principals who deal with question paper creation at scale.',
  },
  {
    q: 'Does the AI generate out-of-syllabus questions?',
    a: 'No. Because you upload your own textbooks and materials, Shiken only suggests questions grounded strictly in your school\'s exact curriculum.',
  },
  {
    q: 'What happens if the AI generates a weak question?',
    a: 'You can individually swap, edit, or regenerate any question without touching the rest of the paper. Section totals recalculate in real time.',
  },
  {
    q: 'Can we share question banks across different branches?',
    a: 'Yes. Superadmins can link schools and deploy shared repositories across multiple campuses to maintain a unified standard of testing.',
  },
  {
    q: 'How is pricing and AI usage managed?',
    a: 'Admins assign roles and can set generation budgets per school or department. You can easily track token usage and control costs directly from the dashboard.',
  },
];



/* ─── Ease ───────────────────────────────────────────────── */
const EASE = [0.16, 1, 0.3, 1];

/* ─── Count-up hook ──────────────────────────────────────── */
function useCountUp(end, duration = 1.6, isInView) {
  const [count, setCount] = useState(0);
  const hasRun = useRef(false);

  useEffect(() => {
    if (!isInView || hasRun.current) return;
    if (end === '∞') { setCount('∞'); hasRun.current = true; return; }

    const target = parseInt(end, 10);
    if (isNaN(target)) { setCount(end); hasRun.current = true; return; }

    hasRun.current = true;
    const startTime = performance.now();

    function tick(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / (duration * 1000), 1);
      // ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }, [end, duration, isInView]);

  return count;
}

/* ─── FAQ Item ───────────────────────────────────────────── */
function FaqItem({ item, index }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay: index * 0.06, ease: EASE }}
      style={{ borderBottom: '1px solid #e8e5e0' }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '1.5rem 0',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          gap: 16,
          fontFamily: 'var(--font-body)',
        }}
      >
        <span style={{ fontSize: '1rem', fontWeight: 600, color: '#0f0e0d', lineHeight: 1.4 }}>
          {item.q}
        </span>
        <span style={{
          width: 28, height: 28, borderRadius: '50%',
          border: '1px solid #e2ddd7',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
          transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
          background: open ? '#0f0e0d' : 'transparent',
          color: open ? '#fff' : '#888',
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
        }}>
          {open ? <Minus size={13} /> : <Plus size={13} />}
        </span>
      </button>
      <motion.div
        initial={false}
        animate={{ height: open ? 'auto' : 0, opacity: open ? 1 : 0 }}
        transition={{ duration: 0.35, ease: EASE }}
        style={{ overflow: 'hidden' }}
      >
        <p style={{
          fontSize: '0.9375rem',
          color: '#6b6560',
          lineHeight: 1.75,
          paddingBottom: '1.5rem',
          fontFamily: 'var(--font-body)',
          maxWidth: 640,
        }}>
          {item.a}
        </p>
      </motion.div>
    </motion.div>
  );
}



/* ─── Feature Card (Premium) ─────────────────────────────── */
function FeatureCard({ item, index }) {
  const Icon = item.icon;
  const cardRef = useRef(null);
  const [hovered, setHovered] = useState(false);

  const handleMouseMove = useCallback((e) => {
    const card = cardRef.current;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    card.style.setProperty('--spotlight-x', `${x}%`);
    card.style.setProperty('--spotlight-y', `${y}%`);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 40, scale: 0.95, filter: 'blur(8px)' }}
      whileInView={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.8, delay: index * 0.1, ease: EASE }}
      className="h-full"
    >
      <BorderGlow
        backgroundColor="#ffffff"
        borderRadius={20}
        glowRadius={30}
        edgeSensitivity={40}
        coneSpread={30}
        glowIntensity={0.6}
        glowColor="40 40 70"
        colors={[item.accent, '#f7f5f2', item.accent]}
        className="h-full"
      >
        <div
          ref={cardRef}
          className="landing-card-spotlight landing-card-shine"
          onMouseMove={handleMouseMove}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            padding: '2rem',
            borderRadius: 20,
            backgroundColor: 'transparent',
            backgroundImage: hovered
              ? `linear-gradient(135deg, rgba(255,255,255,0.95), ${item.accent}15)`
              : `linear-gradient(135deg, ${item.accent}08, transparent)`,
            backdropFilter: hovered ? 'blur(12px)' : 'none',
            cursor: 'default',
            height: '100%',
            transition: 'background 0.4s ease, transform 0.4s cubic-bezier(0.16,1,0.3,1)',
            transform: hovered ? 'translateY(-4px)' : 'translateY(0)',
          }}
        >
      <div style={{
        width: 44, height: 44,
        borderRadius: 13,
        background: hovered
          ? `linear-gradient(135deg, ${item.accent}30, ${item.accent}15)`
          : '#f7f5f2',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginBottom: '1.25rem',
        color: '#0f0e0d',
        transition: 'all 0.4s ease',
        transform: hovered ? 'scale(1.08) rotate(-3deg)' : 'scale(1) rotate(0deg)',
        position: 'relative',
        zIndex: 2,
      }}>
        <Icon size={19} strokeWidth={1.6} />
      </div>
      <h3 style={{
        fontSize: '0.9375rem',
        fontWeight: 700,
        color: '#0f0e0d',
        marginBottom: '0.625rem',
        fontFamily: 'var(--font-body)',
        letterSpacing: '-0.01em',
        position: 'relative',
        zIndex: 2,
      }}>
        {item.title}
      </h3>
      <p style={{
        fontSize: '0.875rem',
        color: hovered ? '#5a5550' : '#7a756f',
        lineHeight: 1.72,
        fontFamily: 'var(--font-body)',
        transition: 'color 0.3s ease',
        position: 'relative',
        zIndex: 2,
      }}>
        {item.body}
      </p>
        </div>
      </BorderGlow>
    </motion.div>
  );
}

/* ─── Stat Chip (Count-up) ───────────────────────────────── */
function StatChip({ item, index }) {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, amount: 0.5 });
  const count = useCountUp(item.value, 1.4, isInView);
  const [hovered, setHovered] = useState(false);

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.4 }}
      transition={{ duration: 0.6, delay: index * 0.1, ease: EASE }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '1.75rem 1.5rem',
        border: '1px solid #ece9e4',
        borderRadius: 18,
        background: '#fff',
        textAlign: 'center',
        cursor: 'default',
        transition: 'all 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        transform: hovered ? 'translateY(-4px) scale(1.02)' : 'translateY(0) scale(1)',
        boxShadow: hovered
          ? '0 16px 48px rgba(15,14,13,0.07), 0 2px 8px rgba(15,14,13,0.03)'
          : '0 1px 3px rgba(15,14,13,0.02)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Gradient accent line at top */}
      <div style={{
        position: 'absolute',
        top: 0, left: '15%', right: '15%',
        height: 2,
        background: 'linear-gradient(90deg, transparent, #c9b99a, transparent)',
        opacity: hovered ? 1 : 0.3,
        transition: 'opacity 0.4s ease',
        borderRadius: 999,
      }} />
      <div style={{
        fontSize: '2.5rem',
        fontWeight: 800,
        color: '#0f0e0d',
        letterSpacing: '-0.04em',
        lineHeight: 1,
        fontFamily: 'var(--font-display)',
        marginBottom: '0.625rem',
        transition: 'transform 0.3s ease',
        transform: isInView && count !== 0 ? 'scale(1)' : 'scale(0.8)',
      }}>
        {count}{item.suffix}
      </div>
      <div style={{
        fontSize: '0.8125rem',
        color: '#9c9590',
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        fontWeight: 600,
        fontFamily: 'var(--font-body)',
      }}>
        {item.label}
      </div>
    </motion.div>
  );
}

/* ─── How It Works (Flow Timeline) ────────────────────────── */
/* This component is no longer needed — the timeline is rendered inline */

/* ─── Role Card (Dark Section) ───────────────────────────── */
function RoleCard({ role, desc, icon, index }) {
  const [hovered, setHovered] = useState(false);

  // Assign a subtle accent color based on index for the glow effect
  const accents = ['#c084fc', '#38bdf8', '#f472b6', '#fbbf24'];
  const accent = accents[index % accents.length];

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.2 }}
      transition={{ duration: 0.8, delay: index * 0.1, ease: EASE }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative',
        padding: '2.5rem 2rem',
        background: 'rgba(255,255,255,0.02)',
        backgroundImage: hovered 
          ? `linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0))` 
          : 'none',
        border: '1px solid rgba(255,255,255,0.06)',
        boxShadow: hovered 
          ? `0 20px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1), 0 0 20px ${accent}20` 
          : '0 10px 20px rgba(0,0,0,0.2)',
        borderRadius: 24,
        cursor: 'default',
        display: 'flex',
        flexDirection: 'column',
        transform: hovered ? 'translateY(-6px)' : 'translateY(0)',
        transition: 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)',
        overflow: 'hidden',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Background radial glow */}
      <div style={{
        position: 'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        background: `radial-gradient(circle at 50% 0%, ${accent}15 0%, transparent 60%)`,
        opacity: hovered ? 1 : 0,
        transition: 'opacity 0.7s ease',
        pointerEvents: 'none',
        zIndex: 0,
      }} />

      <div style={{
        position: 'relative',
        zIndex: 1,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 48,
        height: 48,
        borderRadius: 14,
        background: hovered ? `${accent}20` : 'rgba(255,255,255,0.05)',
        border: hovered ? `1px solid ${accent}40` : '1px solid rgba(255,255,255,0.1)',
        fontSize: '1.5rem',
        marginBottom: '1.5rem',
        transition: 'all 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        transform: hovered ? 'scale(1.1)' : 'scale(1)',
      }}>
        {icon}
      </div>
      
      <h3 style={{
        position: 'relative',
        zIndex: 1,
        fontFamily: 'var(--font-body)',
        fontSize: '1.125rem',
        fontWeight: 700,
        color: '#ffffff',
        marginBottom: '0.75rem',
        letterSpacing: '-0.01em',
      }}>
        {role}
      </h3>
      
      <p style={{
        position: 'relative',
        zIndex: 1,
        fontSize: '0.9375rem',
        color: hovered ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.45)',
        lineHeight: 1.6,
        fontFamily: 'var(--font-body)',
        transition: 'color 0.4s ease',
      }}>
        {desc}
      </p>
    </motion.div>
  );
}


/*  ──────────────────────────────────────────────────────────
    MAIN PAGE
    ────────────────────────────────────────────────────────── */
export default function RootPage() {
  const reduceMotion = useReducedMotion();
  const [scrolled, setScrolled] = useState(false);
  const [headlineReady, setHeadlineReady] = useState(false);
  const heroRef = useRef(null);
  const bentoRef = useRef(null);
  const words = useMemo(() => HEADLINE.split(' '), []);

  /* ── Lenis smooth scroll ──────────────── */
  useEffect(() => {
    if (reduceMotion) return;
    const lenis = new Lenis({
      duration: 1.15,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      orientation: 'vertical',
      gestureOrientation: 'vertical',
      smoothWheel: true,
    });
    function raf(time) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
    return () => lenis.destroy();
  }, [reduceMotion]);

  /* ── Scroll state ─────────────────────── */
  useEffect(() => {
    const tick = () => setScrolled(window.scrollY > 20);
    tick();
    window.addEventListener('scroll', tick, { passive: true });
    return () => window.removeEventListener('scroll', tick);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setHeadlineReady(true), 80);
    return () => clearTimeout(t);
  }, []);

  /* ── Parallax values ──────────────────── */
  const { scrollYProgress: heroScrollProgress } = useScroll({
    target: heroRef,
    offset: ['start start', 'end start'],
  });
  const heroParallaxY = useTransform(heroScrollProgress, [0, 1], [0, -80]);
  const heroSubtitleParallaxY = useTransform(heroScrollProgress, [0, 1], [0, -40]);
  const heroOpacity = useTransform(heroScrollProgress, [0, 0.6], [1, 0]);

  /* ── Bento parallax ───────────────────── */
  const { scrollYProgress: bentoScrollProgress } = useScroll({
    target: bentoRef,
    offset: ['start end', 'end start'],
  });
  const bentoRotateX = useTransform(bentoScrollProgress, [0, 0.5, 1], [3, 0, -2]);
  const bentoScale = useTransform(bentoScrollProgress, [0, 0.5], [0.96, 1]);

  return (
    <div
      className={`${display.variable} ${body.variable}`}
      style={{
        minHeight: '100vh',
        background: '#faf9f7',
        color: '#0f0e0d',
        fontFamily: 'var(--font-body)',
        overflowX: 'hidden',
      }}
    >

      {/* ══════════════════════════════════════════    NAV   ═════════════════════════════════════════ */}
      <div style={{
        position: 'fixed', top: '1.5rem', left: '50%', transform: 'translateX(-50%)', zIndex: 100,
        width: 'fit-content',
        minWidth: 'min(640px, calc(100% - 2rem))',
        maxWidth: 'calc(100% - 2rem)',
      }}>
        <motion.nav
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          style={{
            padding: '0.5rem 0.75rem 0.5rem 1.5rem',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: scrolled ? 'rgba(250, 249, 247, 0.92)' : 'rgba(244, 242, 240, 0.95)',
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)',
            border: '1px solid rgba(0,0,0,0.03)',
            borderRadius: 999,
            boxShadow: scrolled
              ? '0 12px 40px rgba(15, 14, 13, 0.08), 0 2px 8px rgba(15, 14, 13, 0.03)'
              : '0 12px 32px rgba(15, 14, 13, 0.04), 0 2px 8px rgba(15, 14, 13, 0.02)',
            transition: 'all 0.4s ease',
            width: '100%',
          }}
        >
          <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6rem' }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <div style={{
              width: 28, height: 28,
              background: '#0f0e0d',
              borderRadius: 8,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <GraduationCap size={14} style={{ color: '#faf9f7' }} />
            </div>
            <span style={{
              fontSize: '1.0625rem',
              fontWeight: 800,
              color: '#0f0e0d',
              letterSpacing: '-0.025em',
              fontFamily: 'var(--font-body)',
            }}>
              Shiken
            </span>
          </div>

          {/* Nav actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
           

            <Link
              href="/#how"
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#0f0e0d',
                textDecoration: 'none',
                padding: '0.625rem 1rem',
                borderRadius: 999,
                transition: 'background 0.2s',
              }}
              onMouseOver={e => e.currentTarget.style.background = 'rgba(0,0,0,0.04)'}
              onMouseOut={e => e.currentTarget.style.background = 'transparent'}
            >
              How it works
            </Link>

            <Link
              href="/pricing"
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#0f0e0d',
                textDecoration: 'none',
                padding: '0.625rem 1rem',
                borderRadius: 999,
                transition: 'background 0.2s',
              }}
              onMouseOver={e => e.currentTarget.style.background = 'rgba(0,0,0,0.04)'}
              onMouseOut={e => e.currentTarget.style.background = 'transparent'}
            >
              Pricing
            </Link>

            <Link
              href="/login"
              style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: '#0f0e0d',
                textDecoration: 'none',
                padding: '0.625rem 1rem',
                borderRadius: 999,
                transition: 'background 0.2s',
              }}
              onMouseOver={e => e.currentTarget.style.background = 'rgba(0,0,0,0.04)'}
              onMouseOut={e => e.currentTarget.style.background = 'transparent'}
            >
              Log in
            </Link>
          </div>
        </div>
      </motion.nav>
    </div>

      <main style={{ paddingTop: 60 }}>

        {/* ══════════════════════════════════════════    HERO   ═════════════════════════════════════════ */}
        <section
          ref={heroRef}
          style={{
            maxWidth: 900,
            margin: '0 auto',
            padding: '5rem 1.5rem 4rem',
            textAlign: 'center',
            position: 'relative',
          }}
        >
          <div>
            <div>

              {/* Eyebrow */}
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.55, ease: EASE }}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  marginBottom: '1.75rem',
                  padding: '0.375rem 0.875rem',
                  background: '#f0ede8',
                  border: '1px solid #e2ddd7',
                  borderRadius: 999,
                }}
              >
                <Sparkles size={12} style={{ color: '#0f0e0d' }} />
                <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#5a5550', letterSpacing: '0.07em', textTransform: 'uppercase', fontFamily: 'var(--font-body)' }}>
                  AI-powered question paper generation
                </span>
              </motion.div>

              {/* Headline — word-by-word reveal with parallax */}
              <motion.h1
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 'clamp(3rem, 7vw, 5.5rem)',
                  fontWeight: 800,
                  lineHeight: 1.04,
                  letterSpacing: '-0.045em',
                  color: '#0f0e0d',
                  marginBottom: '1.75rem',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '0 0.22em',
                  justifyContent: 'center',
                  y: heroParallaxY,
                  opacity: heroOpacity,
                }}
              >
                {headlineReady && words.map((word, i) => (
                  <motion.span
                    key={i}
                    initial={{ opacity: 0, y: 30, filter: 'blur(6px)' }}
                    animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                    transition={{ duration: 0.7, delay: 0.1 + i * 0.055, ease: EASE }}
                    style={{ display: 'inline-block' }}
                  >
                    {/* Last two words get a lighter weight to add rhythm */}
                    <span style={{ color: i >= words.length - 3 ? '#c9b99a' : '#0f0e0d' }}>
                      {word}
                    </span>
                  </motion.span>
                ))}
              </motion.h1>

              {/* Subtitle with separate parallax rate */}
              <motion.p
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.7, delay: 0.65, ease: EASE }}
                style={{
                  fontSize: '1.125rem',
                  color: '#7a756f',
                  lineHeight: 1.8,
                  maxWidth: 600,
                  fontFamily: 'var(--font-body)',
                  marginBottom: '2.5rem',
                  margin: '0 auto 2.5rem',
                  y: heroSubtitleParallaxY,
                }}
              >
                {SUBTITLE}
              </motion.p>

              {/* CTAs */}
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.8, ease: EASE }}
                style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', justifyContent: 'center' }}
              >
                <Link
                  href="/login"
                  className="landing-cta-shimmer"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '0.875rem 1.75rem',
                    background: '#0f0e0d',
                    color: '#faf9f7',
                    fontSize: '0.9375rem',
                    fontWeight: 700,
                    borderRadius: 12,
                    textDecoration: 'none',
                    letterSpacing: '-0.01em',
                    fontFamily: 'var(--font-body)',
                    transition: 'background 0.2s, transform 0.15s, box-shadow 0.2s',
                  }}
                  onMouseOver={e => { e.currentTarget.style.background = '#2a2826'; e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 10px 28px rgba(15,14,13,0.14)'; }}
                  onMouseOut={e => { e.currentTarget.style.background = '#0f0e0d'; e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}
                >
                  Open workspace
                  <ArrowRight size={16} />
                </Link>

                <Link
                  href="#how"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '0.875rem 1.5rem',
                    background: 'transparent',
                    color: '#6b6560',
                    fontSize: '0.9375rem',
                    fontWeight: 600,
                    borderRadius: 12,
                    textDecoration: 'none',
                    border: '1px solid #e2ddd7',
                    transition: 'all 0.2s',
                    fontFamily: 'var(--font-body)',
                  }}
                  onMouseOver={e => { e.currentTarget.style.borderColor = '#c9b99a'; e.currentTarget.style.color = '#0f0e0d'; e.currentTarget.style.background = '#f7f5f2'; }}
                  onMouseOut={e => { e.currentTarget.style.borderColor = '#e2ddd7'; e.currentTarget.style.color = '#6b6560'; e.currentTarget.style.background = 'transparent'; }}
                >
                  <Orbit size={15} />
                  See how it works
                </Link>
              </motion.div>

              {/* Signal pills */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6, delay: 1.0, ease: EASE }}
                style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: '2rem', justifyContent: 'center' }}
              >
                {SIGNALS.map((s, i) => (
                  <motion.span
                    key={s}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.4, delay: 1.0 + i * 0.06, ease: EASE }}
                    style={{
                      padding: '0.3125rem 0.75rem',
                      background: '#f0ede8',
                      border: '1px solid #e8e5e0',
                      borderRadius: 999,
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      color: '#7a756f',
                      letterSpacing: '0.04em',
                      fontFamily: 'var(--font-body)',
                    }}
                  >
                    {s}
                  </motion.span>
                ))}
              </motion.div>
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════
            DIVIDER LINE
        ══════════════════════════════════════════ */}
        <div style={{ maxWidth: 1140, margin: '0 auto', padding: '0 1.5rem' }}>
          <motion.div
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, ease: EASE }}
            style={{ height: 1, background: '#ece9e4', transformOrigin: 'left' }}
          />
        </div>

        {/* ══════════════════════════════════════════
            STATS STRIP
        ══════════════════════════════════════════ */}
        <section style={{ maxWidth: 1140, margin: '0 auto', padding: '4rem 1.5rem' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
            gap: 12,
          }}>
            {STATS.map((s, i) => <StatChip key={s.label} item={s} index={i} />)}
          </div>
        </section>

        {/* ══════════════════════════════════════════
            PRODUCT PREVIEW — BENTO CARD with parallax tilt
        ══════════════════════════════════════════ */}
        <section ref={bentoRef} style={{ maxWidth: 1140, margin: '0 auto', padding: '0 1.5rem 5rem' }}>
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.15 }}
            transition={{ duration: 1.0, ease: EASE }}
            style={{
              background: '#fff',
              border: '1px solid #ece9e4',
              borderRadius: 24,
              padding: '2rem',
              boxShadow: '0 2px 40px rgba(15,14,13,0.04)',
              perspective: '1200px',
              rotateX: bentoRotateX,
              scale: bentoScale,
              transformStyle: 'preserve-3d',
            }}
          >
            {/* Mock browser chrome */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              marginBottom: '1.5rem',
              padding: '0.75rem 1rem',
              background: '#f7f5f2',
              borderRadius: 12,
              border: '1px solid #ece9e4',
            }}>
              <div style={{ display: 'flex', gap: 5 }}>
                {['#f87171','#fbbf24','#34d399'].map((c, i) => (
                  <span key={i} style={{ width: 10, height: 10, borderRadius: '50%', background: c, opacity: 0.7 }} />
                ))}
              </div>
              <div style={{
                flex: 1, height: 24,
                background: '#ece9e4',
                borderRadius: 6,
                maxWidth: 280,
                display: 'flex', alignItems: 'center',
                padding: '0 10px',
              }}>
                <span style={{ fontSize: '0.6875rem', color: '#9c9590', fontFamily: 'var(--font-body)' }}>
                  app.shiken.in / workspace
                </span>
              </div>
            </div>

            {/* Product UI mockup grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 12, minHeight: 360 }}>
              {/* Sidebar mockup */}
              <div style={{
                background: '#f7f5f2',
                borderRadius: 14,
                padding: '1rem',
                display: 'flex', flexDirection: 'column', gap: 4,
              }}>
                <p style={{ fontSize: '0.625rem', fontWeight: 700, color: '#b0a99f', textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 8, fontFamily: 'var(--font-body)' }}>
                  Workspace
                </p>
                {[
                  { label: 'Blueprints', active: false },
                  { label: 'Generator', active: true },
                  { label: 'Papers', active: false },
                  { label: 'Materials', active: false },
                  { label: 'Patterns', active: false },
                  { label: 'Team', active: false },
                ].map(({ label, active }) => (
                  <div key={label} style={{
                    padding: '0.5rem 0.75rem',
                    borderRadius: 8,
                    background: active ? '#0f0e0d' : 'transparent',
                    fontSize: '0.8125rem',
                    fontWeight: active ? 700 : 500,
                    color: active ? '#fff' : '#7a756f',
                    fontFamily: 'var(--font-body)',
                    cursor: 'default',
                  }}>
                    {label}
                  </div>
                ))}
                <div style={{ flex: 1 }} />
                <div style={{
                  padding: '0.75rem',
                  background: '#fff',
                  borderRadius: 10,
                  border: '1px solid #ece9e4',
                }}>
                  <div style={{ width: 24, height: 24, borderRadius: '50%', background: '#e8d5b7', marginBottom: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.6875rem', fontWeight: 700, color: '#7a5c30' }}>
                    M
                  </div>
                  <p style={{ fontSize: '0.6875rem', fontWeight: 600, color: '#0f0e0d', fontFamily: 'var(--font-body)' }}>Ms. Meera Singh</p>
                  <p style={{ fontSize: '0.625rem', color: '#9c9590', fontFamily: 'var(--font-body)' }}>Coordinator</p>
                </div>
              </div>

              {/* Main area mockup */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <p style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: 4 }}>
                      Paper Generator
                    </p>
                    <h2 style={{ fontSize: '1.375rem', fontWeight: 800, color: '#0f0e0d', letterSpacing: '-0.03em', fontFamily: 'var(--font-display)', marginBottom: 0 }}>
                      Class X Mathematics — Final Term
                    </h2>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <span style={{ padding: '4px 10px', background: '#dcfce7', borderRadius: 6, fontSize: '0.6875rem', fontWeight: 700, color: '#15803d', fontFamily: 'var(--font-body)' }}>Blueprint ✓</span>
                    <span style={{ padding: '4px 10px', background: '#fef9ec', borderRadius: 6, fontSize: '0.6875rem', fontWeight: 700, color: '#92400e', border: '1px solid #fde68a', fontFamily: 'var(--font-body)' }}>Draft</span>
                  </div>
                </div>

                {/* Section cards row */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                  {[
                    { section: 'Section A', desc: '10 × 1 mark', chapter: 'Algebra & Number Theory', color: '#f3f0eb' },
                    { section: 'Section B', desc: '6 × 5 marks', chapter: 'Geometry & Mensuration', color: '#f0f7f4' },
                    { section: 'Section C', desc: '3 × 10 marks', chapter: 'Statistics & Probability', color: '#fdf7f0' },
                  ].map(({ section, desc, chapter, color }) => (
                    <div key={section} style={{ background: color, borderRadius: 12, padding: '0.875rem', border: '1px solid #ece9e4' }}>
                      <p style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: 4 }}>{section}</p>
                      <p style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#0f0e0d', fontFamily: 'var(--font-body)', marginBottom: 2 }}>{desc}</p>
                      <p style={{ fontSize: '0.6875rem', color: '#9c9590', fontFamily: 'var(--font-body)' }}>{chapter}</p>
                    </div>
                  ))}
                </div>

                {/* Coverage bars */}
                <div style={{ background: '#f7f5f2', borderRadius: 12, padding: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                    <p style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)' }}>Chapter Coverage</p>
                    <span style={{ fontSize: '0.6875rem', color: '#22c55e', fontWeight: 700, fontFamily: 'var(--font-body)' }}>Blueprint aligned ✓</span>
                  </div>
                  {[['Algebra', 92], ['Geometry', 88], ['Statistics', 76], ['Number Theory', 84]].map(([ch, pct]) => (
                    <div key={ch} style={{ marginBottom: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: '0.75rem', color: '#7a756f', fontFamily: 'var(--font-body)' }}>{ch}</span>
                        <span style={{ fontSize: '0.75rem', color: '#0f0e0d', fontWeight: 600, fontFamily: 'var(--font-body)' }}>{pct}%</span>
                      </div>
                      <div style={{ height: 4, background: '#ece9e4', borderRadius: 999 }}>
                        <motion.div
                          initial={{ width: 0 }}
                          whileInView={{ width: `${pct}%` }}
                          viewport={{ once: true, amount: 0.5 }}
                          transition={{ duration: 1.1, delay: 0.3, ease: EASE }}
                          style={{ height: '100%', background: '#0f0e0d', borderRadius: 999 }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                {/* AI suggestion chip */}
                <div style={{
                  display: 'flex', alignItems: 'flex-start', gap: 10,
                  background: '#fffbf4',
                  border: '1px solid #f5e6c8',
                  borderRadius: 12, padding: '0.875rem 1rem',
                }}>
                  <Sparkles size={15} style={{ color: '#b45309', flexShrink: 0, marginTop: 1 }} />
                  <div>
                    <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#92400e', fontFamily: 'var(--font-body)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                      AI Suggestion
                    </p>
                    <p style={{ fontSize: '0.8125rem', color: '#7a5c30', lineHeight: 1.6, fontFamily: 'var(--font-body)' }}>
                      Replace 2 recall questions in Section A with application-based prompts from Algebra Ch. 3 to improve difficulty balance.
                    </p>
                  </div>
                  <button style={{
                    flexShrink: 0, padding: '4px 10px',
                    background: '#0f0e0d', color: '#fff',
                    border: 'none', borderRadius: 6, cursor: 'pointer',
                    fontSize: '0.6875rem', fontWeight: 700, fontFamily: 'var(--font-body)',
                  }}>
                    Apply
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </section>

        {/* ══════════════════════════════════════════
            DIVIDER
        ══════════════════════════════════════════ */}
        <div style={{ maxWidth: 1140, margin: '0 auto', padding: '0 1.5rem' }}>
          <motion.div
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8, ease: EASE }}
            style={{ height: 1, background: '#ece9e4', transformOrigin: 'center' }}
          />
        </div>

        {/* ══════════════════════════════════════════
            FEATURES GRID
        ══════════════════════════════════════════ */}
        <section style={{ maxWidth: 1140, margin: '0 auto', padding: '5rem 1.5rem' }}>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
            transition={{ duration: 0.7, ease: EASE }}
            style={{ marginBottom: '3rem', textAlign: 'center' }}
          >
            <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '0.875rem' }}>
              What's inside
            </p>
            <h2 style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(2rem, 4vw, 3rem)',
              fontWeight: 800,
              color: '#0f0e0d',
              lineHeight: 1.1,
              letterSpacing: '-0.035em',
              marginBottom: '1rem',
            }}>
              Everything a school needs.
              <br />
              <span style={{ color: '#c9b99a' }}>Nothing it doesn't.</span>
            </h2>
            <p style={{ fontSize: '1rem', color: '#7a756f', lineHeight: 1.75, fontFamily: 'var(--font-body)', maxWidth: 520, margin: '0 auto' }}>
              Shiken was built around how teachers and coordinators actually work — not how software engineers assume they do.
            </p>
          </motion.div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: '1.5rem',
          }}>
            {FEATURES.map((f, i) => (
              <FeatureCard key={f.title} item={f} index={i} />
            ))}
          </div>
        </section>

        {/* ══════════════════════════════════════════
            HOW IT WORKS — Flow Timeline (Left → Right)
        ══════════════════════════════════════════ */}
        <section id="how" style={{ maxWidth: 1140, margin: '0 auto', padding: '0 1.5rem 5rem' }}>
          <div style={{ borderTop: '1px solid #ece9e4', paddingTop: '5rem' }}>
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.65, ease: EASE }}
              style={{ marginBottom: '3.5rem', textAlign: 'center' }}
            >
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '0.875rem' }}>
                How it works
              </p>
              <h2 style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(2rem, 4vw, 3rem)',
                fontWeight: 800,
                color: '#0f0e0d',
                lineHeight: 1.1,
                letterSpacing: '-0.035em',
              }}>
                Blueprint to export
                <br />
                <span style={{ color: '#c9b99a' }}>in four steps.</span>
              </h2>
            </motion.div>

            {/* ── Flow timeline ─────────────────────── */}
            <div style={{ position: 'relative' }}>

              {/* Horizontal track line (sits behind badges) */}
              <div style={{
                position: 'absolute',
                top: 17, /* vertically center with the 36px badges */
                left: 'calc(12.5% + 18px)',  /* starts at center of first badge */
                right: 'calc(12.5% + 18px)', /* ends at center of last badge */
                height: 2,
                background: '#ece9e4',
                borderRadius: 999,
                zIndex: 0,
              }} />

              {/* Animated fill line that flows left → right */}
              <motion.div
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true, amount: 0.15 }}
                transition={{ duration: 1.8, ease: EASE, delay: 0.4 }}
                style={{
                  position: 'absolute',
                  top: 17,
                  left: 'calc(12.5% + 18px)',
                  right: 'calc(12.5% + 18px)',
                  height: 2,
                  background: 'linear-gradient(90deg, #0f0e0d, #c9b99a)',
                  transformOrigin: 'left',
                  borderRadius: 999,
                  zIndex: 1,
                }}
              />

              {/* Badge row */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                position: 'relative',
                zIndex: 2,
                marginBottom: 0,
              }}>
                {HOW_IT_WORKS.map((h, i) => (
                  <motion.div
                    key={`badge-${h.step}`}
                    initial={{ opacity: 0, scale: 0.5 }}
                    whileInView={{ opacity: 1, scale: 1 }}
                    viewport={{ once: true, amount: 0.5 }}
                    transition={{ duration: 0.5, delay: 0.5 + i * 0.18, ease: EASE }}
                    style={{ display: 'flex', justifyContent: 'center' }}
                  >
                    <div
                      className="landing-step-badge is-visible"
                      style={{
                        width: 36, height: 36,
                        borderRadius: '50%',
                        background: '#0f0e0d',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        boxShadow: '0 0 0 4px #faf9f7',
                        flexShrink: 0,
                      }}
                    >
                      <span style={{
                        fontSize: '0.6875rem',
                        fontWeight: 700,
                        color: '#faf9f7',
                        letterSpacing: '0.06em',
                        fontFamily: 'var(--font-body)',
                      }}>
                        {h.step}
                      </span>
                    </div>
                  </motion.div>
                ))}
              </div>

              {/* Card row — boxes below the badges */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: 12,
                marginTop: '1.5rem',
                position: 'relative',
                zIndex: 2,
              }}>
                {HOW_IT_WORKS.map((h, i) => {
                  return (
                    <motion.div
                      key={h.step}
                      initial={{ opacity: 0, x: -24, y: 12 }}
                      whileInView={{ opacity: 1, x: 0, y: 0 }}
                      viewport={{ once: true, amount: 0.25 }}
                      transition={{ duration: 0.7, delay: 0.6 + i * 0.15, ease: EASE }}
                      whileHover={{ y: -4, boxShadow: '0 12px 36px rgba(15,14,13,0.08)' }}
                      style={{
                        padding: '1.5rem 1.25rem',
                        borderRadius: 16,
                        background: 'rgba(201, 185, 154, 0.10)',
                        border: '1px solid rgba(201, 185, 154, 0.18)',
                        cursor: 'default',
                        transition: 'box-shadow 0.4s ease, transform 0.4s ease, background 0.3s ease',
                      }}
                    >
                      <h3 style={{
                        fontFamily: 'var(--font-display)',
                        fontSize: '1.25rem',
                        fontWeight: 700,
                        color: '#0f0e0d',
                        lineHeight: 1.25,
                        letterSpacing: '-0.02em',
                        marginBottom: '0.625rem',
                      }}>
                        {h.title}
                      </h3>
                      <p style={{
                        fontSize: '0.8125rem',
                        color: '#7a756f',
                        lineHeight: 1.72,
                        fontFamily: 'var(--font-body)',
                      }}>
                        {h.body}
                      </p>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════
            WHO IT'S FOR — ROLES SECTION (Dark with Glow Cards)
        ══════════════════════════════════════════ */}
        <section style={{ background: '#0f0e0d', padding: '5rem 1.5rem', position: 'relative', overflow: 'hidden' }}>
          {/* Subtle ambient glow */}
          <div style={{
            position: 'absolute',
            top: '-20%', left: '10%',
            width: '40%', height: '60%',
            background: 'radial-gradient(circle, rgba(201,185,154,0.06) 0%, transparent 70%)',
            pointerEvents: 'none',
          }} />
          <div style={{
            position: 'absolute',
            bottom: '-10%', right: '5%',
            width: '35%', height: '50%',
            background: 'radial-gradient(circle, rgba(139,224,255,0.04) 0%, transparent 70%)',
            pointerEvents: 'none',
          }} />

          <div style={{ maxWidth: 1140, margin: '0 auto', position: 'relative' }}>
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.65, ease: EASE }}
              style={{ marginBottom: '3rem', textAlign: 'center' }}
            >
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '0.875rem' }}>
                Who it's built for
              </p>
              <h2 style={{
                fontFamily: 'var(--font-display)',
                fontSize: 'clamp(2rem, 4vw, 3rem)',
                fontWeight: 800,
                color: '#faf9f7',
                lineHeight: 1.1,
                letterSpacing: '-0.035em',
              }}>
                One platform.
                <br />
                <span style={{ color: 'rgba(255,255,255,0.35)' }}>Every role in the school.</span>
              </h2>
            </motion.div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
              {[
                { role: 'Teachers', desc: 'Draft questions, use AI suggestions, and submit papers for coordinator review.', icon: '✏️' },
                { role: 'Coordinators', desc: 'Review drafts, enforce blueprint standards, and manage cross-subject consistency.', icon: '🔍' },
                { role: 'Admins', desc: 'Oversee all papers, approve final exports, and manage school-wide access control.', icon: '🛡️' },
                { role: 'Principals', desc: 'Monitor paper quality, audit history, and track blueprint compliance across the institution.', icon: '📋' },
              ].map(({ role, desc, icon }, i) => (
                <RoleCard key={role} role={role} desc={desc} icon={icon} index={i} />
              ))}
            </div>

            {/* Trust badges */}
            <motion.div
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true, amount: 0.4 }}
              transition={{ duration: 0.7, delay: 0.3, ease: EASE }}
              style={{ marginTop: '3rem', paddingTop: '2.5rem', borderTop: '1px solid rgba(255,255,255,0.08)' }}
            >
              <p style={{ fontSize: '0.6875rem', fontWeight: 600, color: 'rgba(255,255,255,0.25)', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-body)', marginBottom: '1.25rem', textAlign: 'center' }}>
                Compatible with curriculum boards
              </p>
              <div style={{ display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: '1rem 2.5rem' }}>
                {['CBSE', 'ICSE', 'IB', 'Cambridge IGCSE', 'State Boards'].map((board, i) => (
                  <motion.span
                    key={board}
                    initial={{ opacity: 0, y: 8 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.5, delay: 0.4 + i * 0.07, ease: EASE }}
                    style={{ fontSize: '0.875rem', fontWeight: 700, color: 'rgba(255,255,255,0.22)', letterSpacing: '0.06em', fontFamily: 'var(--font-body)' }}
                  >
                    {board}
                  </motion.span>
                ))}
              </div>
            </motion.div>
          </div>
        </section>



        {/* ══════════════════════════════════════════
            FAQ
        ══════════════════════════════════════════ */}
        <section style={{ maxWidth: 760, margin: '0 auto', padding: '5rem 1.5rem' }}>
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
            transition={{ duration: 0.65, ease: EASE }}
            style={{ marginBottom: '3rem', textAlign: 'center' }}
          >
            <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '0.875rem' }}>
              Questions
            </p>
            <h2 style={{
              fontFamily: 'var(--font-display)',
              fontSize: 'clamp(2rem, 4vw, 3rem)',
              fontWeight: 800,
              color: '#0f0e0d',
              lineHeight: 1.1,
              letterSpacing: '-0.035em',
            }}>
              Answers to the
              <br />
              <span style={{ color: '#c9b99a' }}>common questions.</span>
            </h2>
          </motion.div>

          <div>
            {FAQ.map((item, i) => (
              <FaqItem key={item.q} item={item} index={i} />
            ))}
          </div>
        </section>

        {/* ══════════════════════════════════════════
            CTA BANNER — Floating Orbs & Shimmer
        ══════════════════════════════════════════ */}
        <section style={{ padding: '0 1.5rem 6rem' }}>
          <div style={{ maxWidth: 1140, margin: '0 auto' }}>
            <motion.div
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.8, ease: EASE }}
              style={{
                background: '#faf7f2',
                border: '1px solid #e8e2d8',
                borderRadius: 28,
                padding: '4rem 3rem',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                textAlign: 'center',
                gap: '2rem',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {/* Floating orb 1 */}
              <div style={{
                position: 'absolute',
                top: -60, right: -40,
                width: 260, height: 260,
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(201,185,154,0.22) 0%, transparent 70%)',
                pointerEvents: 'none',
                animation: 'float-slow 12s ease-in-out infinite',
              }} />
              {/* Floating orb 2 */}
              <div style={{
                position: 'absolute',
                bottom: -40, left: -50,
                width: 220, height: 220,
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(184,169,144,0.18) 0%, transparent 70%)',
                pointerEvents: 'none',
                animation: 'float-slow 14s ease-in-out infinite reverse',
              }} />
              {/* Floating orb 3 */}
              <div style={{
                position: 'absolute',
                top: '40%', left: '50%',
                transform: 'translate(-50%, -50%)',
                width: 320, height: 320,
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(201,185,154,0.08) 0%, transparent 60%)',
                pointerEvents: 'none',
                animation: 'glow-breathe 6s ease-in-out infinite',
              }} />

              <div style={{ position: 'relative', zIndex: 1 }}>
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9c9590', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--font-body)', marginBottom: '1rem' }}>
                  Get started today
                </p>
                <h2 style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 'clamp(2.25rem, 5vw, 3.75rem)',
                  fontWeight: 800,
                  color: '#0f0e0d',
                  lineHeight: 1.08,
                  letterSpacing: '-0.04em',
                  marginBottom: '1.25rem',
                  maxWidth: 600,
                }}>
                  Build exam papers quickly.
                  <br />
                  <span style={{ color: '#c9b99a' }}>Ship with confidence.</span>
                </h2>
                <p style={{ fontSize: '1rem', color: '#7a756f', lineHeight: 1.75, fontFamily: 'var(--font-body)', maxWidth: 500 }}>
                  Shiken is free to start. No credit card required. Works for any subject, board, or school size.
                </p>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', justifyContent: 'center', position: 'relative', zIndex: 1 }}>
                <Link
                  href="/login"
                  className="landing-cta-shimmer"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '0.9375rem 2rem',
                    background: '#0f0e0d',
                    color: '#faf9f7',
                    fontSize: '0.9375rem',
                    fontWeight: 700,
                    borderRadius: 14,
                    textDecoration: 'none',
                    letterSpacing: '-0.01em',
                    fontFamily: 'var(--font-body)',
                    transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                  onMouseOver={e => { e.currentTarget.style.background = '#2a2826'; e.currentTarget.style.transform = 'translateY(-3px) scale(1.02)'; e.currentTarget.style.boxShadow = '0 16px 40px rgba(15,14,13,0.2)'; }}
                  onMouseOut={e => { e.currentTarget.style.background = '#0f0e0d'; e.currentTarget.style.transform = 'translateY(0) scale(1)'; e.currentTarget.style.boxShadow = 'none'; }}
                >
                  Enter Shiken
                  <ArrowRight size={16} />
                </Link>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <BadgeCheck size={15} style={{ color: '#22c55e' }} />
                  <span style={{ fontSize: '0.8125rem', color: '#7a756f', fontFamily: 'var(--font-body)' }}>Free to start. No card needed.</span>
                </div>
              </div>
            </motion.div>
          </div>
        </section>

        {/* ══════════════════════════════════════════
            FOOTER
        ══════════════════════════════════════════ */}
        <footer style={{
          borderTop: '1px solid #ece9e4',
          padding: '2rem 1.5rem',
        }}>
          <div style={{ maxWidth: 1140, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <div style={{ width: 24, height: 24, background: '#0f0e0d', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <GraduationCap size={12} style={{ color: '#faf9f7' }} />
              </div>
              <span style={{ fontSize: '0.9375rem', fontWeight: 800, color: '#0f0e0d', letterSpacing: '-0.02em', fontFamily: 'var(--font-body)' }}>
                Shiken
              </span>
            </div>

            <p style={{ fontSize: '0.8125rem', color: '#9c9590', fontFamily: 'var(--font-body)' }}>
              Blueprint-first AI exam platform · Built for Indian schools
            </p>

            <div style={{ display: 'flex', gap: '1.5rem' }}>
              {['Privacy', 'Terms', 'Contact'].map(link => (
                <a
                  key={link}
                  href="#"
                  style={{ fontSize: '0.8125rem', color: '#9c9590', textDecoration: 'none', fontFamily: 'var(--font-body)', transition: 'color 0.15s' }}
                  onMouseOver={e => e.currentTarget.style.color = '#0f0e0d'}
                  onMouseOut={e => e.currentTarget.style.color = '#9c9590'}
                >
                  {link}
                </a>
              ))}
            </div>
          </div>
        </footer>

      </main>
    </div>
  );
}
