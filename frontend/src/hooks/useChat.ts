'use client';
import { useState, useCallback, useRef } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
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
      const data = await res.json();

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data?.response ?? 'Sorry, I could not process that.',
        timestamp: new Date(),
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

  const clearMessages = useCallback(() => {
    messagesRef.current = [];
    setMessages([]);
  }, []);

  return { messages, isLoading, error, sendMessage, clearMessages };
}
