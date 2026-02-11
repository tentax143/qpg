'use client';

import { AlertCircle, X } from 'lucide-react';

export default function ErrorAlert({ message, onClose, className = '' }) {
  return (
    <div className={`bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3 ${className}`}>
      <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
      <div className="flex-1">
        <p className="text-red-800 font-medium">Error</p>
        <p className="text-red-700 text-sm">{message}</p>
      </div>
      {onClose && (
        <button onClick={onClose} className="text-red-600 hover:text-red-800">
          <X className="w-5 h-5" />
        </button>
      )}
    </div>
  );
}
