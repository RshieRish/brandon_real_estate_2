'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapPin, SpinnerGap } from '@phosphor-icons/react';
import { apiGet } from '@/lib/api';

interface Suggestion {
  formatted_address: string;
  display_name: string;
  lat: number;
  lng: number;
  type: string;
  address_components: {
    house_number: string;
    road: string;
    city: string;
    state: string;
    postcode: string;
    county: string;
  };
}

interface AddressAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  onSelect?: (suggestion: Suggestion) => void;
  placeholder?: string;
  className?: string;
  required?: boolean;
  id?: string;
}

export default function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  placeholder = '123 Main St, Nashua, NH 03060',
  className = '',
  required,
  id,
}: AddressAutocompleteProps) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const suppressFetchRef = useRef(false);

  // Fetch suggestions from the backend
  const fetchSuggestions = useCallback(async (query: string) => {
    if (query.length < 3) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    setIsLoading(true);
    try {
      const encoded = encodeURIComponent(query);
      const data = await apiGet<Suggestion[]>(`/api/v1/geocode/autocomplete?q=${encoded}&limit=5`);
      setSuggestions(data);
      setIsOpen(data.length > 0);
      setActiveIndex(-1);
    } catch {
      setSuggestions([]);
      setIsOpen(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Debounced input handler
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      onChange(newValue);
      suppressFetchRef.current = false;

      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      debounceRef.current = setTimeout(() => {
        if (!suppressFetchRef.current) {
          fetchSuggestions(newValue);
        }
      }, 300);
    },
    [onChange, fetchSuggestions],
  );

  // Handle suggestion selection
  const handleSelect = useCallback(
    (suggestion: Suggestion) => {
      suppressFetchRef.current = true;
      onChange(suggestion.formatted_address);
      setSuggestions([]);
      setIsOpen(false);
      setActiveIndex(-1);
      onSelect?.(suggestion);
      inputRef.current?.blur();
    },
    [onChange, onSelect],
  );

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!isOpen || suggestions.length === 0) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setActiveIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setActiveIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
          break;
        case 'Enter':
          e.preventDefault();
          if (activeIndex >= 0 && activeIndex < suggestions.length) {
            handleSelect(suggestions[activeIndex]);
          }
          break;
        case 'Escape':
          setIsOpen(false);
          setActiveIndex(-1);
          break;
      }
    },
    [isOpen, suggestions, activeIndex, handleSelect],
  );

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type="text"
          value={value}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
          }}
          placeholder={placeholder}
          required={required}
          autoComplete="off"
          role="combobox"
          aria-expanded={isOpen}
          aria-autocomplete="list"
          aria-activedescendant={activeIndex >= 0 ? `suggestion-${activeIndex}` : undefined}
          className={className}
        />
        {isLoading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <SpinnerGap weight="bold" className="w-4 h-4 text-gold animate-spin" />
          </div>
        )}
      </div>

      <AnimatePresence>
        {isOpen && suggestions.length > 0 && (
          <motion.ul
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            role="listbox"
            className="absolute z-50 left-0 right-0 mt-1 bg-[#141414] border border-dark-border shadow-2xl shadow-black/50 overflow-hidden max-h-[240px] overflow-y-auto"
          >
            {suggestions.map((suggestion, index) => (
              <li
                key={`${suggestion.formatted_address}-${index}`}
                id={`suggestion-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                onMouseDown={(e) => {
                  e.preventDefault();
                  handleSelect(suggestion);
                }}
                onMouseEnter={() => setActiveIndex(index)}
                className={`
                  flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors
                  ${index === activeIndex
                    ? 'bg-gold/10 border-l-2 border-l-gold'
                    : 'border-l-2 border-l-transparent hover:bg-white/5'
                  }
                `}
              >
                <MapPin
                  weight="fill"
                  className={`w-4 h-4 flex-shrink-0 mt-0.5 ${
                    index === activeIndex ? 'text-gold' : 'text-white/30'
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p className={`text-sm truncate ${
                    index === activeIndex ? 'text-white font-medium' : 'text-white/70'
                  }`}>
                    {suggestion.formatted_address}
                  </p>
                  {suggestion.address_components.county && (
                    <p className="text-[10px] text-white/30 truncate mt-0.5 uppercase tracking-wider">
                      {suggestion.address_components.county}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
