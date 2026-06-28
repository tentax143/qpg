'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  GraduationCap, Zap, BookOpen, FileText, Users, CheckCircle,
  ArrowRight, Sparkles, LayoutTemplate, Upload, Printer,
} from 'lucide-react';
import apiClient from '@/lib/api';

const PLAN_FEATURES = {
  free:   ['5 papers / month', '2 teachers', 'All subjects', 'Email support'],
  basic:  ['30 papers / month', '5 teachers', 'All subjects', 'Email support'],
  pro:    ['100 papers / month', '15 teachers', 'All subjects', 'Chat support'],
  school: ['Unlimited papers', 'Unlimited teachers', 'All subjects', 'Priority phone support'],
};

const FEATURES = [
  {
    icon: Sparkles,
    title: 'AI Question Generation',
    desc: 'Generate syllabus-aligned questions instantly from your own study materials using AI.',
  },
  {
    icon: LayoutTemplate,
    title: 'Blueprint Templates',
    desc: 'Define exam patterns once — marks distribution, question types, difficulty — and reuse them across papers.',
  },
  {
    icon: Upload,
    title: 'Material Library',
    desc: 'Upload PDFs, notes, or textbook chapters. The AI draws questions directly from your content.',
  },
  {
    icon: Printer,
    title: 'Print-Ready PDFs',
    desc: 'Export polished, formatted question papers ready for the printer in one click.',
  },
  {
    icon: Users,
    title: 'Multi-Teacher Teams',
    desc: 'Invite subject teachers to collaborate. Each teacher manages their own question bank.',
  },
  {
    icon: BookOpen,
    title: 'All Subjects & Boards',
    desc: 'Supports all subjects and common board patterns including CBSE, ICSE, and state boards.',
  },
];

const STEPS = [
  { n: '1', title: 'Upload materials', desc: 'Add your notes, textbook chapters, or any PDF.' },
  { n: '2', title: 'Pick a blueprint', desc: 'Choose an exam pattern or create your own marks layout.' },
  { n: '3', title: 'Generate & export', desc: 'AI builds the paper; download a print-ready PDF.' },
];

