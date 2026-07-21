'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect, useMemo, useSyncExternalStore } from 'react';
import {
  LayoutDashboard,
  PenTool,
  ClipboardList,
  Settings2,
  UploadCloud,
  BookOpen,
  Users,
  LogOut,
  GraduationCap,
  School,
  BarChart3,
  ShieldCheck,
  HelpCircle,
  Database,
  ListOrdered,
  Menu,
  X,
  Search,
  PanelLeftClose,
  PanelLeftOpen
} from 'lucide-react';

const ROLE_LABELS = {
  superadmin: 'Super Admin',
  school_admin: 'School Admin',
  teacher: 'Teacher',
};

function subscribeToAuthState(callback) {
  window.addEventListener('storage', callback);
  window.addEventListener('focus', callback);
  return () => {
    window.removeEventListener('storage', callback);
    window.removeEventListener('focus', callback);
  };
}

function getAuthTokenSnapshot() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('authToken');
}

function getAuthUserSnapshot() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('user');
}

function NavLink({ href, icon: Icon, label, active, onClick, isCollapsed }) {
  return (
    <div className="relative group">
      <Link
        href={href}
        onClick={onClick}
        className={`flex items-center ${
          isCollapsed ? 'justify-center w-[46px] h-[46px] mx-auto' : 'gap-3 px-4 py-3 w-full'
        } rounded-2xl text-[14px] font-medium transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] transform hover:scale-[1.02] active:scale-[0.98] ${
          active
            ? 'bg-white text-slate-900 shadow-sm shadow-slate-200/50 border border-slate-100'
            : 'text-slate-500 hover:bg-slate-100/60 hover:text-slate-900 border border-transparent'
        }`}
      >
        <Icon strokeWidth={active ? 2 : 1.75} className={`w-[22px] h-[22px] shrink-0 transition-colors duration-300 ${active ? 'text-indigo-600' : 'text-slate-400 group-hover:text-slate-600'}`} />
        {!isCollapsed && <span className="truncate">{label}</span>}
      </Link>
      
      {/* Tooltip for collapsed state */}
      {isCollapsed && (
        <div className="absolute left-full top-1/2 -translate-y-1/2 ml-4 px-3.5 py-2 bg-slate-800 text-white text-xs font-semibold rounded-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-300 whitespace-nowrap z-50 shadow-xl shadow-slate-900/20 border border-slate-700">
          {label}
        </div>
      )}
    </div>
  );
}

