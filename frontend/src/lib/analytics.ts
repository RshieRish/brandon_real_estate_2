const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function trackEvent(eventType: string, pageUrl: string, metadata?: Record<string, unknown>): Promise<void> {
  try {
    await fetch(`${API_URL}/api/v1/analytics/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_type: eventType,
        page_url: pageUrl,
        metadata: metadata ?? {},
      }),
    });
  } catch {
    // Analytics failures are non-fatal — never throw
  }
}

export function trackPageView(path: string): void {
  trackEvent('page_view', path);
}
