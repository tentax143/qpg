'use client';

import { useState, useEffect } from 'react';

const STYLES = `
  @media print {
    .no-print { display: none !important; }
    .page-break { page-break-before: always; }
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .manual-root { padding: 0 !important; margin: 0 auto !important; }
    aside, nav, header, [class*="fixed"] { display: none !important; }
    main { margin-left: 0 !important; padding: 0 !important; }
    div[class*="ml-64"] { margin-left: 0 !important; }
    div[class*="max-w-7xl"] { max-width: 100% !important; padding: 0 !important; }
  }
  .manual-root { font-family: 'Georgia', serif; }
  .sans { font-family: 'Inter', 'Segoe UI', sans-serif; }
  .step-num {
    width: 28px; height: 28px; border-radius: 50%;
    background: #1e3a5f; color: white;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; flex-shrink: 0;
    font-family: 'Inter', sans-serif;
  }
  .role-pill {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 700; font-family: 'Inter', sans-serif;
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .tip-box {
    background: #f0f7ff; border-left: 4px solid #3b82f6;
    padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 14px 0;
  }
  .warn-box {
    background: #fffbeb; border-left: 4px solid #f59e0b;
    padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 14px 0;
  }
  .section-card {
    border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 18px 22px; margin: 14px 0; background: #fafbfc;
  }
  h1,h2,h3,h4 { font-family: 'Inter', 'Segoe UI', sans-serif; }
`;

function StepList({ steps }) {
  return (
    <ol className="space-y-2">
      {steps.map((s, j) => (
        <li key={j} className="text-sm text-slate-700 flex gap-2">
          <span className="step-num" style={{ width: 22, height: 22, fontSize: 11 }}>{j + 1}</span> {s}
        </li>
      ))}
    </ol>
  );
}

function BulletList({ items }) {
  return (
    <ul className="space-y-1.5">
      {items.map((s, i) => (
        <li key={i} className="text-sm text-slate-700 flex gap-2">
          <span className="text-blue-500 mt-0.5">▸</span> {s}
        </li>
      ))}
    </ul>
  );
}

// ── Shared sections (used by all roles) ────────────────────────────────────

