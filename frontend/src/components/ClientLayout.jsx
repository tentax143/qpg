'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
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
  const [isCollapsed, setIsCollapsed] = useState(false);

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
    <div className="flex min-h-screen bg-[#F5F5F7]">
      <Sidebar isCollapsed={isCollapsed} setIsCollapsed={setIsCollapsed} />
      <main className={`flex-1 min-w-0 pt-14 lg:pt-0 transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] ${isCollapsed ? 'lg:ml-[88px]' : 'lg:ml-[260px]'}`}>
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
