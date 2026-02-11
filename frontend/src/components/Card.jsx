'use client';

export default function Card({ children, className = '' }) {
  return (
    <div className={`backdrop-blur-md bg-white/80 border border-white/50 rounded-2xl shadow-xl shadow-blue-500/5 p-6 transition-all duration-300 hover:shadow-blue-500/10 ${className}`}>
      {children}
    </div>
  );
}
