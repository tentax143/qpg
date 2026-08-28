'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

// options: [{ value, label, meta?, badge? }]
//   label — the primary text; truncated to a single line, full text on hover via title
//   meta  — optional muted right-hand column (e.g. "Class 10 · Biology · 80M")
//   badge — optional short tag rendered before the label (e.g. "SQP")
// meta and badge are additive: callers that pass only value/label render exactly as before.
export default function CustomSelect({ 
  options = [], 
  value, 
  onChange, 
  placeholder = 'Select option', 
  label,
  icon: Icon,
  disabled = false,
  className = ""
}) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectedOption = options.find(opt => String(opt.value) === String(value));

  return (
    <div className={`relative space-y-2 ${className} ${isOpen ? 'z-[100]' : 'z-10'}`} ref={dropdownRef}>
      {label && (
        <label className="flex items-center gap-2 text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1">
          {Icon && <Icon size={12} className="text-blue-500" />}
          {label}
        </label>
      )}
      
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center justify-between px-5 py-4 bg-white/70 backdrop-blur-md border border-gray-200 rounded-2xl transition-all duration-300 ${
          isOpen ? 'ring-4 ring-blue-500/5 border-blue-500 shadow-lg' : 'hover:border-blue-400 hover:bg-white'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span
          title={selectedOption ? selectedOption.label : ''}
          className={`flex-1 min-w-0 text-left truncate font-bold text-sm ${
            selectedOption ? 'text-gray-900' : 'text-gray-400'
          }`}
        >
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDown 
          size={18} 
          className={`shrink-0 ml-3 text-gray-400 transition-transform duration-300 ${isOpen ? 'rotate-180 text-blue-500' : ''}`} 
        />
      </button>

      {isOpen && !disabled && (
        <div 
          className="absolute z-[1000] top-full left-0 mt-2 w-full min-w-full bg-white border border-gray-100 rounded-[24px] shadow-2xl shadow-blue-500/10 py-3 animate-in fade-in duration-200 max-h-80 overflow-y-auto overflow-x-hidden custom-scrollbar"
          style={{ overscrollBehavior: 'contain' }}
        >
          {options.length === 0 ? (
            <div className="px-5 py-3 text-xs font-bold text-gray-400 italic">No options available</div>
          ) : (
            options.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setIsOpen(false);
                }}
                title={[option.label, option.meta].filter(Boolean).join(' — ')}
                className={`w-full flex items-center gap-3 px-5 py-3 text-left hover:bg-blue-50/50 transition-colors group ${
                  String(option.value) === String(value) ? 'bg-blue-50' : ''
                }`}
              >
                {/* Badge first so a whole class of option (e.g. official sample papers) is
                    scannable down the left edge without reading every label. */}
                {option.badge && (
                  <span className="shrink-0 px-2 py-0.5 rounded-md bg-cyan-100 text-cyan-700 text-[9px] font-black uppercase tracking-widest">
                    {option.badge}
                  </span>
                )}
                {/* min-w-0 is what lets `truncate` actually shrink inside a flex row — without it
                    the name pushes the meta column out and the option wraps onto two lines. */}
                <span className={`flex-1 min-w-0 truncate text-sm font-bold transition-colors ${
                  String(option.value) === String(value) ? 'text-blue-600' : 'text-gray-700 group-hover:text-gray-900'
                }`}>
                  {option.label}
                </span>
                {option.meta && (
                  <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-gray-400">
                    {option.meta}
                  </span>
                )}
                {String(option.value) === String(value) && (
                  <Check size={16} className="shrink-0 text-blue-600" />
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
