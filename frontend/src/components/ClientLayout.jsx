'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { GoogleOAuthProvider } from '@react-oauth/google';
import Sidebar from './Sidebar';
import TrialBanner from './TrialBanner';

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '';

// Pages reachable without a session (the root "/" is itself the login screen).
const PUBLIC_PATHS = ['/', '/login', '/register', '/forgot-password', '/change-password', '/onboarding'];

function isPublicPath(pathname) {
  return PUBLIC_PATHS.includes(pathname);
}

export default function ClientLayout({ children }) {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <ClientLayoutInner>{children}</ClientLayoutInner>
    </GoogleOAuthProvider>
  );
}

function ClientLayoutInner({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  // null = checking, true = authed/public (render), false = redirecting
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isPublicPath(pathname)) {
      setReady(true);
      return;
    }
    const token = typeof window !== 'undefined' ? localStorage.getItem('authToken') : null;
    if (!token) {
      // Not logged in — bounce to login before any protected content renders.
      router.replace('/login');
      setReady(false);
      return;
    }
    setReady(true);
  }, [pathname, router]);

  // Public/auth pages render without the app chrome.
  if (isPublicPath(pathname)) {
    return <>{children}</>;
  }

  // Protected page, auth not yet confirmed → render nothing (prevents flashing
  // the page for logged-out users while the redirect happens).
  if (!ready) {
    return null;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 lg:ml-64 min-w-0 flex flex-col">
        <TrialBanner />
        <main className="flex-1">
          <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
