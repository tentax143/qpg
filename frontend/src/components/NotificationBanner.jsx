'use client';

import { useState, useEffect } from 'react';
import { X, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import apiClient from '@/lib/api';

export default function NotificationBanner() {
  const [notifications, setNotifications] = useState([]);
  const [dismissedIds, setDismissedIds] = useState(new Set());

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 10000);
    return () => clearInterval(interval);
  }, []);

  async function fetchNotifications() {
    try {
      const r = await apiClient.get('/notifications/');
      setNotifications(r.data.notifications || []);
    } catch (e) {
      console.error('Failed to fetch notifications:', e);
    }
  }

  function dismissNotification(id) {
    setDismissedIds(prev => new Set(prev).add(id));
  }

  const visibleNotifications = notifications.filter(n => !dismissedIds.has(n.id));

  if (visibleNotifications.length === 0) {
    return null;
  }

  return (
    <div className="w-full max-w-2xl space-y-2">
      {visibleNotifications.map(notification => (
        <NotificationItem
          key={notification.id}
          notification={notification}
          onDismiss={() => dismissNotification(notification.id)}
        />
      ))}
    </div>
  );
}

function NotificationItem({ notification, onDismiss }) {
  const severityConfig = {
    info: {
      bg: 'bg-blue-100',
      border: 'border-blue-400',
      text: 'text-blue-900',
      titleText: 'text-blue-900',
      icon: Info,
      iconColor: 'text-blue-700',
      shadow: 'shadow-md'
    },
    warning: {
      bg: 'bg-yellow-100',
      border: 'border-yellow-400',
      text: 'text-yellow-900',
      titleText: 'text-yellow-900',
      icon: AlertTriangle,
      iconColor: 'text-yellow-700',
      shadow: 'shadow-md'
    },
    error: {
      bg: 'bg-red-100',
      border: 'border-red-400',
      text: 'text-red-900',
      titleText: 'text-red-900',
      icon: AlertCircle,
      iconColor: 'text-red-700',
      shadow: 'shadow-md'
    },
  };

  const config = severityConfig[notification.severity] || severityConfig.info;
  const IconComponent = config.icon;

  return (
    <div className={`${config.bg} border-2 ${config.border} rounded-lg p-4 flex items-start gap-3 ${config.shadow}`}>
      <div className={`flex-shrink-0 mt-1 ${config.iconColor}`}>
        <IconComponent className="w-6 h-6" />
      </div>

      <div className="flex-1">
        <p className={`font-bold text-base ${config.titleText}`}>{notification.title}</p>
        <p className={`text-sm ${config.text} mt-2 leading-relaxed`}>
          {notification.message}
        </p>
      </div>

      <button
        onClick={onDismiss}
        className={`flex-shrink-0 ${config.text} hover:opacity-70 transition-opacity mt-1`}
        aria-label="Dismiss notification"
      >
        <X className="w-5 h-5" />
      </button>
    </div>
  );
}
