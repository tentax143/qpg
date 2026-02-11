'use client';

import { ChevronDown } from 'lucide-react';
import { useState } from 'react';

export default function Accordion({ items = [] }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.id} className="border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
            className="w-full px-4 py-3 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors text-left"
          >
            <div>
              <h3 className="font-semibold text-gray-900">{item.title}</h3>
              {item.subtitle && (
                <p className="text-sm text-gray-600 mt-0.5">{item.subtitle}</p>
              )}
            </div>
            <ChevronDown
              className={`w-5 h-5 text-gray-400 transition-transform ${
                expandedId === item.id ? 'rotate-180' : ''
              }`}
            />
          </button>

          {expandedId === item.id && (
            <div className="px-4 py-3 border-t border-gray-200 bg-white">
              {item.content}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
