'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

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
    <div className={`relative ${className} ${isOpen ? 'z-[100]' : 'z-10'}`} ref={dropdownRef}>
      {label && (
        <label className="flex items-center gap-2 text-[12px] font-bold text-slate-500 uppercase tracking-wider mb-2">
          {Icon && <Icon size={14} className="text-indigo-500" strokeWidth={1.75} />}
          {label}
        </label>
      )}
      
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center justify-between px-4 py-3.5 bg-white border rounded-2xl transition-all duration-200 ${
          isOpen 
            ? 'ring-2 ring-indigo-500/10 border-indigo-400 shadow-md shadow-indigo-100/30' 
            : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'
        } ${disabled ? 'opacity-50 cursor-not-allowed bg-slate-50' : 'cursor-pointer'}`}
      >
        <span className={`text-[14px] font-semibold truncate ${selectedOption ? 'text-slate-900' : 'text-slate-400'}`}>
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDown 
          size={16} 
          strokeWidth={2}
          className={`text-slate-400 shrink-0 ml-2 transition-transform duration-200 ${isOpen ? 'rotate-180 text-indigo-500' : ''}`} 
        />
      </button>

      {/* Dropdown Panel */}
      <div 
        className={`absolute top-full left-0 mt-1.5 w-full bg-white border border-slate-100 rounded-2xl shadow-xl shadow-slate-200/40 py-1.5 max-h-72 overflow-y-auto transition-all duration-200 origin-top ${
          isOpen && !disabled
            ? 'opacity-100 scale-100 pointer-events-auto'
            : 'opacity-0 scale-95 pointer-events-none'
        }`}
        style={{ overscrollBehavior: 'contain', zIndex: 1000 }}
      >
        {options.length === 0 ? (
          <div className="px-4 py-4 text-[13px] font-medium text-slate-400 text-center">No options available</div>
        ) : (
          options.map((option) => {
            const isSelected = String(option.value) === String(value);
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-4 py-3 mx-0 rounded-xl transition-all duration-150 group ${
                  isSelected 
                    ? 'bg-indigo-50/70 text-indigo-700' 
                    : 'text-slate-700 hover:bg-slate-50'
                }`}
              >
                <span className={`text-[14px] truncate pr-2 ${
                  isSelected ? 'font-semibold text-indigo-700' : 'font-medium text-slate-700 group-hover:text-slate-900'
                }`}>
                  {option.label}
                </span>
                {isSelected && (
                  <Check size={15} strokeWidth={2.5} className="text-indigo-600 shrink-0" />
                )}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
