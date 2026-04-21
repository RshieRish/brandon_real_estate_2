'use client';
import { useState, useCallback, useRef } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export type ChatWidget = 'calendar_picker';
export type ChatWidgetMode = 'guided' | 'next_available';

export interface ChatAction {
  type: 'send_message' | 'navigate' | 'open_widget';
  label: string;
  message?: string;
  href?: string;
  widget?: ChatWidget;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  actions?: ChatAction[];
  widget?: ChatWidget;
  widgetMode?: ChatWidgetMode;
}

interface ChatApiResponse {
  text?: string;
  response?: string;
  actions?: unknown;
  widget?: unknown;
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

function normalizeWidget(value: unknown): ChatWidget | undefined {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (normalized === 'calendar_picker' || normalized === 'calendar' || normalized === 'booking') {
    return 'calendar_picker';
  }
  return undefined;
}

function normalizeAction(value: unknown): ChatAction | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const action = value as Record<string, unknown>;
  const type = typeof action.type === 'string' ? action.type : '';
  const label = typeof action.label === 'string' ? action.label.trim() : '';

  if (!label) {
    return null;
  }

  if (type === 'send_message') {
    const message = typeof action.message === 'string' ? action.message.trim() : '';
    if (!message) {
      return null;
    }
    return { type, label, message };
  }

  if (type === 'navigate') {
    const href = typeof action.href === 'string' ? action.href.trim() : '';
    if (!href) {
      return null;
    }
    return { type, label, href };
  }

  if (type === 'open_widget') {
    const widget = normalizeWidget(action.widget);
    if (!widget) {
      return null;
    }
    return { type, label, widget };
  }

  return null;
}

function normalizeAssistantPayload(data: ChatApiResponse): Pick<Message, 'content' | 'actions' | 'widget'> {
  const rawText = typeof data.text === 'string'
    ? data.text
    : typeof data.response === 'string'
      ? data.response
      : 'Sorry, I could not process that.';

  const hasBookingTrigger = detectBookingTrigger(rawText);
  const cleanedContent = hasBookingTrigger ? cleanBookingTrigger(rawText) : rawText.trim();
  const normalizedActions = Array.isArray(data.actions)
    ? data.actions.map(normalizeAction).filter((action): action is ChatAction => action !== null)
    : [];
  const widget = normalizeWidget(data.widget) ?? (hasBookingTrigger ? 'calendar_picker' : undefined);

  return {
    content: cleanedContent || (widget === 'calendar_picker' ? "Let me pull up Brandon's availability for you!" : 'Sorry, I could not process that.'),
    actions: normalizedActions,
    widget,
  };
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesRef = useRef<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      const data = await res.json() as ChatApiResponse;
      const assistantPayload = normalizeAssistantPayload(data);

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: assistantPayload.content,
        timestamp: new Date(),
        actions: assistantPayload.actions,
        widget: assistantPayload.widget,
      };
      const withAssistant = [...messagesRef.current, assistantMsg];
      messagesRef.current = withAssistant;
      setMessages(withAssistant);
    } catch {
      setError('Unable to connect. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const triggerBooking = useCallback((
    content = 'How would you like to meet Brandon? Choose phone call, Google Meet, or in person to keep booking.',
    widgetMode: ChatWidgetMode = 'guided',
  ) => {
    const bookingMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content,
      timestamp: new Date(),
      widget: 'calendar_picker',
      widgetMode,
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
  }, []);

  return { messages, isLoading, error, sendMessage, clearMessages, triggerBooking, addMessage };
}
