'use client';

import { useState, useEffect } from 'react';
import { X, Info, AlertTriangle, CheckCircle2 } from 'lucide-react';
import apiClient from '@/lib/api';

// Per-user messages sent by a superadmin, shown as stacked toasts in the top-right
// corner. Dismissing a toast marks the message read on the server so it won't return.
const LEVEL_STYLES = {
  info: { bar: 'bg-blue-500', icon: Info, iconColor: 'text-blue-600' },
  warning: { bar: 'bg-amber-500', icon: AlertTriangle, iconColor: 'text-amber-600' },
  success: { bar: 'bg-emerald-500', icon: CheckCircle2, iconColor: 'text-emerald-600' },
};

export default function DirectMessageToasts() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    fetchMessages();
    const interval = setInterval(fetchMessages, 15000);
    return () => clearInterval(interval);
  }, []);

  async function fetchMessages() {
    // Don't poll on the login/public screens.
    if (typeof window !== 'undefined' && !localStorage.getItem('authToken')) return;
    try {
      const r = await apiClient.get('/messages/');
      setMessages(r.data.messages || []);
    } catch {
      // 401s are handled by the axios interceptor (redirects to login); ignore here.
    }
  }

  async function dismiss(id) {
    // Optimistically remove, then acknowledge on the server.
    setMessages((prev) => prev.filter((m) => m.id !== id));
    try {
      await apiClient.post(`/messages/${id}/read/`);
    } catch {
      /* best-effort; it'll simply reappear on the next poll if this failed */
    }
  }

  if (messages.length === 0) return null;

  return (
    <div className="fixed top-16 right-4 lg:top-4 z-[60] w-full max-w-sm space-y-2 pointer-events-none">
      {messages.map((m) => {
        const style = LEVEL_STYLES[m.level] || LEVEL_STYLES.info;
        const Icon = style.icon;
        return (
          <div
            key={m.id}
            className="pointer-events-auto flex overflow-hidden rounded-xl bg-white border border-slate-200 shadow-lg animate-in slide-in-from-right-4 fade-in duration-300"
          >
            <div className={`w-1 flex-shrink-0 ${style.bar}`} />
            <div className="flex items-start gap-3 p-4 flex-1 min-w-0">
              <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${style.iconColor}`} />
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">
                  Message from {m.sender}
                </p>
                <p className="text-sm text-slate-800 mt-1 whitespace-pre-wrap break-words leading-relaxed">
                  {m.body}
                </p>
              </div>
              <button
                onClick={() => dismiss(m.id)}
                className="flex-shrink-0 text-slate-400 hover:text-slate-600 transition-colors"
                aria-label="Dismiss message"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
