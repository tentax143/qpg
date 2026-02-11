'use client';

import { CheckCircle, X } from 'lucide-react';

export default function SuccessAlert({ message, onClose, className = '' }) {
  return (
    <div className={`bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3 ${className}`}>
      <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
      <div className="flex-1">
        <p className="text-green-800 font-medium">Success</p>
        <p className="text-green-700 text-sm">{message}</p>
      </div>
      {onClose && (
        <button onClick={onClose} className="text-green-600 hover:text-green-800">
          <X className="w-5 h-5" />
        </button>
      )}
    </div>
  );
}
