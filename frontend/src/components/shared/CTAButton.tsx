'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import type { ReactNode } from 'react';

type Variant = 'gold' | 'outline' | 'ghost';

interface CTAButtonBase {
  children: ReactNode;
  variant?: Variant;
  className?: string;
}

interface CTAButtonWithHref extends CTAButtonBase {
  href: string;
  external?: boolean;
  onClick?: () => void;
  type?: never;
  disabled?: never;
}

interface CTAButtonWithClick extends CTAButtonBase {
  href?: never;
  external?: never;
  onClick?: () => void;
  type?: 'button' | 'submit' | 'reset';
  disabled?: boolean;
}

type CTAButtonProps = CTAButtonWithHref | CTAButtonWithClick;

const BASE =
  'inline-flex items-center gap-2 px-6 py-3 font-bold text-sm tracking-widest uppercase transition-colors duration-200 rounded-none';

const VARIANTS: Record<Variant, string> = {
  gold: 'bg-gold text-[#0a0a0a] hover:bg-gold-hover',
  outline: 'border border-gold text-gold hover:bg-gold hover:text-[#0a0a0a]',
  ghost: 'text-gold hover:text-white underline-offset-4 hover:underline',
};

const MOTION = {
  whileHover: { scale: 1.02 },
  whileTap: { scale: 0.98 },
  transition: { type: 'spring' as const, stiffness: 100, damping: 20 },
};

export default function CTAButton({
  children,
  variant = 'gold',
  className = '',
  href,
  external = false,
  onClick,
  type = 'button',
  disabled = false,
}: CTAButtonProps) {
  const classes = `${BASE} ${VARIANTS[variant]} ${className}`;
  const style = { letterSpacing: '0.12em' };

  if (href) {
    const inner = (
      <motion.span className={classes} style={style} {...MOTION}>
        {children}
      </motion.span>
    );

    if (external) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" onClick={onClick}>
          {inner}
        </a>
      );
    }

    return (
      <Link href={href} onClick={onClick}>
        {inner}
      </Link>
    );
  }

  return (
    <motion.button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${classes} disabled:opacity-50 disabled:cursor-not-allowed`}
      style={style}
      whileHover={disabled ? undefined : MOTION.whileHover}
      whileTap={disabled ? undefined : MOTION.whileTap}
      transition={MOTION.transition}
    >
      {children}
    </motion.button>
  );
}