function SectionUploadMaterials({ num }) {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        <span className="text-blue-600">Step {num}</span> — Upload Learning Materials
      </h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-3" />
      <p className="text-sm text-slate-500 mb-5 sans">
        <strong>Required before generating any paper.</strong> The AI draws exclusively from your uploaded materials to write questions.
      </p>

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-3">How to Upload</h4>
        <StepList steps={[
          'Go to Upload Material in the sidebar.',
          'Select the Class (e.g. Class 10) and Subject (e.g. Biology).',
          'Choose the Material Type — see the table below.',
          'Enter a title and optionally specify a Unit / Chapter.',
          'Select the PDF file and click Upload.',
          'Wait for processing — the status changes from "Processing" to "Ready" automatically.',
        ]} />
      </div>

      <h4 className="font-bold text-slate-800 sans mb-3">Material Types</h4>
      <table className="w-full text-sm border border-slate-200 rounded-lg overflow-hidden sans mb-4">
        <thead>
          <tr className="bg-slate-100 text-slate-600 text-xs uppercase tracking-wider">
            <th className="px-4 py-2.5 text-left font-semibold">Type</th>
            <th className="px-4 py-2.5 text-left font-semibold">Use Case</th>
            <th className="px-4 py-2.5 text-left font-semibold">Visibility</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {[
            ['Textbook', 'Official CBSE / publisher textbook', 'Shared across schools (if enabled)'],
            ['Notes', 'Teacher-prepared notes or summaries', 'Private to your school'],
            ['Question Bank', 'Past papers or practice questions', 'Private to your school'],
            ['Syllabus', 'Curriculum or syllabus document', 'Private to your school'],
            ['Reference Book', 'Supplementary reference material', 'Private to your school'],
          ].map(([type, use, vis]) => (
            <tr key={type} className="even:bg-slate-50">
              <td className="px-4 py-2.5 font-medium text-slate-800">{type}</td>
              <td className="px-4 py-2.5 text-slate-600">{use}</td>
              <td className="px-4 py-2.5 text-slate-500 text-xs">{vis}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="warn-box text-sm text-slate-700">
        <strong className="sans text-amber-700">Important:</strong> Upload at least one Textbook or Notes file for the subject and class you intend to examine. Without uploaded material the AI has no content to draw questions from.
      </div>
    </section>
  );
}

function SectionExamPattern({ num }) {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        <span className="text-blue-600">Step {num}</span> — Create an Exam Pattern
      </h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-3" />
      <p className="text-sm text-slate-500 mb-5 sans">
        <strong>Required before generating a paper.</strong> A pattern defines the structure — how many sections, what question types, and how many marks each carries.
      </p>

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-3">Creating a Manual Pattern</h4>
        <StepList steps={[
          'Go to Exam Patterns in the sidebar.',
          'Click Create New Pattern.',
          'Enter a pattern name (e.g. "PT-1 Biology Class 10"), subject, and class.',
          'Add sections — for each section fill in the fields shown below.',
          'Click Save Pattern.',
        ]} />
        <div className="ml-8 mt-3 bg-white border border-slate-200 rounded-lg p-3">
          <p className="text-xs font-bold text-slate-500 sans uppercase tracking-wider mb-2">Section Fields</p>
          <table className="w-full text-xs sans">
            <tbody>
              {[
                ['Section Name', 'e.g. "Section A — MCQ"'],
                ['Question Type', 'MCQ / Short Answer / Long Answer / Fill in the Blank / Match / Assertion-Reason'],
                ['Questions Count', 'How many questions in this section'],
                ['Marks per Question', 'Marks awarded for each correct answer'],
                ['Instructions', '(Optional) Instructions printed above the section'],
              ].map(([field, ex]) => (
                <tr key={field}>
                  <td className="py-0.5 pr-3 font-semibold text-slate-700 whitespace-nowrap">{field}</td>
                  <td className="py-0.5 text-slate-500">{ex}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-2">Using AI to Generate a Pattern</h4>
        <p className="text-sm text-slate-700 mb-2">
          Instead of building manually, describe your exam in plain English and QPG generates the structure for you:
        </p>
        <div className="bg-slate-900 rounded-lg px-4 py-3 text-green-400 font-mono text-xs leading-relaxed">
          "Create a 40-mark Biology paper for Class 10 with 10 MCQs of 1 mark each, 5 short answers of 2 marks, and 3 long answers of 5 marks each."
        </div>
        <p className="text-xs text-slate-400 mt-2 sans">Review and adjust the AI-generated structure before saving.</p>
      </div>

      <div className="tip-box text-sm text-slate-700">
        <strong className="sans text-blue-700">Tip:</strong> Create one pattern per exam type (PT-1, PT-2, Half-Yearly, Annual) and reuse it across subjects — patterns are not subject-specific.
      </div>
    </section>
  );
}

function SectionBlueprint({ num }) {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        <span className="text-blue-600">Step {num}</span> — Create a Blueprint <span className="text-base font-normal text-slate-400">(Optional)</span>
      </h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-3" />
      <p className="text-sm text-slate-600 mb-5 leading-relaxed">
        A blueprint is a chapter-wise mark distribution plan. While a pattern says "10 MCQs worth 1 mark each",
        a blueprint specifies which chapters those questions come from. Blueprints are optional but give precise control over coverage.
      </p>

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-3">When to Use a Blueprint</h4>
        <BulletList items={[
          'You want guaranteed chapter-wise coverage (every chapter must have at least one question).',
          'You are following a mandated CBSE blueprint for board exams.',
          "You want to replicate the exact structure of a previous year's paper.",
        ]} />
      </div>

      <div className="section-card">
        <h4 className="font-bold text-slate-900 sans mb-3">Creating a Blueprint</h4>
        <StepList steps={[
          'Go to Blueprints in the sidebar.',
          'Click Create Blueprint or start from an existing CBSE template.',
          'Select the subject and class.',
          'For each chapter, enter the marks allocated per question type.',
          'Save the blueprint — it will be available to select during paper generation.',
        ]} />
      </div>
    </section>
  );
}

function SectionGenerate({ num }) {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        <span className="text-blue-600">Step {num}</span> — Generate a Question Paper
      </h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-5" />

      <div className="section-card mb-6 border-blue-200 bg-blue-50">
        <h4 className="font-bold text-blue-900 sans mb-3">Pre-Generation Checklist</h4>
        <ul className="space-y-2">
          {[
            ['Materials uploaded', 'At least one PDF uploaded for the target subject and class'],
            ['Pattern created', 'An exam pattern exists for the subject / exam type'],
            ['Blueprint (optional)', 'Create one if you need chapter-wise mark control'],
          ].map(([label, desc]) => (
            <li key={label} className="flex items-start gap-3 text-sm text-blue-800">
              <span className="mt-0.5 text-blue-500">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
              </span>
              <span><strong>{label}</strong> — {desc}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="section-card">
        <h4 className="font-bold text-slate-900 sans mb-3">Generation Steps</h4>
        <ol className="space-y-3">
          {[
            ['Open Generator', 'Click Generate Paper in the sidebar.'],
            ['Select Class & Subject', 'Choose the class (e.g. Class 10) and subject (e.g. Biology).'],
            ['Choose Chapters', 'Select one or more chapters. The list is populated from your uploaded materials.'],
            ['Pick a Pattern', 'Select the exam pattern that defines the paper structure.'],
            ['Set Difficulty', 'Choose Easy, Medium, or Hard.'],
            ['Select Blueprint (optional)', 'Attach a blueprint for chapter-wise mark distribution.'],
            ['Generate', 'Click Generate Paper. The paper is created in the background — it appears in My Papers with a "Generating" status. Generation typically takes 30–90 seconds.'],
          ].map(([title, desc], j) => (
            <li key={j} className="flex gap-3">
              <span className="step-num shrink-0 mt-0.5">{j + 1}</span>
              <div>
                <p className="text-sm font-semibold text-slate-800 sans">{title}</p>
                <p className="text-sm text-slate-600 mt-0.5">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function SectionEditDownload() {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">Editing & Downloading Papers</h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-5" />

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-3">Viewing a Generated Paper</h4>
        <StepList steps={[
          'Go to My Papers in the sidebar.',
          'Wait for the paper status to change from "Generating" to "Done".',
          'Click View to open the paper.',
        ]} />
      </div>

      <div className="section-card mb-4">
        <h4 className="font-bold text-slate-900 sans mb-3">Editing Questions</h4>
        <p className="text-sm text-slate-700 mb-2">
          Every generated question can be individually edited before printing. Click the Edit icon on any question to:
        </p>
        <BulletList items={[
          'Rephrase the question text',
          'Adjust the answer or marking scheme',
          'Change marks assigned to that question',
          'Delete a question and replace it',
        ]} />
      </div>

      <div className="section-card">
        <h4 className="font-bold text-slate-900 sans mb-2">Downloading as PDF</h4>
        <p className="text-sm text-slate-700">
          Once satisfied, click <strong>Download PDF</strong> from the paper view page.
          The PDF is formatted for A4 printing with the school name, subject, class, and date in the header.
        </p>
      </div>
    </section>
  );
}

function SectionTips() {
  return (
    <section className="mb-12">
      <h2 className="text-2xl font-bold text-slate-900 mb-1">Tips & Best Practices</h2>
      <div className="h-1 w-12 bg-blue-500 rounded mb-5" />
      <div className="space-y-3">
        {[
          { icon: '📚', title: 'Upload before you generate', body: 'Always upload the relevant textbook chapter or notes before generating. The AI cannot invent content — it extracts and reformulates from what you provide.' },
          { icon: '📝', title: 'Name patterns clearly', body: 'Use names like "PT-2 Physics Class 11 — 40 Marks" so patterns are easy to identify and reuse across teachers.' },
          { icon: '🔢', title: 'Be specific with chapter selection', body: 'Selecting fewer chapters forces the AI to focus more deeply. Selecting all chapters may dilute coverage per chapter.' },
          { icon: '♻️', title: 'Reuse patterns across subjects', body: 'Patterns are not subject-specific. A "30-Mark SA Exam" pattern can be reused for any subject with the same structure.' },
          { icon: '💰', title: 'Monitor token usage', body: 'Each generation consumes AI tokens. School admins can view per-user token consumption in Team Usage to manage costs.' },
        ].map(({ icon, title, body }) => (
          <div key={title} className="section-card flex gap-4">
            <span className="text-2xl shrink-0">{icon}</span>
            <div>
              <h4 className="font-bold text-slate-900 sans text-sm mb-0.5">{title}</h4>
              <p className="text-sm text-slate-600 leading-relaxed">{body}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Role-specific manuals ───────────────────────────────────────────────────

function SuperadminManual() {
  return (
    <>
      {/* TOC */}
      <div className="mb-12">
        <h2 className="text-lg font-bold text-slate-900 mb-4 uppercase tracking-wide text-sm border-b border-slate-200 pb-2">Table of Contents</h2>
        <ol className="space-y-2 sans text-sm text-slate-600">
          {[
            ['1', 'System Overview & User Roles'],
            ['2', 'Create Schools'],
            ['3', 'Create the First User (School Admin)'],
            ['4', 'Step 1 — Upload Learning Materials'],
            ['5', 'Step 2 — Create an Exam Pattern'],
            ['6', 'Step 3 — Create a Blueprint (Optional)'],
            ['7', 'Step 4 — Generate a Question Paper'],
            ['8', 'Editing & Downloading Papers'],
            ['9', 'Tips & Best Practices'],
          ].map(([n, t]) => (
            <li key={n} className="flex items-center gap-3">
              <span className="text-blue-600 font-bold w-5">{n}.</span>
              <span>{t}</span>
              <span className="flex-1 border-b border-dotted border-slate-300 mx-1" />
            </li>
          ))}
        </ol>
      </div>

      {/* Overview */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">1. System Overview</h2>
        <div className="h-1 w-12 bg-blue-500 rounded mb-5" />
        <p className="text-base leading-relaxed text-slate-700 mb-4">
          QPG (Question Paper Generator) is an AI-powered platform that lets schools generate curriculum-aligned question papers from their own uploaded study materials.
        </p>
        <div className="grid grid-cols-1 gap-3">
          {[
            { role: 'Superadmin', color: 'bg-amber-100 text-amber-800', desc: 'Manages schools, grants shared resource access, and oversees the entire platform.' },
            { role: 'School Admin', color: 'bg-violet-100 text-violet-800', desc: 'Manages teachers within their school, views team usage, and configures school settings.' },
            { role: 'Teacher', color: 'bg-slate-100 text-slate-700', desc: 'Uploads materials, creates exam patterns, and generates question papers.' },
          ].map(({ role, color, desc }) => (
            <div key={role} className="section-card flex items-start gap-4">
              <span className={`role-pill ${color} mt-0.5`}>{role}</span>
              <p className="text-sm leading-relaxed text-slate-600">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Create School */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">2. Create Schools</h2>
        <div className="h-1 w-12 bg-amber-400 rounded mb-5" />
        <div className="section-card">
          <div className="flex items-start gap-3 mb-3">
            <span className="step-num">1</span>
            <div>
              <h4 className="font-bold text-slate-900 sans">Create a School</h4>
              <p className="text-xs text-slate-400 sans mt-0.5">Superadmin → Schools → New School</p>
            </div>
          </div>
          <StepList steps={[
            'Navigate to Superadmin → Schools and click New School.',
            'Fill in the school name, address, phone, and email.',
            'Set a monthly token budget (0 = unlimited).',
            "Toggle Shared Vector Store Access ON if this school should inherit the platform's shared textbooks.",
            'Click Create School.',
          ]} />
          <div className="tip-box mt-3 text-sm text-slate-700">
            <strong className="sans text-blue-700">Note:</strong> Enabling Shared Vector Store copies all existing shared textbooks into the school's private storage. Use the Re-sync button later if new shared textbooks are added.
          </div>
        </div>
      </section>

      {/* Create School Admin */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">3. Create the First User (School Admin)</h2>
        <div className="h-1 w-12 bg-amber-400 rounded mb-5" />
        <div className="section-card">
          <div className="flex items-start gap-3 mb-3">
            <span className="step-num">1</span>
            <div>
              <h4 className="font-bold text-slate-900 sans">Add School Admin</h4>
              <p className="text-xs text-slate-400 sans mt-0.5">School detail → Users tab → Add User</p>
            </div>
          </div>
          <StepList steps={[
            "Open the school's detail page and switch to the Users tab.",
            'Click Add User.',
            'Enter a username and password.',
            'Set Role to School Admin.',
            'Leave Subject Restriction blank (school admins access all subjects).',
            'Click Add User.',
          ]} />
          <div className="tip-box mt-3 text-sm text-slate-700">
            <strong className="sans text-blue-700">Note:</strong> Share the credentials with the school. The school admin will create teacher accounts themselves.
          </div>
        </div>
      </section>

      <SectionUploadMaterials num={1} />
      <SectionExamPattern num={2} />
      <SectionBlueprint num={3} />
      <SectionGenerate num={4} />
      <SectionEditDownload />
      <SectionTips />
    </>
  );
}

function SchoolAdminManual({ schoolName }) {
  return (
    <>
      {/* TOC */}
      <div className="mb-12">
        <h2 className="text-lg font-bold text-slate-900 mb-4 uppercase tracking-wide text-sm border-b border-slate-200 pb-2">Table of Contents</h2>
        <ol className="space-y-2 sans text-sm text-slate-600">
          {[
            ['1', 'Your Role as School Admin'],
            ['2', 'Create Teacher Accounts'],
            ['3', 'Monitor Team Usage'],
            ['4', 'Step 1 — Upload Learning Materials'],
            ['5', 'Step 2 — Create an Exam Pattern'],
            ['6', 'Step 3 — Create a Blueprint (Optional)'],
            ['7', 'Step 4 — Generate a Question Paper'],
            ['8', 'Editing & Downloading Papers'],
            ['9', 'Tips & Best Practices'],
          ].map(([n, t]) => (
            <li key={n} className="flex items-center gap-3">
              <span className="text-blue-600 font-bold w-5">{n}.</span>
              <span>{t}</span>
              <span className="flex-1 border-b border-dotted border-slate-300 mx-1" />
            </li>
          ))}
        </ol>
      </div>

      {/* Role overview */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">1. Your Role as School Admin</h2>
        <div className="h-1 w-12 bg-violet-500 rounded mb-5" />
        <p className="text-base leading-relaxed text-slate-700 mb-4">
          As School Admin{schoolName ? ` of ${schoolName}` : ''}, you manage your school's users, monitor AI usage, and generate question papers.
          You are the only user in your school who can create teacher accounts.
        </p>
        <div className="section-card">
          <h4 className="font-bold text-slate-900 sans mb-3">What you can do</h4>
          <BulletList items={[
            'Create and manage teacher accounts for your school',
            'Optionally restrict each teacher to a specific subject',
            'Upload learning materials (textbooks, notes, question banks)',
            'Create exam patterns and blueprints',
            'Generate question papers',
            'View team AI usage and costs in the Team Usage page',
            'Promote a teacher to school admin or demote an admin to teacher',
          ]} />
        </div>
      </section>

      {/* Create teachers */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">2. Create Teacher Accounts</h2>
        <div className="h-1 w-12 bg-violet-500 rounded mb-5" />
        <div className="section-card mb-4">
          <StepList steps={[
            'Go to Users in the sidebar.',
            'Click Add User and fill in the username and password.',
            'Select a Subject Restriction from the dropdown if this teacher should only access one subject. Leave blank for full access.',
            'Click Initialize User.',
          ]} />
          <div className="tip-box mt-3 text-sm text-slate-700">
            <strong className="sans text-blue-700">Subject Restriction:</strong> If a teacher is assigned "Mathematics", they can only upload materials and generate papers for Mathematics. Teachers with no restriction can access all subjects but cannot create other users.
          </div>
        </div>

        <div className="section-card">
          <h4 className="font-bold text-slate-900 sans mb-2">Promoting / Demoting Users</h4>
          <p className="text-sm text-slate-700">
            In the Users list, click the <strong>shield icon</strong> next to a teacher to promote them to School Admin.
            Click the shield-off icon next to an admin to demote them back to Teacher.
          </p>
        </div>
      </section>

      {/* Team usage */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-slate-900 mb-1">3. Monitor Team Usage</h2>
        <div className="h-1 w-12 bg-violet-500 rounded mb-5" />
        <div className="section-card">
          <p className="text-sm text-slate-700 mb-3">
            The <strong>Team Usage</strong> page (sidebar) shows a per-user breakdown of AI consumption for your school:
          </p>
          <table className="w-full text-xs sans border border-slate-200 rounded-lg overflow-hidden">
            <thead>
              <tr className="bg-slate-100 text-slate-500 uppercase tracking-wider">
                <th className="px-3 py-2 text-left font-semibold">Column</th>
                <th className="px-3 py-2 text-left font-semibold">What it shows</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {[
                ['Total Papers', 'All papers generated by this user (ever)'],
                ['Total Tokens', 'All AI tokens consumed (ever)'],
                ['Total Cost', 'Cumulative cost in ₹ (ever)'],
                ['Monthly Tokens', 'Tokens used in the current calendar month'],
                ['Monthly Cost', 'Cost in ₹ for the current calendar month'],
              ].map(([col, desc]) => (
                <tr key={col} className="even:bg-slate-50">
                  <td className="px-3 py-2 font-medium text-slate-800">{col}</td>
                  <td className="px-3 py-2 text-slate-600">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <SectionUploadMaterials num={1} />
      <SectionExamPattern num={2} />
      <SectionBlueprint num={3} />
      <SectionGenerate num={4} />
      <SectionEditDownload />
      <SectionTips />
    </>
  );
}

function TeacherManual() {
  return (
    <>
      {/* TOC */}
      <div className="mb-12">
        <h2 className="text-lg font-bold text-slate-900 mb-4 uppercase tracking-wide text-sm border-b border-slate-200 pb-2">Table of Contents</h2>
        <ol className="space-y-2 sans text-sm text-slate-600">
          {[
            ['1', 'Step 1 — Upload Learning Materials'],
            ['2', 'Step 2 — Create an Exam Pattern'],
            ['3', 'Step 3 — Create a Blueprint (Optional)'],
            ['4', 'Step 4 — Generate a Question Paper'],
            ['5', 'Editing & Downloading Papers'],
            ['6', 'Tips & Best Practices'],
          ].map(([n, t]) => (
            <li key={n} className="flex items-center gap-3">
              <span className="text-blue-600 font-bold w-5">{n}.</span>
              <span>{t}</span>
              <span className="flex-1 border-b border-dotted border-slate-300 mx-1" />
            </li>
          ))}
        </ol>
      </div>

      <SectionUploadMaterials num={1} />
      <SectionExamPattern num={2} />
      <SectionBlueprint num={3} />
      <SectionGenerate num={4} />
      <SectionEditDownload />
      <SectionTips />
    </>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────

export default function ManualPage() {
  const [role, setRole] = useState(null);
  const [schoolName, setSchoolName] = useState('');

  useEffect(() => {
    const stored = localStorage.getItem('user');
    if (stored) {
      const u = JSON.parse(stored);
      setRole(u.role || 'teacher');
      setSchoolName(u.school_name || '');
    } else {
      setRole('teacher');
    }
    document.title = 'QPG — User Manual';
  }, []);

  const roleLabel = role === 'superadmin' ? 'Superadmin' : role === 'school_admin' ? 'School Admin' : 'Teacher';
  const accentColor = role === 'superadmin' ? 'bg-amber-100 text-amber-800' : role === 'school_admin' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700';

  return (
    <>
      <style>{STYLES}</style>

      <div className="manual-root max-w-[820px] mx-auto px-8 py-10 text-slate-800">

        {/* Print button */}
        <div className="no-print mb-8 flex justify-end">
          <button
            onClick={() => window.print()}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
            </svg>
            Save as PDF
          </button>
        </div>

        {/* Cover */}
        <div className="text-center mb-14 pb-10 border-b-2 border-slate-200">
          <div className="w-16 h-16 bg-blue-600 rounded-2xl mx-auto mb-5 flex items-center justify-center">
            <svg className="w-9 h-9 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l9-5-9-5-9 5 9 5z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l6.16-3.422a12.083 12.083 0 01.665 6.479A11.952 11.952 0 0012 20.055a11.952 11.952 0 00-6.824-2.998 12.078 12.078 0 01.665-6.479L12 14z" />
            </svg>
          </div>
          <h1 className="text-4xl font-bold text-slate-900 mb-2 tracking-tight">QPG</h1>
          <p className="text-xl text-slate-500 mb-1">Question Paper Generator</p>
          <p className="text-base font-semibold text-blue-600 mb-4">User Manual</p>
          <div className="flex items-center justify-center gap-3">
            <span className={`role-pill ${accentColor}`}>{roleLabel}</span>
            {schoolName && <span className="text-sm text-slate-400">{schoolName}</span>}
          </div>
        </div>

        {/* Role-specific content */}
        {role === 'superadmin' && <SuperadminManual />}
        {role === 'school_admin' && <SchoolAdminManual schoolName={schoolName} />}
        {role === 'teacher' && <TeacherManual />}

        {/* Footer */}
        <div className="border-t-2 border-slate-200 pt-6 text-center text-xs text-slate-400 sans">
          <p>QPG — Question Paper Generator &nbsp;·&nbsp; User Manual v1.0 &nbsp;·&nbsp; {roleLabel} Edition</p>
          <p className="mt-1">For support, contact your system administrator.</p>
        </div>

      </div>
    </>
  );
}