export default function Sidebar({ isCollapsed, setIsCollapsed }) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  
  const token = useSyncExternalStore(subscribeToAuthState, getAuthTokenSnapshot, () => null);
  const userData = useSyncExternalStore(subscribeToAuthState, getAuthUserSnapshot, () => null);
  const user = useMemo(() => {
    if (!userData) return null;
    try {
      return JSON.parse(userData);
    } catch {
      return null;
    }
  }, [userData]);
  
  const isAuthenticated = Boolean(token && userData);
  const [mounted, setMounted] = useState(false);
  
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (pathname === '/' || pathname === '/login') return;
    if (!isAuthenticated) router.replace('/login');
  }, [pathname, router, isAuthenticated, mounted]);

  const isAuthPage = pathname === '/' || pathname === '/login';
  if (!mounted || isAuthPage || !isAuthenticated) return null;

  const role = user?.role || 'teacher';
  const isSuperAdmin = role === 'superadmin';

  const superAdminItems = [
    { href: '/superadmin', icon: LayoutDashboard, label: 'Dashboard' },
    { href: '/superadmin/schools', icon: School, label: 'Schools' },
    { href: '/superadmin/vector-stores', icon: Database, label: 'Vector Stores' },
    { href: '/superadmin/cbse-patterns', icon: ClipboardList, label: 'CBSE Patterns' },
    { href: '/superadmin/queue', icon: ListOrdered, label: 'Queue' },
  ];

  const superAdminContentItems = [
    { href: '/materials/upload', icon: UploadCloud, label: 'Upload Material' },
    { href: '/materials', icon: BookOpen, label: 'Materials' },
  ];

  const mainItems = [
    { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { href: '/generator', icon: PenTool, label: 'Generate Paper' },
  ];

  const managementItems = [
    { href: '/patterns', icon: ClipboardList, label: 'Exam Patterns' },
    { href: '/blueprints', icon: Settings2, label: 'Blueprints' },
    { href: '/materials/upload', icon: UploadCloud, label: 'Upload Material' },
    { href: '/materials', icon: BookOpen, label: 'Materials' },
    { href: '/users', icon: Users, label: 'Users', roles: ['school_admin'] },
    { href: '/team-usage', icon: BarChart3, label: 'Team Usage', roles: ['school_admin'] },
  ];

  const handleLogout = () => {
    localStorage.removeItem('authToken');
    localStorage.removeItem('user');
    router.push('/');
    window.location.reload();
  };

  const isActive = (href) => {
    if (href === '/superadmin') return pathname === '/superadmin';
    if (href === '/materials' && pathname.startsWith('/materials/upload')) return false;
    return pathname === href || pathname.startsWith(href + '/');
  };

  return (
    <>
      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 left-0 right-0 h-14 bg-white border-b border-slate-100 flex items-center justify-between px-4 z-40">
        <div className="flex items-center min-w-0">
          <img src="/SHIKEN.jpg" alt="Shiken Logo" className="w-8 h-8 rounded-[10px] object-cover shrink-0 shadow-sm" />
          <span className="ml-3 text-[16px] font-black tracking-tight truncate text-slate-900 capitalize">
            Shiken
          </span>
        </div>
        <button
          onClick={() => setMobileOpen(true)}
          className="p-2 -mr-2 text-slate-600 hover:text-slate-900 active:scale-95 transition-transform"
        >
          <Menu className="w-6 h-6" />
        </button>
      </div>

      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-slate-900/30 z-40 backdrop-blur-sm transition-opacity duration-300"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar Container */}
      <div
        className={`${
          isCollapsed ? 'w-[88px]' : 'w-[260px]'
        } bg-[#FDFDFD] border-r border-slate-100/60 min-h-screen fixed left-0 top-0 flex flex-col z-50 transform transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] shadow-[4px_0_24px_rgba(0,0,0,0.01)] ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        } lg:translate-x-0`}
      >
        
        {/* Brand Header */}
        <div className={`h-[88px] flex items-center shrink-0 relative ${isCollapsed ? 'justify-center' : 'px-6 justify-between'}`}>
          <div className="flex items-center min-w-0">
            {/* Logo Icon */}
            <img 
              src="/SHIKEN.jpg" 
              alt="Shiken Logo" 
              className="w-10 h-10 rounded-2xl object-cover shrink-0 shadow-sm hover:scale-[1.03] transition-transform duration-300"
            />
            {/* Logo Text */}
            <div className={`ml-3.5 min-w-0 transition-opacity duration-300 ${isCollapsed ? 'opacity-0 hidden' : 'opacity-100'}`}>
              <span className="text-[18px] font-black tracking-wide truncate block text-slate-900 capitalize">
                Shiken
              </span>
            </div>
          </div>

          {/* Mobile Close Button */}
          <button
            onClick={() => setMobileOpen(false)}
            className="lg:hidden p-1.5 rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-600 shrink-0 active:scale-95 transition-all"
          >
            <X className="w-5 h-5" />
          </button>
          
          {/* Desktop Toggle Button */}
          <button 
            onClick={() => setIsCollapsed(!isCollapsed)}
            className={`hidden lg:flex absolute right-0 translate-x-1/2 w-8 h-8 bg-white border border-slate-200 rounded-full items-center justify-center text-slate-400 hover:text-slate-700 hover:border-slate-300 hover:scale-110 active:scale-95 shadow-sm transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] z-10 ${isCollapsed ? 'top-10' : 'top-10'}`}
          >
            {isCollapsed ? <PanelLeftOpen strokeWidth={1.5} className="w-[15px] h-[15px]" /> : <PanelLeftClose strokeWidth={1.5} className="w-[15px] h-[15px]" />}
          </button>
        </div>

        {/* Navigation */}
        <nav className={`flex-1 overflow-y-auto py-4 flex flex-col gap-6 ${isCollapsed ? 'px-3 scrollbar-hide [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]' : 'px-4 custom-scrollbar'}`}>
          {isSuperAdmin ? (
            <>
              <div>
                {!isCollapsed && <p className="px-4 mb-3 text-[11px] font-bold tracking-widest text-slate-400/80 uppercase">Main Menu</p>}
                <div className="space-y-1.5">
                  {superAdminItems.map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} onClick={() => setMobileOpen(false)} isCollapsed={isCollapsed} />
                  ))}
                </div>
              </div>
              <div>
                {!isCollapsed && <p className="px-4 mb-3 text-[11px] font-bold tracking-widest text-slate-400/80 uppercase">Teams</p>}
                <div className="space-y-1.5">
                  {superAdminContentItems.map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} onClick={() => setMobileOpen(false)} isCollapsed={isCollapsed} />
                  ))}
                </div>
              </div>
            </>
          ) : (
            <>
              <div>
                {!isCollapsed && <p className="px-4 mb-3 text-[11px] font-bold tracking-widest text-slate-400/80 uppercase">Main Menu</p>}
                <div className="space-y-1.5">
                  {mainItems.map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} onClick={() => setMobileOpen(false)} isCollapsed={isCollapsed} />
                  ))}
                </div>
              </div>

              <div>
                {!isCollapsed && <p className="px-4 mb-3 text-[11px] font-bold tracking-widest text-slate-400/80 uppercase">Teams</p>}
                <div className="space-y-1.5">
                  {managementItems.filter(item => !item.roles || item.roles.includes(role)).map((item) => (
                    <NavLink key={item.href} {...item} active={isActive(item.href)} onClick={() => setMobileOpen(false)} isCollapsed={isCollapsed} />
                  ))}
                </div>
              </div>
            </>
          )}

          <div className="mt-auto space-y-1.5">
            <NavLink href="/manual" icon={HelpCircle} label="Help center" active={isActive('/manual')} onClick={() => setMobileOpen(false)} isCollapsed={isCollapsed} />
          </div>
        </nav>

        {/* Bottom Section: User Profile */}
        <div className={`p-5 shrink-0 border-t border-slate-100/60 ${isCollapsed ? 'flex flex-col items-center' : ''}`}>
          {user && (
            <div className={`flex items-center ${isCollapsed ? 'justify-center' : 'justify-between'} w-full`}>
              <div className="relative group">
                <div className={`w-[46px] h-[46px] rounded-2xl bg-indigo-50 flex items-center justify-center shrink-0 border border-indigo-100/50 shadow-sm transition-transform duration-300 hover:scale-[1.03] active:scale-95 cursor-pointer`}>
                  <img src={`https://ui-avatars.com/api/?name=${user.username}&background=eff6ff&color=4f46e5&bold=true`} alt="Avatar" className="w-full h-full object-cover rounded-2xl" />
                </div>
                
                {/* Tooltip for collapsed user avatar */}
                {isCollapsed && (
                  <div className="absolute left-full top-1/2 -translate-y-1/2 ml-4 px-3.5 py-2.5 bg-slate-800 text-white text-xs font-medium rounded-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-300 whitespace-nowrap z-50 shadow-xl shadow-slate-900/20 border border-slate-700">
                    <p className="font-bold text-[13px]">{user.username}</p>
                    <p className="text-slate-300 mt-0.5">{ROLE_LABELS[role]}</p>
                  </div>
                )}
              </div>
              
              {!isCollapsed && (
                <>
                  <div className="ml-3.5 min-w-0 pr-2 flex-1">
                    <p className="text-[14px] font-bold truncate text-slate-900 tracking-tight">{user.username}</p>
                    <p className="text-[12px] truncate text-slate-500 font-medium">{ROLE_LABELS[role] || 'Member'}</p>
                  </div>
                  <button 
                    onClick={handleLogout}
                    className="p-2.5 rounded-2xl text-slate-400 hover:bg-red-50 hover:text-red-600 transition-all duration-300 hover:scale-[1.05] active:scale-95 shrink-0"
                    title="Logout"
                  >
                    <LogOut strokeWidth={1.75} className="w-[18px] h-[18px]" />
                  </button>
                </>
              )}
            </div>
          )}
          
          {/* Logout for collapsed state */}
          {isCollapsed && user && (
            <div className="relative group mt-3 w-full flex justify-center">
              <button 
                onClick={handleLogout}
                className="w-[46px] h-[46px] flex items-center justify-center rounded-2xl text-slate-400 hover:bg-red-50 hover:text-red-600 transition-all duration-300 hover:scale-[1.05] active:scale-95 shadow-sm"
                title="Logout"
              >
                <LogOut strokeWidth={1.75} className="w-[18px] h-[18px]" />
              </button>
              <div className="absolute left-full top-1/2 -translate-y-1/2 ml-4 px-3.5 py-2 bg-red-600 text-white text-xs font-bold rounded-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-300 whitespace-nowrap z-50 shadow-xl shadow-red-900/20 border border-red-700">
                Logout
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
