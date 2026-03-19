'use client';

import { motion } from 'framer-motion';

interface ReviewCardProps {
  quote: string;
  author: string;
  location?: string;
  rating?: number;
  className?: string;
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill={filled ? '#eac469' : 'none'}
      stroke="#eac469"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  );
}

export default function ReviewCard({
  quote,
  author,
  location,
  rating = 5,
  className = '',
}: ReviewCardProps) {
  return (
    <motion.div
      className={`bg-dark-card border border-dark-border rounded-xl p-6 flex flex-col gap-4 ${className}`}
      whileHover={{ y: -4, boxShadow: '0 8px 32px rgba(234,196,105,0.12)' }}
      transition={{ type: 'spring', stiffness: 100, damping: 20 }}
    >
      {/* Stars */}
      <div className="flex gap-1" role="img" aria-label={`${rating} out of 5 stars`}>
        {Array.from({ length: 5 }).map((_, i) => (
          <StarIcon key={i} filled={i < rating} />
        ))}
      </div>

      {/* Quote */}
      <p className="text-sm text-gray-300 leading-relaxed italic flex-1">
        &ldquo;{quote}&rdquo;
      </p>

      {/* Attribution */}
      <div className="border-t border-dark-border pt-4">
        <p className="text-gold font-semibold text-sm">{author}</p>
        {location && <p className="text-gray text-xs mt-0.5">{location}</p>}
      </div>
    </motion.div>
  );
}
