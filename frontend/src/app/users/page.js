'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  Users as UsersIcon, Plus, Search, Mail, 
  Shield, UserCheck, Trash2, ShieldAlert,
  UserPlus, Lock, CheckCircle, Clock,
  Calendar, Layers, BookOpen, GraduationCap, ArrowRight
} from 'lucide-react';
import apiClient from '@/lib/api';
import ErrorAlert from '@/components/ErrorAlert';
import SuccessAlert from '@/components/SuccessAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import UpgradeModal from '@/components/UpgradeModal';

const ROLE_BADGE = {
  superadmin: 'bg-amber-100/80 text-amber-700 border border-amber-200',
  school_admin: 'bg-violet-100/80 text-violet-700 border border-violet-200',
  teacher: 'bg-gray-100/80 text-gray-600 border border-gray-300',
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
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);

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
    // Only school admins / superadmins manage users — bounce teachers away.
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
      // Use standard REST API; auth_views.py handles password hashing correctly
      await apiClient.post('/users/', {
        ...newUser,
        allowed_subject: newUser.allowed_subject || null,
      });
      setSuccess(`User ${newUser.username} created successfully`);
      setNewUser({ username: '', password: '', email: '', is_staff: false, allowed_subject: '' });
      fetchData();
    } catch (err) {
      // HTTP 402 means the teacher plan limit was hit — show the upgrade wall
      if (err.response?.status === 402) {
        setShowUpgradeModal(true);
      } else {
        setError(err.response?.data?.error || err.response?.data?.username?.[0] || 'Failed to create user');
      }
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

  if (loading) return <LoadingSpinner message="Loading administrative panel..." />;

  return (
    <div className="w-full relative py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 mb-12">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-blue-50 text-blue-600 text-[10px] font-black uppercase tracking-wider rounded-full">Administration</span>
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
            {currentUser?.school_name && (
              <span className="px-3 py-1 bg-slate-100 text-slate-600 text-[10px] font-black uppercase tracking-wider rounded-full">{currentUser.school_name}</span>
            )}
          </div>
          <h1 className="text-4xl font-black text-gray-900 leading-tight tracking-tight">User Management</h1>
          <p className="text-gray-600 font-medium text-lg mt-1 tracking-tight">Configure access and review generated content across the system.</p>
        </div>
        <button 
          onClick={() => window.history.back()} 
          className="px-6 py-3 bg-white border border-gray-200 rounded-2xl font-black text-[10px] uppercase tracking-widest text-gray-500 hover:text-blue-600 hover:border-blue-200 hover:shadow-xl hover:shadow-blue-500/10 transition-all duration-300 hover:-translate-y-0.5 active:scale-95"
        >
          Back to Safety
        </button>
      </div>

      {error && <ErrorAlert message={error} onClose={() => setError(null)} className="mb-8" />}
      {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} className="mb-8" />}

      {/* Create User Card */}
      <div className="glass-card overflow-hidden mb-12 hover:shadow-2xl transition-shadow duration-500">
        <div className="p-6 border-b border-gray-100 bg-white/50 flex items-center gap-3">
          <div className="w-8 h-8 bg-[#1e293b] text-white rounded-lg flex items-center justify-center shadow-lg shadow-slate-200">
            <UserPlus size={16} />
          </div>
          <h2 className="font-black text-gray-900 text-sm tracking-tight uppercase">Create New User</h2>
        </div>
        <form onSubmit={handleCreateUser} className="p-10">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start mb-10">
            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1">Username</label>
              <input
                type="text"
                required
                value={newUser.username}
                onChange={(e) => setNewUser({...newUser, username: e.target.value})}
                placeholder="Enter username"
                className="w-full px-5 py-4 bg-gray-50/80 border border-gray-200 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all duration-300 font-bold text-gray-900 placeholder:text-gray-300"
              />
            </div>

            <div className="space-y-3">
              <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1">Temporary Password</label>
              <div className="relative">
                <input
                  type="password"
                  required
                  value={newUser.password}
                  onChange={(e) => setNewUser({...newUser, password: e.target.value})}
                  placeholder="Set password"
                  className="w-full px-5 py-4 bg-gray-50/80 border border-gray-200 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all duration-300 font-bold text-gray-900 placeholder:text-gray-300"
                />
                <Lock size={16} className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              <p className="text-[9px] text-gray-500 font-bold ml-1 uppercase tracking-wider italic">User will be asked to change on first login.</p>
            </div>

            {(!currentUser || currentUser.role === 'superadmin' || currentUser.is_superuser) && (
              <div className="lg:pt-10">
                <label className="flex items-center gap-4 group cursor-pointer p-4 bg-gray-50/80 border border-gray-200 rounded-2xl hover:bg-white hover:shadow-lg hover:shadow-gray-200/50 transition-all duration-300 hover:-translate-y-0.5">
                  <div className={`w-6 h-6 rounded-lg border-2 flex items-center justify-center transition-all duration-300 ${newUser.is_staff ? 'bg-[#1e293b] border-[#1e293b]' : 'border-gray-200 bg-white'}`}>
                    <input
                      type="checkbox"
                      className="hidden"
                      checked={newUser.is_staff}
                      onChange={(e) => setNewUser({...newUser, is_staff: e.target.checked})}
                    />
                    {newUser.is_staff && <Shield size={12} className="text-white" />}
                  </div>
                  <span className="text-xs font-black text-gray-700 uppercase tracking-widest">Assign Staff Privileges</span>
                </label>
              </div>
            )}
          </div>

          <div className="mb-10">
            <label className="text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 block mb-3">Subject Restriction</label>
            <select
              value={newUser.allowed_subject}
              onChange={e => setNewUser(p => ({ ...p, allowed_subject: e.target.value }))}
              className="w-full px-5 py-4 bg-gray-50/80 border border-gray-200 rounded-2xl focus:ring-4 focus:ring-[#1e293b]/5 focus:border-[#1e293b] outline-none transition-all duration-300 font-bold text-gray-900"
            >
              <option value="">All Subjects (no restriction)</option>
              {subjects.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <p className="mt-1 text-[9px] text-gray-500 font-bold ml-1 uppercase tracking-wider italic">If set, this user can only generate papers and upload materials for this subject.</p>
          </div>

          <div className="flex justify-end">
            <button type="submit" className="bg-[#1e293b] text-white px-10 py-4 rounded-2xl font-black text-[10px] uppercase tracking-[0.2em] hover:bg-slate-800 transition-all duration-300 shadow-xl shadow-slate-200 active:scale-95 hover:-translate-y-1 flex items-center gap-3 group">
              <UserPlus size={16} className="group-hover:rotate-12 transition-transform duration-300" />
              Initialize User
            </button>
          </div>
        </form>
      </div>

      {/* Existing Users Table */}
      <div className="glass-card overflow-hidden mb-16 hover:shadow-2xl transition-shadow duration-500">
        <div className="p-6 border-b border-gray-100 bg-white/50 flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center shadow-lg shadow-blue-100">
            <UsersIcon size={16} />
          </div>
          <h2 className="font-black text-gray-900 text-sm tracking-tight uppercase">Authorized Personnel</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead className="bg-gray-50/80 text-[10px] font-black uppercase text-gray-500 tracking-widest border-b border-gray-100">
              <tr>
                <th className="px-8 py-5">Profile Entity</th>
                <th className="px-6 py-5">Clearance</th>
                <th className="px-8 py-5">Last Activity</th>
                <th className="px-8 py-5">Registration</th>
                <th className="px-8 py-5 text-right">Administrative</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 bg-white/30">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-blue-50/30 transition-all duration-300 group">
                  <td className="px-8 py-6">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-black transition-transform duration-300 group-hover:scale-110 ${u.is_superuser ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                        {u.username.substring(0, 2).toUpperCase()}
                      </div>
                      <span className="text-xs font-black text-gray-900 uppercase tracking-tight">{u.username}</span>
                    </div>
                  </td>
                  <td className="px-6 py-6 font-bold">
                    <div className="flex flex-col gap-1">
                      <span className={`px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest ${ROLE_BADGE[u.role] || ROLE_BADGE.teacher}`}>
                        {u.role === 'superadmin' ? 'Super Admin' : u.role === 'school_admin' ? 'School Admin' : 'Teacher'}
                      </span>
                      {u.school_name && <span className="text-[9px] text-gray-400 pl-1">{u.school_name}</span>}
                      {u.allowed_subject && (
                        <span className="px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-widest bg-blue-50 text-blue-600 border border-blue-200 w-fit">
                          {u.allowed_subject}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-8 py-6">
                    <div className="flex items-center gap-2 text-[10px] font-black text-gray-600 uppercase tracking-tight">
                      <Clock size={12} className="opacity-60" />
                      {u.last_login ? new Date(u.last_login).toLocaleDateString('en-US', {month:'short', day:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'}) : 'NEVER'}
                    </div>
                  </td>
                  <td className="px-8 py-6">
                    <div className="flex items-center gap-2 text-[10px] font-black text-gray-600 uppercase tracking-tight">
                      <Calendar size={12} className="opacity-60" />
                      {new Date(u.date_joined).toLocaleDateString('en-US', {month:'short', day:'2-digit', year:'numeric'})}
                    </div>
                  </td>
                  <td className="px-8 py-6 text-right">
                    {!u.is_superuser && (
                      <button 
                        onClick={() => handleDeleteUser(u.id, u.username)}
                        className="bg-red-50 text-red-600 hover:bg-red-600 hover:text-white px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all duration-300 shadow-sm hover:shadow-lg hover:shadow-red-200 active:scale-95"
                      >
                        Terminate
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
      <div className="space-y-10">
        <div className="flex items-center gap-4 mb-2">
          <div className="w-12 h-12 bg-blue-600 text-white rounded-2xl flex items-center justify-center shadow-lg shadow-blue-200 animate-pulse-slow">
            <Layers size={24} />
          </div>
          <div>
            <h2 className="text-2xl font-black text-gray-900 tracking-tight">Inventory Census</h2>
            <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest">Question Papers Grouped by Class and Subject</p>
          </div>
        </div>
        
        {Object.entries(groupedPapers).sort((a,b) => a[0] - b[0]).map(([className, subjects]) => (
          <div key={className} className="glass-card overflow-hidden border-2 border-slate-100 group/class mb-8 hover:border-blue-200 transition-all duration-500">
            <div className="bg-[#1e293b] text-white px-8 py-5 flex items-center justify-between transition-colors duration-500 group-hover/class:bg-slate-800">
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center transition-transform duration-500 group-hover/class:rotate-12">
                  <GraduationCap size={16} />
                </div>
                <span className="text-sm font-black uppercase tracking-[0.3em]">Institutional Class: {className}</span>
              </div>
              <div className="text-[10px] font-black text-slate-300 uppercase tracking-widest">
                {Object.keys(subjects).length} Subjects Active
              </div>
            </div>

            <div className="p-4 space-y-6">
              {Object.entries(subjects).map(([subject, paperList]) => (
                <div key={`${className}-${subject}`} className="bg-white/50 border border-gray-100 rounded-2xl overflow-hidden hover:shadow-lg hover:shadow-gray-100/50 transition-all duration-300 hover:border-blue-100">
                  <div className="px-6 py-3 bg-gray-50/80 border-b border-gray-100 flex items-center justify-between">
                    <span className="text-[10px] font-black text-gray-600 uppercase tracking-widest">
                      Subject Matter: <span className="text-blue-600 ml-2">{subject}</span>
                    </span>
                    <span className="text-[9px] font-black text-gray-500 uppercase tracking-widest">{paperList.length} Papers</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-[#fafbfc] text-[9px] font-black uppercase text-gray-500 tracking-widest border-b border-gray-100">
                        <tr>
                          <th className="px-6 py-4">Structural Pattern</th>
                          <th className="px-6 py-4">Complexity</th>
                          <th className="px-6 py-4">Generation Date</th>
                          <th className="px-6 py-4">Operational Status</th>
                          <th className="px-6 py-4 text-right">Nexus</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {paperList.map((paper) => (
                          <tr key={paper.id} className="hover:bg-blue-50/20 transition-all duration-300 group/row">
                            <td className="px-6 py-4 font-black text-gray-900 uppercase tracking-tight group-hover/row:text-blue-700 transition-colors uppercase">{paper.pattern_name || 'Standard'}</td>
                            <td className="px-6 py-4 font-bold text-gray-700">{paper.difficulty}</td>
                            <td className="px-6 py-4 text-gray-600 font-medium">
                              {new Date(paper.created_at).toLocaleString('en-US', {
                                year: 'numeric', month: '2-digit', day: '2-digit'
                              })}
                            </td>
                            <td className="px-6 py-4">
                              <span className={`px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-tighter transition-all duration-300 ${
                                paper.status === 'done' ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' : 
                                paper.status === 'failed' ? 'bg-red-100 text-red-700 border border-red-200' : 'bg-amber-100 text-amber-700 border border-amber-200'
                              }`}>
                                {paper.status}
                              </span>
                            </td>
                            <td className="px-6 py-4 text-right">
                              {paper.file ? (
                                <a 
                                  href={paper.file} 
                                  target="_blank" 
                                  className="text-[10px] font-black text-blue-600 uppercase hover:text-blue-800 transition-all duration-300 flex items-center justify-end gap-1 group/btn"
                                >
                                  Access <ArrowRight size={10} className="group-hover/btn:translate-x-1 transition-transform" />
                                </a>
                              ) : (
                                <span className="text-[9px] font-bold text-gray-500 uppercase italic">In Transit</span>
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

      {/* Upgrade Modal — shown when the teacher plan limit is hit */}
      {showUpgradeModal && (
        <UpgradeModal
          reason="teacher"
          onClose={() => setShowUpgradeModal(false)}
          onSuccess={() => {
            setShowUpgradeModal(false);
            setSuccess('Plan upgraded! You can now add more teachers.');
          }}
        />
      )}
    </div>
  );
}
