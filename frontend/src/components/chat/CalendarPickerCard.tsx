'use client';

import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Phone,
  VideoCamera,
  MapPin,
  CalendarBlank,
  Clock,
  CheckCircle,
  SpinnerGap,
  CaretLeft,
} from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface CalendarPickerCardProps {
  onBooked: (summary: string) => void;
  initialMode?: 'guided' | 'next_available';
  initialMeetingType?: MeetingType;
}

type MeetingType = 'phone' | 'video' | 'in_person';
type Step = 'type' | 'date' | 'time' | 'details' | 'confirm' | 'done';

interface Slot {
  start: string;
  end: string;
  available: boolean;
}

interface SuggestedSlot extends Slot {
  dateLabel: string;
}

const MEETING_TYPES: { key: MeetingType; label: string; icon: typeof Phone }[] = [
  { key: 'phone', label: 'Phone Call', icon: Phone },
  { key: 'video', label: 'Google Meet', icon: VideoCamera },
  { key: 'in_person', label: 'In Person', icon: MapPin },
];

function getNextDays(count: number): Date[] {
  const days: Date[] = [];
  const now = new Date();
  for (let i = 1; i <= count + 10; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() + i);
    // Skip weekends
    if (d.getDay() !== 0 && d.getDay() !== 6) {
      days.push(d);
    }
    if (days.length >= count) break;
  }
  return days;
}

function getNextBusinessDaysAfter(date: Date, count: number): Date[] {
  const days: Date[] = [];
  const cursor = new Date(date);
  for (let i = 1; i <= count + 10; i++) {
    cursor.setDate(cursor.getDate() + 1);
    if (cursor.getDay() !== 0 && cursor.getDay() !== 6) {
      days.push(new Date(cursor));
    }
    if (days.length >= count) break;
  }
  return days;
}

