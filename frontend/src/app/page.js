'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// The bare domain owns no UI of its own — it forwards to the canonical login
// page (which carries the Dev Notes sidebar) when there's no session, or to the
// dashboard when one already exists. Keeping a single login screen means the
// Dev Notes never diverge between "/" and "/login" again.
export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    router.replace(token ? '/dashboard' : '/login');
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
    </div>
  );
}
