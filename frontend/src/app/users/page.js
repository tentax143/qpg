'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  Users as UsersIcon, Plus, Search, Mail, 
  Shield, UserCheck, Trash2, ShieldAlert,
  UserPlus, Lock, CheckCircle, Clock,
  Calendar, Layers, BookOpen, GraduationCap, ArrowRight,
  Sparkles, ShieldCheck
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import LoadingSpinner from '@/components/LoadingSpinner';

const ROLE_BADGE = {
  superadmin: 'bg-amber-100/80 text-amber-700 border border-amber-200/60',
  school_admin: 'bg-violet-100/80 text-violet-700 border border-violet-200/60',
  teacher: 'bg-slate-100/80 text-slate-600 border border-slate-200/60',
};

export default function UsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState([]);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [subjects, setSubjects] = useState([]);

  // New User Form State
  const [newUser, setNewUser] = useState({
    username: '',
    password: '',
    email: '',
    is_staff: false,
    allowed_subject: ''
  });

  useEffect(() => {
    const stored = localStorage.getItem('user');
    const u = stored ? JSON.parse(stored) : null;
    setCurrentUser(u);
    if (u && u.role !== 'school_admin' && u.role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    fetchData();
    apiClient.get('/subjects/').then(r => setSubjects(r.data.subjects || [])).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [usersRes, papersRes] = await Promise.all([
        apiClient.get('/users/'),
        apiClient.get('/papers/?page_size=1000')
      ]);
      setUsers(usersRes.data || []);
      setPapers(papersRes.data.results || []);
    } catch (err) {
      setError('Failed to load administrative data');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    try {
      await apiClient.post('/users/', {
        ...newUser,
        allowed_subject: newUser.allowed_subject || null,
      });
      setSuccess(`User ${newUser.username} created successfully`);
      setNewUser({ username: '', password: '', email: '', is_staff: false, allowed_subject: '' });
      fetchData();
    } catch (err) {
      setError(err.response?.data?.error || err.response?.data?.username?.[0] || 'Failed to create user');
    }
  };

  const handleDeleteUser = async (id, username) => {
    if (!confirm(`Are you sure you want to delete user ${username}?`)) return;
    try {
      await apiClient.delete(`/users/${id}/`);
      setSuccess('User deleted');
      fetchData();
    } catch (err) {
      setError('Failed to delete user');
    }
  };

  // Group papers by class then subject
  const groupedPapers = papers.reduce((acc, paper) => {
    const classKey = paper.class_name;
    const subjectKey = paper.subject;
    
    if (!acc[classKey]) acc[classKey] = {};
    if (!acc[classKey][subjectKey]) acc[classKey][subjectKey] = [];
    
    acc[classKey][subjectKey].push(paper);
    return acc;
  }, {});

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-slate-200 border-t-indigo-600 rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="w-full pb-20 relative">
      {/* Decorative background blobs */}
      <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-indigo-400/10 rounded-full blur-3xl pointer-events-none -z-10" />
      <div className="absolute top-40 right-1/4 w-[400px] h-[400px] bg-purple-400/10 rounded-full blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <div className="mb-10 max-w-7xl mx-auto flex flex-col xl:flex-row xl:items-end justify-between gap-6">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white border border-slate-200/60 shadow-sm rounded-full mb-3">
            <Sparkles size={14} className="text-indigo-500" strokeWidth={2} />
            <span className="text-[11px] font-bold text-slate-700 uppercase tracking-widest">Administration</span>
            {currentUser?.school_name && (
              <>
                <div className="w-1 h-1 rounded-full bg-slate-300"></div>
                <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">{currentUser.school_name}</span>
              </>
            )}
          </div>
          <h1 className="text-[32px] font-extrabold text-slate-900 tracking-tight leading-tight mb-2">User Management</h1>
          <p className="text-[15px] text-slate-500 leading-relaxed max-w-lg">Configure access and review generated content across the system.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <button 
            onClick={() => window.history.back()} 
            className="px-6 py-3.5 bg-white border border-slate-200 text-slate-700 rounded-2xl font-bold text-[13px] hover:bg-slate-50 hover:text-indigo-600 hover:border-indigo-200 transition-all active:scale-[0.98] flex items-center gap-2 shadow-sm"
          >
            <ArrowRight size={16} className="rotate-180" />
            Back to Safety
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto">
        {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-6" />}
        {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-6" />}

        {/* Create User Card */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] mb-12">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-slate-900 text-white rounded-2xl flex items-center justify-center shadow-md">
              <UserPlus size={20} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Create New User</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Initialize a new faculty or admin account</p>
            </div>
          </div>
          <form onSubmit={handleCreateUser} className="p-8">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start mb-8">
              <div className="space-y-3">
                <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-1">Username</label>
                <input
                  type="text"
                  required
                  value={newUser.username}
                  onChange={(e) => setNewUser({...newUser, username: e.target.value})}
                  placeholder="Enter username"
                  className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all duration-300 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm"
                />
              </div>

              <div className="space-y-3">
                <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-1">Temporary Password</label>
                <div className="relative">
                  <input
                    type="password"
                    required
                    value={newUser.password}
                    onChange={(e) => setNewUser({...newUser, password: e.target.value})}
                    placeholder="Set password"
                    className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all duration-300 font-bold text-slate-900 placeholder:text-slate-400 shadow-sm"
                  />
                  <Lock size={16} className="absolute right-5 top-1/2 -translate-y-1/2 text-slate-400" />
                </div>
                <p className="text-[10px] text-slate-500 font-bold ml-1 tracking-wide">User will be asked to change on first login.</p>
              </div>

              {(!currentUser || currentUser.role === 'superadmin' || currentUser.is_superuser) && (
                <div className="lg:pt-[26px]">
                  <label className="flex items-center gap-4 group cursor-pointer p-4 bg-white border border-slate-200 rounded-2xl hover:border-indigo-300 hover:shadow-sm transition-all duration-300 shadow-sm h-[58px]">
                    <div className={`w-5 h-5 rounded-md border-2 flex items-center justify-center transition-all duration-300 ${newUser.is_staff ? 'bg-indigo-600 border-indigo-600' : 'border-slate-300 bg-white'}`}>
                      <input
                        type="checkbox"
                        className="hidden"
                        checked={newUser.is_staff}
                        onChange={(e) => setNewUser({...newUser, is_staff: e.target.checked})}
                      />
                      {newUser.is_staff && <Shield size={12} className="text-white" />}
                    </div>
                    <span className="text-[13px] font-bold text-slate-700">Assign Staff Privileges</span>
                  </label>
                </div>
              )}
            </div>

            <div className="mb-8 max-w-lg">
              <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider ml-1 block mb-3">Subject Restriction</label>
              <select
                value={newUser.allowed_subject}
                onChange={e => setNewUser(p => ({ ...p, allowed_subject: e.target.value }))}
                className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all duration-300 font-bold text-slate-900 shadow-sm"
              >
                <option value="">All Subjects (no restriction)</option>
                {subjects.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <p className="mt-2 text-[10px] text-slate-500 font-medium ml-1 tracking-wide">If set, this user can only generate papers and upload materials for this subject.</p>
            </div>

            <div className="flex justify-end pt-6 border-t border-slate-100">
              <button type="submit" className="bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white px-8 py-3.5 rounded-2xl font-bold text-[13px] transition-all duration-300 shadow-lg shadow-indigo-200/50 active:scale-[0.98] flex items-center gap-2">
                <UserPlus size={16} strokeWidth={2.5} />
                Initialize User
              </button>
            </div>
          </form>
        </div>

        {/* Existing Users Table */}
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] mb-12">
          <div className="px-8 py-6 border-b border-slate-100 flex items-center gap-4 bg-slate-50/50">
            <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center border border-indigo-100">
              <ShieldCheck size={20} />
            </div>
            <div>
              <h2 className="text-[18px] font-bold text-slate-900 tracking-tight">Authorized Personnel</h2>
              <p className="text-[12px] text-slate-500 font-medium mt-0.5">Manage existing user accounts and clearances</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-slate-50/80 text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-100">
                <tr>
                  <th className="px-8 py-5">Profile</th>
                  <th className="px-6 py-5">Clearance & Scope</th>
                  <th className="px-6 py-5">Last Activity</th>
                  <th className="px-6 py-5">Registered</th>
                  <th className="px-8 py-5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 bg-white/50">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-50/80 transition-colors group">
                    <td className="px-8 py-5">
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-[12px] font-extrabold shadow-sm ${u.is_superuser ? 'bg-amber-100 text-amber-700' : 'bg-indigo-100 text-indigo-700'}`}>
                          {u.username.substring(0, 2).toUpperCase()}
                        </div>
                        <span className="text-[14px] font-bold text-slate-900">{u.username}</span>
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex flex-col items-start gap-2">
                        <span className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${ROLE_BADGE[u.role] || ROLE_BADGE.teacher}`}>
                          {u.role === 'superadmin' ? 'Super Admin' : u.role === 'school_admin' ? 'School Admin' : 'Teacher'}
                        </span>
                        {u.school_name && <span className="text-[11px] font-semibold text-slate-500">{u.school_name}</span>}
                        {u.allowed_subject && (
                          <span className="px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-600 border border-indigo-100">
                            {u.allowed_subject}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-500">
                        <Clock size={14} className="text-slate-400" />
                        {u.last_login ? new Date(u.last_login).toLocaleDateString('en-US', {month:'short', day:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'}) : 'Never'}
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-500">
                        <Calendar size={14} className="text-slate-400" />
                        {new Date(u.date_joined).toLocaleDateString('en-US', {month:'short', day:'2-digit', year:'numeric'})}
                      </div>
                    </td>
                    <td className="px-8 py-5 text-right">
                      {!u.is_superuser && (
                        <button 
                          onClick={() => handleDeleteUser(u.id, u.username)}
                          className="bg-white border border-red-200 text-red-500 hover:bg-red-50 hover:text-red-600 px-4 py-2 rounded-xl text-[11px] font-bold transition-all duration-300 shadow-sm active:scale-95"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Question Papers Overview Section */}
        <div className="space-y-6">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center border border-emerald-100">
              <Layers size={22} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-[24px] font-extrabold text-slate-900 tracking-tight">Inventory Census</h2>
              <p className="text-[13px] font-medium text-slate-500 mt-1">Question Papers Grouped by Class and Subject</p>
            </div>
          </div>
          
          {Object.entries(groupedPapers).sort((a,b) => a[0] - b[0]).map(([className, subjects]) => (
            <div key={className} className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-[28px] overflow-hidden shadow-[0_8px_30px_rgb(0,0,0,0.04)] mb-8">
              <div className="bg-slate-900 text-white px-8 py-5 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-slate-800 rounded-xl flex items-center justify-center border border-slate-700">
                    <GraduationCap size={18} />
                  </div>
                  <span className="text-[15px] font-bold uppercase tracking-wider">Class: {className}</span>
                </div>
                <div className="text-[12px] font-bold text-slate-400 bg-slate-800 px-3 py-1 rounded-lg border border-slate-700">
                  {Object.keys(subjects).length} Subjects Active
                </div>
              </div>

              <div className="p-6 space-y-6">
                {Object.entries(subjects).map(([subject, paperList]) => (
                  <div key={`${className}-${subject}`} className="bg-white border border-slate-100 rounded-[20px] overflow-hidden shadow-sm">
                    <div className="px-6 py-4 bg-slate-50/80 border-b border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <BookOpen size={16} className="text-indigo-500" />
                        <span className="text-[13px] font-bold text-slate-700 uppercase tracking-wider">
                          Subject: <span className="text-indigo-600">{subject}</span>
                        </span>
                      </div>
                      <span className="text-[11px] font-bold text-slate-500 bg-white px-2 py-1 rounded-md border border-slate-200">{paperList.length} Papers</span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-[13px]">
                        <thead className="bg-white text-[11px] font-bold uppercase text-slate-400 tracking-wider border-b border-slate-50">
                          <tr>
                            <th className="px-6 py-4">Blueprint / Pattern</th>
                            <th className="px-6 py-4">Difficulty</th>
                            <th className="px-6 py-4">Generated</th>
                            <th className="px-6 py-4">Status</th>
                            <th className="px-6 py-4 text-right">Link</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-50 bg-white/30">
                          {paperList.map((paper) => (
                            <tr key={paper.id} className="hover:bg-slate-50/50 transition-all duration-300 group/row">
                              <td className="px-6 py-4 font-bold text-slate-900 group-hover/row:text-indigo-600 transition-colors">{paper.pattern_name || 'Standard'}</td>
                              <td className="px-6 py-4 font-semibold text-slate-600 capitalize">{paper.difficulty}</td>
                              <td className="px-6 py-4 text-slate-500 font-medium">
                                {new Date(paper.created_at).toLocaleString('en-US', {
                                  year: 'numeric', month: 'short', day: 'numeric'
                                })}
                              </td>
                              <td className="px-6 py-4">
                                <span className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all duration-300 ${
                                  paper.status === 'done' ? 'bg-emerald-50 text-emerald-600 border border-emerald-100/50' : 
                                  paper.status === 'failed' ? 'bg-red-50 text-red-600 border border-red-100/50' : 'bg-amber-50 text-amber-600 border border-amber-100/50'
                                }`}>
                                  {paper.status}
                                </span>
                              </td>
                              <td className="px-6 py-4 text-right">
                                {paper.file ? (
                                  <a 
                                    href={paper.file} 
                                    target="_blank" 
                                    className="text-[12px] font-bold text-indigo-600 hover:text-indigo-800 transition-all duration-300 flex items-center justify-end gap-1.5 group/btn"
                                  >
                                    View <ArrowRight size={14} className="group-hover/btn:translate-x-1 transition-transform" />
                                  </a>
                                ) : (
                                  <span className="text-[11px] font-semibold text-slate-400 italic">Processing...</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
