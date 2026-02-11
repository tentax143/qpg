'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { 
  LayoutDashboard, 
  PenTool, 
  ClipboardList, 
  Settings2, 
  UploadCloud, 
  BookOpen, 
  Users, 
  Zap, 
  LogOut, 
  User,
  Settings,
  ChevronUp,
  GraduationCap
} from 'lucide-react';

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [showUserMenu, setShowUserMenu] = useState(false);

  useEffect(() => {
    // Check if user is authenticated
    const token = localStorage.getItem('authToken');
    const userData = localStorage.getItem('user');
    
    if (token && userData) {
      setIsAuthenticated(true);
      setUser(JSON.parse(userData));
    } else {
      setIsAuthenticated(false);
    }
  }, [pathname]);

  // Hide sidebar on auth pages
  const isAuthPage = pathname === '/' || pathname === '/login' || pathname === '/register';
  
  if (isAuthPage || !isAuthenticated) {
    return null;
  }

  const mainItems = [
    { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { href: '/generator', icon: PenTool, label: 'Generate Paper' },
  ];

  const managementItems = [
    { href: '/patterns', icon: ClipboardList, label: 'Exam Patterns' },
    { href: '/blueprints', icon: Settings2, label: 'Blueprints' },
    { href: '/materials/upload', icon: UploadCloud, label: 'Upload Material' },
    { href: '/materials', icon: BookOpen, label: 'Materials & Lessons' },
    { href: '/users', icon: Users, label: 'Users' },
  ];

  const handleLogout = () => {
    localStorage.removeItem('authToken');
    localStorage.removeItem('user');
    router.push('/');
    window.location.reload();
  };

  const isActive = (href) => {
    return pathname === href;
  };

  return (
    <div className="w-64 backdrop-blur-xl bg-white/70 border-r border-blue-100 min-h-screen fixed left-0 top-0 flex flex-col shadow-xl shadow-blue-500/5 z-50">
      {/* Brand */}
      <div className="px-6 py-8 border-b border-blue-50 flex items-center justify-center gap-3">
        <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20 transform rotate-3">
          <GraduationCap className="w-6 h-6 text-white" />
        </div>
        <span className="text-xl font-black text-gray-900 tracking-tight">QPG <span className="text-blue-600">AI</span></span>
      </div>

      {/* Navigation Scroll Area */}
      <nav className="flex-1 px-4 py-8 overflow-y-auto space-y-8 custom-scrollbar">
        {/* Main Section */}
        <div>
          <p className="px-3 text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4">Main</p>
          <div className="space-y-1">
            {mainItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 group hover:-translate-y-0.5 active:scale-95 ${
                    active
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20 active-nav-glow'
                      : 'text-gray-600 hover:bg-white hover:text-blue-600 hover:shadow-lg hover:shadow-blue-500/5'
                  }`}
                >
                  <Icon className={`w-5 h-5 transition-transform duration-300 ${active ? '' : 'group-hover:scale-110 group-hover:rotate-3'}`} />
                  <span className="font-bold text-sm tracking-tight">{item.label}</span>
                  {active && <div className="ml-auto w-1.5 h-1.5 bg-white rounded-full animate-pulse"></div>}
                </Link>
              );
            })}
          </div>
        </div>

        {/* Management Section */}
        <div>
          <p className="px-3 text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4">Management</p>
          <div className="space-y-1">
            {managementItems.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 group hover:-translate-y-0.5 active:scale-95 ${
                    active
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20 active-nav-glow'
                      : 'text-gray-600 hover:bg-white hover:text-blue-600 hover:shadow-lg hover:shadow-blue-500/5'
                  }`}
                >
                  <Icon className={`w-5 h-5 transition-transform duration-300 ${active ? '' : 'group-hover:scale-110 group-hover:rotate-3'}`} />
                  <span className="font-bold text-sm tracking-tight">{item.label}</span>
                  {active && <div className="ml-auto w-1.5 h-1.5 bg-white rounded-full animate-pulse"></div>}
                </Link>
              );
            })}
          </div>
        </div>
      </nav>

      {/* Footer Profile Section */}
      <div className="px-4 py-6 border-t border-blue-50 bg-white/30">
        {user && (
          <div className="relative">
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="w-full flex items-center gap-3 p-2 rounded-xl text-gray-700 hover:bg-white transition-all text-left text-sm group"
            >
              <div className="w-10 h-10 bg-blue-600 text-white rounded-xl flex items-center justify-center font-black shadow-lg shadow-blue-100 group-hover:scale-105 transition-transform">
                {user.username.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-black text-gray-900 truncate tracking-tight">{user.username}</p>
                <p className="text-[10px] font-bold text-blue-600 uppercase tracking-widest truncate">
                  {user.is_staff ? 'Administrator' : 'Academic Member'}
                </p>
              </div>
              <ChevronUp className={`w-4 h-4 text-gray-500 transition-transform duration-300 ${showUserMenu ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown Menu */}
            {showUserMenu && (
              <div className="absolute bottom-full left-0 right-0 mb-3 bg-white border border-blue-50 rounded-2xl shadow-2xl py-2 z-50 animate-in fade-in slide-in-from-bottom-4 duration-300">
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 transition-colors font-bold mx-2 rounded-xl text-left"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Logout</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
   