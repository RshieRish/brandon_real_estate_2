const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export function trackEvent(
  event_type: string,
  metadata: Record<string, unknown> = {},
): void {
  if (typeof window === 'undefined') return;
  void fetch(`${API_URL}/api/v1/analytics/event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_type,
      page: window.location.pathname,
      referrer: document.referrer || undefined,
      user_agent: navigator.userAgent,
      metadata,
    }),
    keepalive: true,
  }).catch(() => undefined);
}
