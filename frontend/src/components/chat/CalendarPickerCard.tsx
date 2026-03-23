'use client';

import { useState, useEffect } from 'react';
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
}

type MeetingType = 'phone' | 'video' | 'in_person';
type Step = 'type' | 'date' | 'time' | 'details' | 'confirm' | 'done';

interface Slot {
  start: string;
  end: string;
  available: boolean;
}

const MEETING_TYPES: { key: MeetingType; label: string; icon: typeof Phone }[] = [
  { key: 'phone', label: 'Phone Call', icon: Phone },
  { key: 'video', label: 'Video Call', icon: VideoCamera },
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

function formatDate(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export default function CalendarPickerCard({ onBooked }: CalendarPickerCardProps) {
  const [step, setStep] = useState<Step>('type');
  const [meetingType, setMeetingType] = useState<MeetingType>('phone');
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [location, setLocation] = useState('');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [selectedSlot, setSelectedSlot] = useState<Slot | null>(null);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [bookingDone, setBookingDone] = useState(false);

  const days = getNextDays(14);

  const fetchSlots = async (date: Date, type: MeetingType, loc: string) => {
    setLoading(true);
    setSlots([]);
    setError('');
    try {
      const dateStr = date.toISOString().split('T')[0];
      const params = new URLSearchParams({
        date: dateStr,
        meeting_type: type,
        location: loc,
      });
      const res = await fetch(`${API_URL}/api/v1/booking/available-slots?${params}`);
      if (!res.ok) throw new Error('Failed to fetch slots');
      const data = await res.json();
      setSlots(data.slots || []);
      if ((data.slots || []).length === 0) {
        setError('No available slots for this date. Try another day.');
      }
    } catch {
      setError('Could not load availability. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectType = (type: MeetingType) => {
    setMeetingType(type);
    if (type === 'in_person') {
      setStep('date');
    } else {
      setLocation('');
      setStep('date');
    }
  };

  const handleSelectDate = (date: Date) => {
    setSelectedDate(date);
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
      fetchSlots(selectedDate, meetingType, location);
      setStep('time');
    }
  };

  const handleSelectSlot = (slot: Slot) => {
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
      if (!res.ok) throw new Error('Booking failed');
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
    } catch {
      setError('Could not complete booking. Please try again.');
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
              ) : error ? (
                <p className="text-red-400 text-xs text-center py-4">{error}</p>
              ) : (
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
              )}
              {meetingType === 'in_person' && location && !loading && slots.length > 0 && (
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
