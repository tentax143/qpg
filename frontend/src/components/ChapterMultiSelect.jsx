'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { ChevronDown, Check, X, Plus, BookMarked, RefreshCw } from 'lucide-react';
import apiClient from '@/lib/api';

/**
 * Multi-select for the chapter(s) a non-textbook material relates to.
 * - Lists chapters already ingested for the given class + subject (from /get_chapters/).
 * - Lets the user pick one or more, AND type a custom chapter name not yet in the list.
 *
 * Props:
 *   classValue, subject  → used to fetch the existing chapter list
 *   value (string[])     → currently selected chapter names
 *   onChange(string[])   → called with the new selection
 *   label, disabled
 */
export default function ChapterMultiSelect({
  classValue,
  subject,
  value = [],
  onChange,
  label = 'Related Chapter(s)',
  disabled = false,
}) {
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setIsOpen(false); };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const fetchChapters = useCallback(async () => {
    if (!classValue || !subject) { setOptions([]); return; }
    setLoading(true);
    try {
      const res = await apiClient.get(
        `/get_chapters/?class_name=${encodeURIComponent(classValue)}&subject=${encodeURIComponent(subject)}`
      );
      setOptions((res.data.chapters || []).filter(Boolean));
    } catch {
      setOptions([]);
    } finally {
      setLoading(false);
    }
  }, [classValue, subject]);

  useEffect(() => { fetchChapters(); }, [fetchChapters]);

  const add = (chapter) => {
    const name = (chapter || '').trim();
    if (!name) return;
    if (!value.some((v) => v.toLowerCase() === name.toLowerCase())) onChange([...value, name]);
    setQuery('');
  };
  const remove = (chapter) => onChange(value.filter((v) => v !== chapter));

  const selectedLower = value.map((v) => v.toLowerCase());
  const q = query.trim().toLowerCase();
  const filtered = options.filter(
    (o) => !selectedLower.includes(o.toLowerCase()) && (!q || o.toLowerCase().includes(q))
  );
  const canAddCustom =
    query.trim() &&
    !options.some((o) => o.toLowerCase() === q) &&
    !selectedLower.includes(q);

  return (
    <div className={`relative ${isOpen ? 'z-[100]' : 'z-10'}`} ref={ref}>
      {label && (
        <label className="flex items-center gap-2 text-[10px] font-black text-gray-500 uppercase tracking-widest ml-1 mb-2">
          <BookMarked size={12} className="text-blue-500" /> {label}
        </label>
      )}

      {/* Selected chips */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {value.map((ch) => (
            <span key={ch} className="inline-flex items-center gap-1.5 pl-3 pr-2 py-1.5 bg-blue-50 text-blue-700 rounded-full text-xs font-bold border border-blue-100">
              {ch}
              {!disabled && (
                <button type="button" onClick={() => remove(ch)} className="text-blue-400 hover:text-red-500 transition-colors">
                  <X size={13} />
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {/* Combobox input */}
      <div
        className={`w-full flex items-center justify-between px-4 py-3 bg-white/70 border rounded-2xl transition-all ${
          isOpen ? 'ring-4 ring-blue-500/5 border-blue-500' : 'border-gray-200 hover:border-blue-400'
        } ${disabled ? 'opacity-50' : ''}`}
      >
        <input
          type="text"
          value={query}
          disabled={disabled}
          onFocus={() => setIsOpen(true)}
          onChange={(e) => { setQuery(e.target.value); setIsOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); if (canAddCustom) add(query); else if (filtered.length === 1) add(filtered[0]); }
          }}
          placeholder={value.length ? 'Add another chapter…' : 'Select or type chapter name…'}
          className="flex-1 bg-transparent outline-none text-sm font-bold text-gray-900 placeholder:text-gray-400 placeholder:font-medium"
        />
        {loading
          ? <RefreshCw size={16} className="text-gray-300 animate-spin" />
          : <ChevronDown size={16} className={`text-gray-400 transition-transform ${isOpen ? 'rotate-180 text-blue-500' : ''}`} onClick={() => !disabled && setIsOpen((o) => !o)} />}
      </div>

      {isOpen && !disabled && (
        <div className="absolute z-[1000] top-full left-0 mt-2 w-full bg-white border border-gray-100 rounded-[20px] shadow-2xl shadow-blue-500/10 py-2 max-h-72 overflow-y-auto custom-scrollbar" style={{ overscrollBehavior: 'contain' }}>
          {canAddCustom && (
            <button type="button" onClick={() => add(query)} className="w-full flex items-center gap-2 px-4 py-3 hover:bg-emerald-50/60 transition-colors text-left">
              <Plus size={15} className="text-emerald-600" />
              <span className="text-sm font-bold text-emerald-700">Add &ldquo;{query.trim()}&rdquo;</span>
            </button>
          )}
          {filtered.map((o) => (
            <button key={o} type="button" onClick={() => add(o)} className="w-full flex items-center justify-between px-4 py-3 hover:bg-blue-50/50 transition-colors group text-left">
              <span className="text-sm font-bold text-gray-700 group-hover:text-gray-900">{o}</span>
              <Check size={15} className="text-blue-500 opacity-0 group-hover:opacity-60" />
            </button>
          ))}
          {!canAddCustom && filtered.length === 0 && (
            <div className="px-4 py-3 text-xs font-bold text-gray-400 italic">
              {options.length === 0
                ? 'No chapters ingested yet — type a chapter name to add it.'
                : 'All matching chapters already selected.'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