export default function LandingPage() {
  const router = useRouter();
  const [plans, setPlans] = useState([]);
  const [plansLoading, setPlansLoading] = useState(true);

  useEffect(() => {
    if (localStorage.getItem('authToken')) {
      router.replace('/dashboard');
      return;
    }
    apiClient.get('/billing/plans/')
      .then(r => setPlans(r.data))
      .catch(() => {})
      .finally(() => setPlansLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-white text-slate-900">

      {/* ── Navbar ─────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur border-b border-slate-100">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center">
              <GraduationCap className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-slate-900 text-sm tracking-tight">Shiken</span>
          </div>
          <nav className="flex items-center gap-2">
            <Link
              href="#pricing"
              className="text-sm text-slate-500 hover:text-slate-900 px-3 py-1.5 rounded-lg transition-colors hidden sm:block"
            >
              Pricing
            </Link>
            <Link
              href="/login"
              className="text-sm text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded-lg transition-colors"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-1.5 rounded-lg font-medium transition-colors"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 pt-20 pb-24 text-center">
        <div className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-700 text-xs font-medium px-3 py-1 rounded-full mb-6">
          <Zap className="w-3 h-3" /> AI-powered for Indian schools
        </div>
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-slate-900 leading-tight max-w-3xl mx-auto">
          Generate question papers<br className="hidden sm:block" /> in minutes, not hours
        </h1>
        <p className="mt-5 text-lg text-slate-500 max-w-xl mx-auto">
          Shiken lets teachers create syllabus-aligned, print-ready question papers using AI —
          from their own materials, in any subject, for any board.
        </p>
        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            href="/register"
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl font-medium text-sm transition-colors"
          >
            Start for free <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 border border-slate-200 hover:border-slate-300 bg-white text-slate-700 px-5 py-2.5 rounded-xl font-medium text-sm transition-colors"
          >
            Sign in to your school
          </Link>
        </div>
        <p className="mt-4 text-xs text-slate-400">Free plan available · No credit card required</p>
      </section>

      {/* ── Features ───────────────────────────────────────────────────── */}
      <section className="bg-slate-50 py-20">
        <div className="max-w-6xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-900">Everything a teacher needs</h2>
            <p className="text-slate-500 mt-2 text-sm">From AI generation to team collaboration — all in one place.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="bg-white border border-slate-200 rounded-2xl p-5">
                <div className="w-9 h-9 bg-blue-50 rounded-xl flex items-center justify-center mb-4">
                  <Icon className="w-4.5 h-4.5 text-blue-600 w-5 h-5" />
                </div>
                <h3 className="font-semibold text-slate-900 text-sm mb-1">{title}</h3>
                <p className="text-slate-500 text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────────────────── */}
      <section className="py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 mb-2">How it works</h2>
          <p className="text-slate-500 text-sm mb-12">Three steps from material to printed paper.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
            {STEPS.map(({ n, title, desc }) => (
              <div key={n} className="flex flex-col items-center text-center">
                <div className="w-10 h-10 rounded-full bg-blue-600 text-white text-sm font-bold flex items-center justify-center mb-4">
                  {n}
                </div>
                <h3 className="font-semibold text-slate-900 text-sm mb-1">{title}</h3>
                <p className="text-slate-500 text-sm">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ────────────────────────────────────────────────────── */}
      <section id="pricing" className="bg-slate-50 py-20">
        <div className="max-w-5xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-900">Simple, school-friendly pricing</h2>
            <p className="text-slate-500 mt-2 text-sm">Start free. Upgrade only when you need more.</p>
          </div>

          {plansLoading ? (
            <div className="flex justify-center py-10">
              <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {plans.map(plan => {
                const features = PLAN_FEATURES[plan.name] || [];
                const isPopular = plan.name === 'pro';
                const isFree = plan.price_inr === '0.00';

                return (
                  <div
                    key={plan.name}
                    className={`relative bg-white border rounded-2xl p-5 flex flex-col
                      ${isPopular ? 'border-blue-500 shadow-md' : 'border-slate-200'}`}
                  >
                    {isPopular && (
                      <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                        <span className="bg-blue-600 text-white text-[11px] font-semibold px-3 py-0.5 rounded-full whitespace-nowrap">
                          Most Popular
                        </span>
                      </div>
                    )}

                    <div className="mb-4">
                      <p className="font-bold text-slate-900">{plan.display_name}</p>
                      <p className="text-2xl font-bold text-slate-900 mt-1">
                        {isFree ? 'Free' : `₹${Number(plan.price_inr).toLocaleString('en-IN')}`}
                        {!isFree && <span className="text-sm font-normal text-slate-400">/mo</span>}
                      </p>
                    </div>

                    <ul className="space-y-1.5 flex-1 mb-5">
                      {features.map(f => (
                        <li key={f} className="flex items-start gap-1.5 text-sm text-slate-600">
                          <CheckCircle className="w-3.5 h-3.5 text-green-500 mt-0.5 flex-shrink-0" />
                          {f}
                        </li>
                      ))}
                    </ul>

                    <Link
                      href="/register"
                      className={`w-full py-2 rounded-lg text-sm font-semibold text-center transition-colors block
                        ${isPopular
                          ? 'bg-blue-600 hover:bg-blue-700 text-white'
                          : isFree
                          ? 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                          : 'bg-slate-800 hover:bg-slate-900 text-white'
                        }`}
                    >
                      {isFree ? 'Get started free' : `Start with ${plan.display_name}`}
                    </Link>
                  </div>
                );
              })}
            </div>
          )}

          <p className="text-center text-xs text-slate-400 mt-6">
            Payments via Razorpay · GST invoice included · Annual billing available on request
          </p>
        </div>
      </section>

      {/* ── CTA Banner ─────────────────────────────────────────────────── */}
      <section className="py-20">
        <div className="max-w-2xl mx-auto px-4 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 mb-3">
            Ready to save hours every week?
          </h2>
          <p className="text-slate-500 text-sm mb-8">
            Join schools already using Shiken to generate better papers faster.
          </p>
          <Link
            href="/register"
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-xl font-medium text-sm transition-colors"
          >
            Create your free account <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-100 py-8">
        <div className="max-w-6xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-blue-600 rounded-md flex items-center justify-center">
              <GraduationCap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-semibold text-slate-700">Shiken</span>
          </div>
          <p className="text-xs text-slate-400">Shiken · AI Question Paper Generator · Built for Indian schools</p>
          <div className="flex items-center gap-4">
            <Link href="/login" className="text-xs text-slate-400 hover:text-slate-600 transition-colors">Sign in</Link>
            <Link href="/register" className="text-xs text-slate-400 hover:text-slate-600 transition-colors">Register</Link>
            <Link href="#pricing" className="text-xs text-slate-400 hover:text-slate-600 transition-colors">Pricing</Link>
          </div>
        </div>
      </footer>

    </div>
  );
}
