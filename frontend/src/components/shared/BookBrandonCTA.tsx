'use client';

import type { ReactNode } from 'react';
import CTAButton from '@/components/shared/CTAButton';
import { openBookingChat } from '@/lib/booking-chat';

interface BookBrandonCTAProps {
  children: ReactNode;
  variant?: 'gold' | 'outline' | 'ghost';
  className?: string;
  source?: string;
  onOpen?: () => void;
}

export default function BookBrandonCTA({
  children,
  variant = 'gold',
  className = '',
  source = 'book-brandon-cta',
  onOpen,
}: BookBrandonCTAProps) {
  return (
    <CTAButton
      variant={variant}
      className={className}
      onClick={() => {
        onOpen?.();
        openBookingChat(source);
      }}
    >
      {children}
    </CTAButton>
  );
}
