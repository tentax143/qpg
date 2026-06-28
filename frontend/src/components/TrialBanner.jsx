'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Zap, X } from 'lucide-react';
import apiClient from '@/lib/api';

export default function TrialBanner() {
  const router = useRouter();
  const [info, setInfo] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const userData = localStorage.getItem('user');
    if (!userData) return;
    const user = JSON.parse(userData);
    if (user?.role !== 'school_admin') return;

    apiClient.get('/admin/my-school/')
      .then(res => {
        const d = res.data;
        if (d.is_on_trial && d.trial_ends_at) {
          const msLeft = new Date(d.trial_ends_at) - Date.now();
          const daysLeft = Math.ceil(msLeft / 86400000);
          setInfo({ daysLeft, planName: d.plan_name });
        } else if (d.plan_key === 'free') {
          setInfo({ daysLeft: null, planName: d.plan_name });
        }
      })
      .catch(() => {});
  }, []);

  if (!info || dismissed) return null;

  const isTrialExpiringSoon = info.daysLeft !== null && info.daysLeft <= 7;
  const isExpired = info.daysLeft !== null && info.daysLeft <= 0;

  const bgClass = isExpired
    ? 'bg-red-600'
    : isTrialExpiringSoon
    ? 'bg-amber-500'
    : 'bg-blue-600';

  const message = isExpired
    ? 'Your Pro trial has expired. Upgrade to keep generating papers.'
    : info.daysLeft !== null
    ? `Your Pro trial ends in ${info.daysLeft} day${info.daysLeft === 1 ? '' : 's'}. Upgrade to continue after trial.`
    : 'You are on the Free plan. Upgrade for more papers and teachers.';

  return (
    <div className={`${bgClass} text-white text-sm flex items-center justify-between px-4 py-2`}>
      <div className="flex items-center gap-2">
        <Zap className="w-4 h-4 flex-shrink-0" />
        <span>{message}</span>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.push('/billing')}
          className="bg-white text-blue-700 font-semibold text-xs px-3 py-1 rounded-full hover:bg-blue-50 transition-colors"
        >
          Upgrade
        </button>
        <button onClick={() => setDismissed(true)} className="opacity-70 hover:opacity-100">
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
