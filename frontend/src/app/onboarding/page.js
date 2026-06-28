'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { UploadCloud, UserPlus, FileText, CheckCircle, ArrowRight, Loader2, X } from 'lucide-react';
import apiClient from '@/lib/api';

const STEPS = [
  { id: 1, icon: UploadCloud, label: 'Upload Material',   desc: 'Add your NCERT textbook PDF so the AI can generate questions from it.' },
  { id: 2, icon: UserPlus,    label: 'Add a Teacher',     desc: 'Create the first teacher account for your school.' },
  { id: 3, icon: FileText,    label: 'Generate a Paper',  desc: 'Generate your first sample question paper to see how it works.' },
];

// ── Step 1: Upload material ────────────────────────────────────────────────────
function StepUpload({ onNext, onSkip }) {
  const [file, setFile] = useState(null);
  const [className, setClassName] = useState('12');
  const [subject, setSubject] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function handleUpload() {
    if (!file || !subject) { setError('Please select a file and subject.'); return; }
    setLoading(true); setError('');
    try {
      const fd = new FormData();
      fd.append('file_0', file);
      fd.append('title_0', file.name.replace(/\.[^.]+$/, ''));
      fd.append('unit_0', subject);
      fd.append('class_name', className);
      fd.append('subject', subject);
      fd.append('type', 'textbook');
      fd.append('chapter_count', '1');
      await apiClient.post('/materials/', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setDone(true);
      setTimeout(onNext, 1000);
    } catch (e) {
      setError(e.response?.data?.error || 'Upload failed. You can skip and do this later.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Class</label>
          <select value={className} onChange={e => setClassName(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-blue-500 outline-none">
            {['9','10','11','12'].map(c => <option key={c} value={c}>Class {c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Subject</label>
          <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. Biology"
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-blue-500 outline-none" />
        </div>
      </div>

      <div
        onClick={() => document.getElementById('ob-file').click()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors
          ${file ? 'border-green-400 bg-green-50' : 'border-slate-300 hover:border-blue-400 hover:bg-blue-50'}`}
      >
        <input id="ob-file" type="file" accept=".pdf,.docx" hidden onChange={e => { setFile(e.target.files[0]); setError(''); }} />
        <UploadCloud className={`w-8 h-8 mx-auto mb-2 ${file ? 'text-green-500' : 'text-slate-400'}`} />
        <p className="text-sm text-slate-600">
          {file ? file.name : 'Click to upload textbook PDF'}
        </p>
        <p className="text-xs text-slate-400 mt-1">PDF or DOCX · up to 50 MB</p>
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <div className="flex gap-3 pt-2">
        <button onClick={onSkip} className="flex-1 py-2.5 border border-slate-300 text-slate-600 text-sm rounded-lg hover:bg-slate-50 transition-colors">
          Skip for now
        </button>
        <button onClick={handleUpload} disabled={loading || done}
          className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-semibold rounded-lg transition-colors flex items-center justify-center gap-2">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : done ? <CheckCircle className="w-4 h-4" /> : null}
          {done ? 'Uploaded!' : loading ? 'Uploading…' : 'Upload'}
        </button>
      </div>
    </div>
  );
}

// ── Step 2: Create teacher ────────────────────────────────────────────────────
function StepTeacher({ onNext, onSkip }) {
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  async function handleCreate() {
    if (!form.username || !form.email || form.password.length < 8) {
      setError('Fill all fields. Password must be ≥ 8 characters.'); return;
    }
    setLoading(true); setError('');
    try {
      await apiClient.post('/users/', { ...form, role: 'teacher' });
      setDone(true);
      setTimeout(onNext, 1000);
    } catch (e) {
      setError(e.response?.data?.username?.[0] || e.response?.data?.email?.[0] || 'Could not create teacher.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      {[
        { key: 'username', label: 'Username', placeholder: 'ravi_sharma', type: 'text' },
        { key: 'email',    label: 'Email',    placeholder: 'ravi@school.in', type: 'email' },
        { key: 'password', label: 'Temporary Password', placeholder: 'Min. 8 chars', type: 'text' },
      ].map(({ key, label, placeholder, type }) => (
        <div key={key}>
          <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
          <input type={type} value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
            placeholder={placeholder}
            className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:border-blue-500 outline-none" />
        </div>
      ))}
      <p className="text-xs text-slate-400">The teacher will be prompted to change their password on first login.</p>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <div className="flex gap-3 pt-2">
        <button onClick={onSkip} className="flex-1 py-2.5 border border-slate-300 text-slate-600 text-sm rounded-lg hover:bg-slate-50 transition-colors">
          Skip for now
        </button>
        <button onClick={handleCreate} disabled={loading || done}
          className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-semibold rounded-lg transition-colors flex items-center justify-center gap-2">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : done ? <CheckCircle className="w-4 h-4" /> : null}
          {done ? 'Created!' : loading ? 'Creating…' : 'Create Teacher'}
        </button>
      </div>
    </div>
  );
}

// ── Step 3: Go generate ────────────────────────────────────────────────────────
function StepGenerate({ onFinish }) {
  return (
    <div className="space-y-4 text-center">
      <div className="bg-blue-50 rounded-xl p-6">
        <FileText className="w-10 h-10 text-blue-500 mx-auto mb-3" />
        <p className="text-slate-700 text-sm">
          You&apos;re all set! Click below to generate your first question paper.
          Pick any class, subject, and exam pattern to try it out.
        </p>
      </div>
      <button onClick={onFinish}
        className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm rounded-lg transition-colors flex items-center justify-center gap-2">
        <ArrowRight className="w-4 h-4" />
        Go to Generator
      </button>
    </div>
  );
}

// ── Main wizard ────────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);

  function next() { setStep(s => Math.min(s + 1, 3)); }
  function finish() { router.replace('/generator'); }

  const currentStep = STEPS[step - 1];
  const CurrentIcon = currentStep.icon;

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Progress */}
        <div className="flex items-center gap-2 mb-8">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <div key={s.id} className="flex items-center gap-2 flex-1">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-colors
                  ${step > s.id ? 'bg-green-500' : step === s.id ? 'bg-blue-600' : 'bg-slate-200'}`}>
                  {step > s.id
                    ? <CheckCircle className="w-4 h-4 text-white" />
                    : <Icon className={`w-4 h-4 ${step === s.id ? 'text-white' : 'text-slate-400'}`} />
                  }
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`flex-1 h-0.5 transition-colors ${step > s.id ? 'bg-green-400' : 'bg-slate-200'}`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Card */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
          <div className="mb-5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                Step {step} of {STEPS.length}
              </span>
            </div>
            <h2 className="text-lg font-semibold text-slate-900">{currentStep.label}</h2>
            <p className="text-sm text-slate-500 mt-0.5">{currentStep.desc}</p>
          </div>

          {step === 1 && <StepUpload onNext={next} onSkip={next} />}
          {step === 2 && <StepTeacher onNext={next} onSkip={next} />}
          {step === 3 && <StepGenerate onFinish={finish} />}
        </div>

        <p className="text-center mt-4">
          <button onClick={finish} className="text-xs text-slate-400 hover:text-slate-600 underline">
            Skip setup and go straight to the app
          </button>
        </p>
      </div>
    </div>
  );
}
