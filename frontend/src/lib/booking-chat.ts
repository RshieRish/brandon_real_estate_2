'use client';

export const OPEN_BOOKING_CHAT_EVENT = 'sws:open-booking-chat';

export interface BookingChatRequest {
  source?: string;
}

export function openBookingChat(source = 'book-brandon-cta') {
  if (typeof window === 'undefined') return;

  window.dispatchEvent(
    new CustomEvent<BookingChatRequest>(OPEN_BOOKING_CHAT_EVENT, {
      detail: { source },
    }),
  );
}
