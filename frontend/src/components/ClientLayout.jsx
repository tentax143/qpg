'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import Sidebar from './Sidebar';

const PUBLIC_PATHS = ['/', '/pricing', '/login', '/register', '/forgot-password', '/change-password'];

function isPublicPath(pathname) {
  if (!pathname) return false;
  const normalized = pathname.endsWith('/') && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
  return PUBLIC_PATHS.includes(normalized) || normalized.startsWith('/pricing');
}

export default function ClientLayout({ children }) {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (isPublicPath(pathname)) {
      return;
    }

    const token = typeof window !== 'undefined' ? localStorage.getItem('authToken') : null;
    if (!token) {
      // Not logged in — bounce to login before any protected content renders.
      router.replace('/login');
    }
  }, [pathname, router]);

  // Public/auth pages render without the app chrome.
  if (isPublicPath(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 lg:ml-64 min-w-0 pt-14 lg:pt-0">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