function formatDate(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

function formatDateParam(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export default function CalendarPickerCard({
  onBooked,
  initialMode = 'guided',
  initialMeetingType = 'phone',
}: CalendarPickerCardProps) {
  const [step, setStep] = useState<Step>(initialMode === 'next_available' ? 'time' : 'type');
  const [meetingType, setMeetingType] = useState<MeetingType>(initialMeetingType);
  const [selectedDate, setSelectedDate] = useState<Date | null>(
    initialMode === 'next_available' ? new Date() : null,
  );
  const [location, setLocation] = useState('');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [suggestedSlots, setSuggestedSlots] = useState<SuggestedSlot[]>([]);
  const [selectedSlot, setSelectedSlot] = useState<Slot | null>(null);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [bookingDone, setBookingDone] = useState(false);
  const didAutoLoadRef = useRef(false);

  const days = getNextDays(14);

  const fetchAvailabilityForDate = async (
    date: Date,
    type: MeetingType,
    loc: string,
  ): Promise<Slot[]> => {
    const dateStr = formatDateParam(date);
    const params = new URLSearchParams({
      date: dateStr,
      meeting_type: type,
      location: loc,
    });
    const res = await fetch(`${API_URL}/api/v1/booking/available-slots?${params}`);
    if (!res.ok) {
      const payload = await res.json().catch(() => null) as { detail?: string } | null;
      throw new Error(payload?.detail || 'Failed to fetch slots');
    }
    const data = await res.json() as { slots?: Slot[] };
    return data.slots || [];
  };

  const fetchNextAvailableSlots = async (
    date: Date,
    type: MeetingType,
    loc: string,
    includeStartDate = false,
  ): Promise<SuggestedSlot[]> => {
    const upcomingDays = includeStartDate
      ? [new Date(date), ...getNextBusinessDaysAfter(date, 10)]
      : getNextBusinessDaysAfter(date, 10);
    const nextSlots: SuggestedSlot[] = [];

    for (const day of upcomingDays) {
      const daySlots = await fetchAvailabilityForDate(day, type, loc);
      nextSlots.push(
        ...daySlots.slice(0, 3).map((slot) => ({
          ...slot,
          dateLabel: formatDate(day),
        })),
      );
      if (nextSlots.length >= 6) break;
    }

    return nextSlots.slice(0, 6);
  };

  const fetchInstantNextAvailableSlots = async (type: MeetingType, loc: string) => {
    const searchStart = new Date();
    setLoading(true);
    setSlots([]);
    setSuggestedSlots([]);
    setSelectedSlot(null);
    setSelectedDate(searchStart);
    setError('');
    setStep('time');

    try {
      const nextAvailableSlots = await fetchNextAvailableSlots(searchStart, type, loc, true);
      setSuggestedSlots(nextAvailableSlots);
      if (nextAvailableSlots.length === 0) {
        setError('No available times found in the next two business weeks. Try another meeting type or call Brandon directly.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load availability. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const fetchSlots = async (date: Date, type: MeetingType, loc: string) => {
    setLoading(true);
    setSlots([]);
    setSuggestedSlots([]);
    setError('');
    try {
      const daySlots = await fetchAvailabilityForDate(date, type, loc);
      setSlots(daySlots);
      if (daySlots.length === 0) {
        const nextAvailableSlots = await fetchNextAvailableSlots(date, type, loc);
        setSuggestedSlots(nextAvailableSlots);
        setError(
          nextAvailableSlots.length > 0
            ? 'Brandon is booked on that date. Here are the next available times.'
            : 'No available times found in the next two business weeks. Try another meeting type or call Brandon directly.',
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load availability. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialMode !== 'next_available' || didAutoLoadRef.current) return;

    didAutoLoadRef.current = true;
    setMeetingType(initialMeetingType);
    void fetchInstantNextAvailableSlots(initialMeetingType, '');
  }, [initialMeetingType, initialMode]);

  const handleSelectType = (type: MeetingType) => {
    setMeetingType(type);
    setSlots([]);
    setSuggestedSlots([]);
    setSelectedSlot(null);
    if (type === 'in_person') {
      setStep('date');
    } else {
      setLocation('');
      setStep('date');
    }
  };

  const handleSelectDate = (date: Date) => {
    setSelectedDate(date);
    setSelectedSlot(null);
    setSuggestedSlots([]);
    if (meetingType === 'in_person' && !location) {
      // Need location first for in-person
      setStep('details');
    } else {
      fetchSlots(date, meetingType, location);
      setStep('time');
    }
  };

  const handleLocationSubmit = () => {
    if (!location.trim()) return;
    if (selectedDate) {
      setSuggestedSlots([]);
      fetchSlots(selectedDate, meetingType, location);
      setStep('time');
    }
  };

  const handleSelectSlot = (slot: Slot) => {
    setSelectedDate(new Date(slot.start));
    setSelectedSlot(slot);
    setStep('confirm');
  };

  const handleBook = async () => {
    if (!name.trim() || !email.trim() || !selectedSlot) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/v1/booking/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          email,
          phone,
          meeting_type: meetingType,
          context: 'general',
          location: location || '',
          scheduled_at: selectedSlot.start,
          notes: '',
        }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null) as { detail?: string } | null;
        throw new Error(payload?.detail || 'Booking failed');
      }
      setBookingDone(true);
      setStep('done');

      const dateStr = new Date(selectedSlot.start).toLocaleDateString('en-US', {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
      });
      const timeStr = formatTime(selectedSlot.start);
      const typeLabel = MEETING_TYPES.find(t => t.key === meetingType)?.label || meetingType;
      onBooked(
        `You're all set! Brandon will meet you on ${dateStr} at ${timeStr} (${typeLabel})${location ? ` at ${location}` : ''}. He'll send a confirmation shortly.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not complete booking. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const goBack = () => {
    switch (step) {
      case 'date': setStep('type'); break;
      case 'details': setStep('date'); break;
      case 'time': setStep(meetingType === 'in_person' ? 'details' : 'date'); break;
      case 'confirm': setStep('time'); break;
      default: break;
    }
  };

  if (bookingDone) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-dark-card border border-gold/30 rounded-xl p-4 text-center"
      >
        <CheckCircle weight="fill" className="w-10 h-10 text-gold mx-auto mb-2" />
        <p className="text-white text-sm font-semibold">Booking Confirmed!</p>
        <p className="text-white/50 text-xs mt-1">Check your email for details.</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-dark-card border border-dark-border rounded-xl overflow-hidden w-full"
    >
      {/* Header */}
      <div className="bg-[#0a0a0a] border-b border-dark-border px-3 py-2 flex items-center gap-2">
        {step !== 'type' && step !== 'done' && (
          <button onClick={goBack} className="text-white/50 hover:text-white transition-colors">
            <CaretLeft className="w-4 h-4" />
          </button>
        )}
        <CalendarBlank weight="fill" className="w-4 h-4 text-gold" />
        <span className="text-white text-xs font-semibold">
          {step === 'type' && 'How would you like to meet?'}
          {step === 'date' && 'Pick a date'}
          {step === 'details' && 'Meeting location'}
          {step === 'time' && 'Available times'}
          {step === 'confirm' && 'Your details'}
        </span>
      </div>

      <div className="p-3">
        <AnimatePresence mode="wait">
          {/* Step 1: Meeting Type */}
          {step === 'type' && (
            <motion.div key="type" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col gap-2">
              {MEETING_TYPES.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => handleSelectType(key)}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-dark-border hover:border-gold/50 transition-colors text-left group"
                >
                  <Icon weight="fill" className="w-5 h-5 text-gold/70 group-hover:text-gold transition-colors" />
                  <span className="text-white/80 text-sm group-hover:text-white transition-colors">{label}</span>
                </button>
              ))}
            </motion.div>
          )}

          {/* Step 2: Date */}
          {step === 'date' && (
            <motion.div key="date" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
                {days.map((d, i) => (
                  <button
                    key={i}
                    onClick={() => handleSelectDate(d)}
                    className={`flex flex-col items-center px-3 py-2 rounded-lg border text-xs shrink-0 transition-colors
                      ${selectedDate?.toDateString() === d.toDateString()
                        ? 'border-gold bg-gold/10 text-gold'
                        : 'border-dark-border text-white/60 hover:border-gold/30 hover:text-white/80'
                      }`}
                  >
                    <span className="font-semibold">{d.toLocaleDateString('en-US', { weekday: 'short' })}</span>
                    <span className="text-[10px] mt-0.5">{d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {/* Step 3: Location (in-person only) */}
          {step === 'details' && (
            <motion.div key="details" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col gap-2">
              <p className="text-white/50 text-xs">Where would you like to meet Brandon?</p>
              <input
                type="text"
                value={location}
                onChange={e => setLocation(e.target.value)}
                placeholder="e.g. 123 Main St, Manchester NH"
                className="bg-[#111] border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-1 focus:ring-gold/60"
                onKeyDown={e => e.key === 'Enter' && handleLocationSubmit()}
              />
              <button
                onClick={handleLocationSubmit}
                disabled={!location.trim()}
                className="bg-gold text-[#0a0a0a] text-xs font-semibold rounded-lg px-3 py-2 disabled:opacity-40 hover:bg-gold/90 transition-colors"
              >
                Check Availability
              </button>
            </motion.div>
          )}

          {/* Step 4: Time Slots */}
          {step === 'time' && (
            <motion.div key="time" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {loading ? (
                <div className="flex items-center justify-center py-6 gap-2">
                  <SpinnerGap className="w-5 h-5 text-gold animate-spin" />
                  <span className="text-white/50 text-xs">
                    {meetingType === 'in_person' ? 'Checking travel times...' : 'Loading availability...'}
                  </span>
                </div>
              ) : slots.length > 0 ? (
                <div className="grid grid-cols-3 gap-1.5 max-h-[180px] overflow-y-auto">
                  {slots.map((slot, i) => (
                    <button
                      key={i}
                      onClick={() => handleSelectSlot(slot)}
                      className="flex items-center justify-center gap-1 px-2 py-2 rounded-lg border border-dark-border text-xs text-white/70 hover:border-gold/50 hover:text-white transition-colors"
                    >
                      <Clock className="w-3 h-3 text-gold/60" />
                      {formatTime(slot.start)}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  {suggestedSlots.length > 0 && (
                    <p className="text-white/50 text-[11px] text-center leading-relaxed">
                      Next available {MEETING_TYPES.find(t => t.key === meetingType)?.label.toLowerCase()} times
                    </p>
                  )}
                  {error && (
                    <p className="text-gold text-xs text-center leading-relaxed">{error}</p>
                  )}
                  {suggestedSlots.length > 0 && (
                    <div className="grid grid-cols-1 gap-1.5 max-h-[220px] overflow-y-auto">
                      {suggestedSlots.map((slot, i) => (
                        <button
                          key={`${slot.start}-${i}`}
                          onClick={() => handleSelectSlot(slot)}
                          className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-dark-border text-xs text-white/70 hover:border-gold/50 hover:text-white transition-colors"
                        >
                          <span className="font-semibold text-white/80">{slot.dateLabel}</span>
                          <span className="flex items-center gap-1 text-gold">
                            <Clock className="w-3 h-3" />
                            {formatTime(slot.start)}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {meetingType === 'in_person' && location && !loading && (slots.length > 0 || suggestedSlots.length > 0) && (
                <p className="text-white/30 text-[10px] mt-2 text-center">
                  Slots filtered by travel time to {location}
                </p>
              )}
            </motion.div>
          )}

          {/* Step 5: Contact Details */}
          {step === 'confirm' && (
            <motion.div key="confirm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col gap-2">
              {selectedSlot && selectedDate && (
                <div className="bg-gold/5 border border-gold/20 rounded-lg px-3 py-2 mb-1">
                  <p className="text-gold text-xs font-semibold">
                    {formatDate(selectedDate)} at {formatTime(selectedSlot.start)}
                  </p>
                  <p className="text-white/40 text-[10px]">
                    {MEETING_TYPES.find(t => t.key === meetingType)?.label}
                    {location ? ` • ${location}` : ''}
                  </p>
                </div>
              )}
              <input
                type="text" value={name} onChange={e => setName(e.target.value)}
                placeholder="Your name"
                className="bg-[#111] border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-1 focus:ring-gold/60"
              />
              <input
                type="email" value={email} onChange={e => setEmail(e.target.value)}
                placeholder="Email address"
                className="bg-[#111] border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-1 focus:ring-gold/60"
              />
              <input
                type="tel" value={phone} onChange={e => setPhone(e.target.value)}
                placeholder="Phone (optional)"
                className="bg-[#111] border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-1 focus:ring-gold/60"
              />
              {error && <p className="text-red-400 text-xs">{error}</p>}
              <button
                onClick={handleBook}
                disabled={!name.trim() || !email.trim() || loading}
                className="bg-gold text-[#0a0a0a] text-xs font-semibold rounded-lg px-3 py-2.5 disabled:opacity-40 hover:bg-gold/90 transition-colors flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <SpinnerGap className="w-4 h-4 animate-spin" />
                    Booking...
                  </>
                ) : (
                  'Confirm Booking'
                )}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
