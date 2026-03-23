'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { ArrowClockwise, LockKey, User } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        setError('Invalid credentials');
        return;
      }

      const data = await res.json();
      localStorage.setItem('admin_token', data.access_token);
      router.push('/admin');
    } catch {
      setError('Invalid credentials');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-[100dvh] bg-dark-surface flex items-center justify-center px-4">
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
        className="relative w-full max-w-sm bg-dark-card border border-dark-border rounded-2xl p-10 overflow-hidden"
        style={{
          boxShadow: '0 0 0 1px rgba(234,196,105,0.04) inset, 0 32px 64px rgba(0,0,0,0.6)',
        }}
      >
        {/* Gold top accent line */}
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-gold to-transparent" />

        {/* Logo area */}
        <div className="mb-8 text-center">
          <p className="text-gold font-black text-lg tracking-tight leading-none">Sweeney &amp; Co.</p>
          <p className="text-white/40 text-xs mt-1 uppercase tracking-widest">Admin</p>
        </div>

        {/* Error banner */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: 'spring' as const, stiffness: 100, damping: 20 }}
            className="mb-6 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400/80 text-sm text-center"
          >
            {error}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* Username */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30">
              <User size={16} />
            </span>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="w-full bg-dark-surface border border-dark-border rounded-lg pl-9 pr-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-gold/40 focus:ring-1 focus:ring-gold/20 transition-colors"
            />
          </div>

          {/* Password */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30">
              <LockKey size={16} />
            </span>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full bg-dark-surface border border-dark-border rounded-lg pl-9 pr-4 py-3 text-sm text-white placeholder-white/30 outline-none focus:border-gold/40 focus:ring-1 focus:ring-gold/20 transition-colors"
            />
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={isLoading}
            className="mt-2 w-full bg-gold text-black font-bold text-sm py-3 rounded-lg flex items-center justify-center gap-2 hover:bg-gold-hover transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <ArrowClockwise size={16} className="animate-spin" />
            ) : (
              'Sign In'
            )}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
