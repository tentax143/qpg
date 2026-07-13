'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Plus, Trash2, Edit2, ToggleLeft, ToggleRight, X } from 'lucide-react';

export default function NotificationsPage() {
  const router = useRouter();
  const [notifications, setNotifications] = useState([]);
  const [schools, setSchools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    title: '',
    message: '',
    severity: 'info',
    school_ids: [],
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('user') || 'null');
    if (!user || user.role !== 'superadmin') {
      router.replace('/dashboard');
      return;
    }
    fetchNotifications();
    fetchSchools();
  }, [router]);

  async function fetchNotifications() {
    try {
      const r = await apiClient.get('/admin/notifications/');
      setNotifications(r.data.notifications || []);
      setError(null);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to load notifications');
    } finally {
      setLoading(false);
    }
  }

  async function fetchSchools() {
    try {
      const r = await apiClient.get('/admin/schools/');
      // Handle both array and object response formats
      const schoolsList = Array.isArray(r.data) ? r.data : (r.data.schools || []);
      setSchools(schoolsList);
    } catch (e) {
      console.error('Failed to load schools:', e);
    }
  }

  function openCreateModal() {
    setEditingId(null);
    setFormData({
      title: '',
      message: '',
      severity: 'info',
      school_ids: [],
    });
    setShowModal(true);
  }

  function openEditModal(notification) {
    setEditingId(notification.id);
    setFormData({
      title: notification.title,
      message: notification.message,
      severity: notification.severity,
      school_ids: notification.school_ids || [],
    });
    setShowModal(true);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingId) {
        await apiClient.patch(`/admin/notifications/${editingId}/`, formData);
      } else {
        await apiClient.post('/admin/notifications/', formData);
      }
      setShowModal(false);
      fetchNotifications();
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to save notification');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id) {
    if (confirm('Are you sure you want to delete this notification?')) {
      try {
        await apiClient.delete(`/admin/notifications/${id}/`);
        fetchNotifications();
      } catch (e) {
        alert(e.response?.data?.error || 'Failed to delete notification');
      }
    }
  }

  async function handleToggle(notification) {
    try {
      await apiClient.patch(`/admin/notifications/${notification.id}/`, {
        is_active: !notification.is_active,
      });
      fetchNotifications();
    } catch (e) {
      alert(e.response?.data?.error || 'Failed to toggle notification');
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <div className="w-5 h-5 border-2 border-slate-300 border-t-blue-600 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">System Notifications</h1>
          <p className="text-sm text-slate-500 mt-0.5">Manage system-wide notifications displayed to all users</p>
        </div>
        <button
          onClick={openCreateModal}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          Create Notification
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Notifications list */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {notifications.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-400">
            No notifications yet.{' '}
            <button onClick={openCreateModal} className="text-blue-600 hover:underline font-medium">
              Create one
            </button>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {notifications.map(notification => (
              <div key={notification.id} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <h3 className="text-sm font-medium text-slate-900">{notification.title}</h3>
                      <span
                        className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          notification.severity === 'error'
                            ? 'bg-red-50 text-red-700'
                            : notification.severity === 'warning'
                            ? 'bg-yellow-50 text-yellow-700'
                            : 'bg-blue-50 text-blue-700'
                        }`}
                      >
                        {notification.severity}
                      </span>
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${notification.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                        {notification.is_active ? 'Active' : 'Inactive'}
                      </span>
                      {notification.is_global ? (
                        <span className="inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-50 text-purple-700">
                          Global
                        </span>
                      ) : (
                        <span className="inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 text-indigo-700">
                          {notification.school_names?.length || 0} school{(notification.school_names?.length || 0) !== 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-600 mb-2">{notification.message}</p>
                    {!notification.is_global && notification.school_names?.length > 0 && (
                      <div className="text-xs text-slate-500 mb-1">
                        <span className="font-medium">Schools:</span> {notification.school_names.join(', ')}
                      </div>
                    )}
                    <div className="text-xs text-slate-400">
                      Created by {notification.created_by}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => handleToggle(notification)}
                      className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors text-slate-600 hover:text-slate-900"
                      title={notification.is_active ? 'Deactivate' : 'Activate'}
                    >
                      {notification.is_active ? (
                        <ToggleRight className="w-4 h-4" />
                      ) : (
                        <ToggleLeft className="w-4 h-4" />
                      )}
                    </button>
                    <button
                      onClick={() => openEditModal(notification)}
                      className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors text-slate-600 hover:text-slate-900"
                      title="Edit"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(notification.id)}
                      className="p-1.5 hover:bg-red-50 rounded-lg transition-colors text-slate-600 hover:text-red-600"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <h3 className="font-semibold text-slate-900">
                {editingId ? 'Edit Notification' : 'Create Notification'}
              </h3>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal body */}
            <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Title
                </label>
                <input
                  type="text"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  placeholder="e.g., Image Model Issues"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Message
                </label>
                <textarea
                  value={formData.message}
                  onChange={(e) => setFormData({ ...formData, message: e.target.value })}
                  placeholder="e.g., We are experiencing issues with the image model. Services may be degraded."
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows="3"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Severity
                </label>
                <select
                  value={formData.severity}
                  onChange={(e) => setFormData({ ...formData, severity: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="error">Error</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  Target Schools
                </label>
                <p className="text-xs text-slate-500 mb-2">Leave empty for global notification (all users). Select schools to target specific ones.</p>
                <div className="border border-slate-300 rounded-lg p-3 max-h-48 overflow-y-auto">
                  {schools.length === 0 ? (
                    <p className="text-sm text-slate-500">No schools available</p>
                  ) : (
                    <div className="space-y-2">
                      {schools.map(school => (
                        <label key={school.id} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={formData.school_ids.includes(school.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setFormData({
                                  ...formData,
                                  school_ids: [...formData.school_ids, school.id]
                                });
                              } else {
                                setFormData({
                                  ...formData,
                                  school_ids: formData.school_ids.filter(id => id !== school.id)
                                });
                              }
                            }}
                            className="rounded"
                          />
                          <span className="text-sm text-slate-700">{school.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </form>

            {/* Modal footer */}
            <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-end gap-2">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-60"
              >
                {submitting ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
