'use client';

import { usePathname } from 'next/navigation';
import Sidebar from './Sidebar';

const AUTH_PATHS = ['/login'];

export default function ClientLayout({ children }) {
  const pathname = usePathname();

  if (AUTH_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 lg:ml-64 min-w-0">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
