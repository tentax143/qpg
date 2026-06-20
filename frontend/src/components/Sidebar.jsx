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
  LogOut,
  ChevronUp,
  GraduationCap,
  School,
  BarChart3,
  ShieldCheck,
  HelpCircle,
} from 'lucide-react';

const ROLE_LABELS = {
  superadmin: 'Super Admin',
  school_admin: 'School Admin',
  teacher: 'Teacher',
};

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [showUserMenu, setShowUserMenu] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('authToken');
    const userData = localStorage.getItem('user');
    if (token && userData) {
      setIsAuthenticated(true);
      setUser(JSON.parse(userData));
    } else {
      setIsAuthenticated(false);
    }
  }, [pathname]);

  const isAuthPage = pathname === '/' || pathname === '/login';
  if (isAuthPage || !isAuthenticated) return null;

  const role = user?.role || 'teacher';
  const isSuperAdmin = role === 'superadmin';

  // SuperAdmin navigation
  const superAdminItems = [
    { href: '/superadmin', icon: LayoutDashboard, label: 'Dashboard' },
    { href: '/superadmin/schools', icon: School, label: 'Schools' },
    { href: '/superadmin/cbse-patterns', icon: ClipboardList, label: 'CBSE Patterns' },
  ];

  // Regular user navigation
  const mainItems = [
    { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { href: '/generator', icon: PenTool, label: 'Generate Paper' },
  ];

  const managementItems = [
    { href: '/patterns', icon: ClipboardList, label: 'Exam Patterns' },
    { href: '/blueprints', icon: Settings2, label: 'Blueprints' },
    { href: '/materials/upload', icon: UploadCloud, label: 'Upload Material' },
    { href: '/materials', icon: BookOpen, label: 'Materials' },
    { href: '/users', icon: Users, label: 'Users' },
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
    return pathname === href || pathname.startsWith(href + '/');
  };

  const NavLink = ({ href, icon: Icon, label }) => {
    const active = isActive(href);
    return (
      <Link
        href={href}
        className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors duration-150 ${
          active
            ? 'bg-blue-50 text-blue-700 font-medium'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
        }`}
      >
        <Icon className="w-4 h-4 shrink-0" />
        <span>{label}</span>
      </Link>
    );
  };

  return (
    <div className="w-64 bg-white border-r border-slate-200 min-h-screen fixed left-0 top-0 flex flex-col z-50">
      {/* Brand */}
      <div className="h-16 px-5 flex items-center border-b border-slate-200 shrink-0">
        <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shrink-0">
          <GraduationCap className="w-4 h-4 text-white" />
        </div>
        <div className="ml-3 min-w-0">
          <span className="text-[15px] font-semibold text-slate-900 tracking-tight truncate block">
            {isSuperAdmin ? 'QPG' : (user?.school_name || 'QPG')}
          </span>
          {isSuperAdmin && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
              <ShieldCheck className="w-2.5 h-2.5" />
              Admin
            </span>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto custom-scrollbar space-y-5">
        {isSuperAdmin ? (
          <div>
            <p className="px-3 mb-1.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider">Administration</p>
            <div className="space-y-0.5">
              {superAdminItems.map((item) => (
                <NavLink key={item.href} {...item} />
              ))}
            </div>
          </div>
        ) : (
          <>
            <div>
              <p className="px-3 mb-1.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider">Main</p>
              <div className="space-y-0.5">
                {mainItems.map((item) => (
                  <NavLink key={item.href} {...item} />
                ))}
              </div>
            </div>

            <div>
              <p className="px-3 mb-1.5 text-[11px] font-medium text-slate-400 uppercase tracking-wider">Management</p>
              <div className="space-y-0.5">
                {managementItems.filter(item => !item.roles || item.roles.includes(role)).map((item) => (
                  <NavLink key={item.href} {...item} />
                ))}
              </div>
            </div>
          </>
        )}

        <div className="pt-2 border-t border-slate-100">
          <NavLink href="/manual" icon={HelpCircle} label="User Manual" />
        </div>
      </nav>

      {/* User footer */}
      <div className="px-3 py-3 border-t border-slate-200 shrink-0 relative">
        {user && (
          <>
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md hover:bg-slate-100 transition-colors text-left"
            >
              <div className={`w-7 h-7 rounded-md flex items-center justify-center text-white text-xs font-semibold shrink-0 ${isSuperAdmin ? 'bg-amber-600' : 'bg-blue-600'}`}>
                {user.username.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-900 truncate">{user.username}</p>
                <p className="text-xs text-slate-500 truncate">{ROLE_LABELS[role] || 'Member'}</p>
                {!isSuperAdmin && user.school_name && (
                  <p className="text-[11px] text-slate-400 truncate">{user.school_name}</p>
                )}
              </div>
              <ChevronUp className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ${showUserMenu ? '' : 'rotate-180'}`} />
            </button>

            {showUserMenu && (
              <div className="absolute bottom-full left-3 right-3 mb-1 bg-white border border-slate-200 rounded-lg shadow-lg py-1 z-50">
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors rounded-md"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Log out</span>
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
