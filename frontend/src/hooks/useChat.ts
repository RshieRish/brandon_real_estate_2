'use client';
import { useState, useCallback, useRef } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  widget?: 'calendar_picker';
}

// Patterns that indicate the AI wants to trigger booking
const BOOKING_TRIGGERS = [
  '[BOOK_MEETING]',
  '[BOOKING]',
  '[CALENDAR]',
];

function detectBookingTrigger(text: string): boolean {
  return BOOKING_TRIGGERS.some(trigger => text.includes(trigger));
}

function cleanBookingTrigger(text: string): string {
  let cleaned = text;
  for (const trigger of BOOKING_TRIGGERS) {
    cleaned = cleaned.replace(trigger, '').trim();
  }
  return cleaned;
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showBooking, setShowBooking] = useState(false);

  const sendMessage = useCallback(async (content: string) => {
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    };
    const withUser = [...messagesRef.current, userMsg];
    messagesRef.current = withUser;
    setMessages(withUser);
    setIsLoading(true);
    setError(null);

    try {
      // Build history for API using the ref (stale-closure safe)
      const history = messagesRef.current.map(m => ({
        role: m.role === 'assistant' ? 'model' : 'user' as const,
        content: m.content,
      }));

      const res = await fetch(`${API_URL}/api/v1/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });

      if (!res.ok) throw new Error('Failed to get response');
      const data = await res.json();
      const rawResponse = data?.response ?? 'Sorry, I could not process that.';

      // Check if the AI wants to trigger booking
      const hasBookingTrigger = detectBookingTrigger(rawResponse);
      const cleanedContent = hasBookingTrigger ? cleanBookingTrigger(rawResponse) : rawResponse;

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: cleanedContent,
        timestamp: new Date(),
        widget: hasBookingTrigger ? 'calendar_picker' : undefined,
      };
      const withAssistant = [...messagesRef.current, assistantMsg];
      messagesRef.current = withAssistant;
      setMessages(withAssistant);

      if (hasBookingTrigger) {
        setShowBooking(true);
      }
    } catch {
      setError('Unable to connect. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const triggerBooking = useCallback(() => {
    setShowBooking(true);
    const bookingMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: "Let me pull up Brandon's availability for you!",
      timestamp: new Date(),
      widget: 'calendar_picker',
    };
    const withBooking = [...messagesRef.current, bookingMsg];
    messagesRef.current = withBooking;
    setMessages(withBooking);
  }, []);

  const addMessage = useCallback((role: 'user' | 'assistant', content: string) => {
    const msg: Message = {
      id: crypto.randomUUID(),
      role,
      content,
      timestamp: new Date(),
    };
    const updated = [...messagesRef.current, msg];
    messagesRef.current = updated;
    setMessages(updated);
  }, []);

  const clearMessages = useCallback(() => {
    messagesRef.current = [];
    setMessages([]);
    setShowBooking(false);
  }, []);

  return { messages, isLoading, error, sendMessage, clearMessages, showBooking, triggerBooking, addMessage };
}
