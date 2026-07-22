'use client';

import Link from 'next/link';
import { BookOpen, BarChart3, FileText, Zap } from 'lucide-react';

export default function Navbar() {
  return (
    <nav className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo/Brand */}
          <Link href="/" className="flex items-center gap-2">
            <Zap className="w-6 h-6 text-blue-600" />
            <span className="text-xl font-bold text-gray-900">qForge AI</span>
          </Link>

          {/* Navigation Links */}
          <div className="hidden md:flex gap-8">
            <Link
              href="/"
              className="flex items-center gap-1 text-gray-700 hover:text-blue-600 transition-colors"
            >
              <BarChart3 className="w-4 h-4" />
              Dashboard
            </Link>
            <Link
              href="/papers"
              className="flex items-center gap-1 text-gray-700 hover:text-blue-600 transition-colors"
            >
              <FileText className="w-4 h-4" />
              Papers
            </Link>
            <Link
              href="/patterns"
              className="flex items-center gap-1 text-gray-700 hover:text-blue-600 transition-colors"
            >
              <BookOpen className="w-4 h-4" />
              Patterns
            </Link>
            <Link
              href="/generator"
              className="flex items-center gap-1 text-gray-700 hover:text-blue-600 transition-colors"
            >
              <Zap className="w-4 h-4" />
              Generate
            </Link>
          </div>

          {/* Mobile menu - simplified for now */}
          <div className="md:hidden">
            <button className="text-gray-700 hover:text-blue-600">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
