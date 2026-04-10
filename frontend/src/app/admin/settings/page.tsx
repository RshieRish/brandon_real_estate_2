'use client';

import { useEffect, useState } from 'react';
import { ArrowsClockwise, CheckCircle, CircleNotch, Warning } from '@phosphor-icons/react';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface CalendarStatus {
  configured: boolean;
  connected: boolean;
  can_connect: boolean;
  detail: string;
}

export default function SettingsPage() {
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm: '',
  });
  const [calendarStatus, setCalendarStatus] = useState<CalendarStatus | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(true);
  const [calendarActionLoading, setCalendarActionLoading] = useState(false);
  const [calendarError, setCalendarError] = useState('');

  async function loadCalendarStatus() {
    const token = localStorage.getItem('admin_token');
    if (!token) {
      setCalendarLoading(false);
      return null;
    }

    try {
      const res = await fetch(`${API_URL}/api/v1/booking/calendar/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        throw new Error('Could not load calendar status.');
      }

      const data = await res.json() as CalendarStatus;
      setCalendarStatus(data);
      setCalendarError('');
      return data;
    } catch (error) {
      setCalendarError(error instanceof Error ? error.message : 'Could not load calendar status.');
      return null;
    } finally {
      setCalendarLoading(false);
    }
  }

  useEffect(() => {
    loadCalendarStatus();
  }, []);

  async function handleConnectCalendar() {
    const token = localStorage.getItem('admin_token');
    if (!token) return;

    setCalendarActionLoading(true);
    setCalendarError('');

    try {
      const res = await fetch(`${API_URL}/api/v1/booking/calendar/auth-url`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        throw new Error('Could not start Google Calendar authorization.');
      }

      const data = await res.json() as { auth_url: string };
      const popup = window.open(data.auth_url, '_blank', 'noopener,noreferrer');
      if (!popup) {
        window.location.href = data.auth_url;
      }

      let attempts = 0;
      const poll = window.setInterval(async () => {
        attempts += 1;
        const latestStatus = await loadCalendarStatus();
        if (latestStatus?.connected || attempts >= 24) {
          window.clearInterval(poll);
          setCalendarActionLoading(false);
        }
      }, 2500);
    } catch (error) {
      setCalendarActionLoading(false);
      setCalendarError(
        error instanceof Error ? error.message : 'Could not start Google Calendar authorization.'
      );
    }
  }

  const calendarConnected = calendarStatus?.connected;
  const calendarCanConnect = calendarStatus?.can_connect;

  return (
    <div className="p-8 w-full">
      <h1 className="text-white font-black text-2xl mb-8">Settings</h1>

      {/* Integrations */}
      <section>
        <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
          Integrations
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Gemini AI */}
          <div className="bg-dark-card border border-dark-border p-6 rounded-xl flex flex-col gap-3">
            <CheckCircle size={24} weight="fill" className="text-green-400" />
            <div>
              <p className="text-white font-semibold text-sm">Gemini AI</p>
              <span className="inline-block mt-1 bg-green-500/20 text-green-400 text-xs px-2 py-0.5 rounded-full uppercase tracking-widest font-semibold">
                Connected
              </span>
            </div>
            <p className="text-white/40 text-xs">Powering chatbot and AI valuations</p>
          </div>

          {/* Google Calendar */}
          <div className="bg-dark-card border border-dark-border p-6 rounded-xl flex flex-col gap-3">
            {calendarLoading ? (
              <CircleNotch size={24} className="text-gold animate-spin" />
            ) : calendarConnected ? (
              <CheckCircle size={24} weight="fill" className="text-green-400" />
            ) : (
              <Warning size={24} weight="fill" className="text-yellow-400" />
            )}
            <div>
              <p className="text-white font-semibold text-sm">Google Calendar</p>
              <span
                className={`inline-block mt-1 text-xs px-2 py-0.5 rounded-full uppercase tracking-widest font-semibold ${
                  calendarLoading
                    ? 'bg-white/10 text-white/50'
                    : calendarConnected
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-yellow-500/20 text-yellow-400'
                }`}
              >
                {calendarLoading
                  ? 'Checking'
                  : calendarConnected
                    ? 'Connected'
                    : calendarStatus?.configured
                      ? 'Needs Authorization'
                      : 'Not Configured'}
              </span>
            </div>
            <p className="text-white/40 text-xs">
              {calendarStatus?.detail ?? 'Connect Google Calendar to enable live availability and actual booking.'}
            </p>
            {calendarError && (
              <p className="text-red-400/80 text-xs">{calendarError}</p>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              {calendarCanConnect && (
                <button
                  type="button"
                  onClick={handleConnectCalendar}
                  disabled={calendarActionLoading}
                  className="text-xs bg-gold text-black font-bold uppercase tracking-widest px-3 py-2 rounded transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {calendarActionLoading ? 'Waiting For Google' : calendarConnected ? 'Reconnect' : 'Connect Calendar'}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setCalendarLoading(true);
                  void loadCalendarStatus();
                }}
                className="text-xs text-white/70 border border-dark-border hover:border-gold/30 hover:text-white px-3 py-2 rounded transition-colors"
              >
                Refresh Status
              </button>
            </div>
          </div>

          {/* KW CRM */}
          <div className="bg-dark-card border border-dark-border p-6 rounded-xl flex flex-col gap-3">
            <ArrowsClockwise size={24} className="text-white/40" />
            <div>
              <p className="text-white font-semibold text-sm">Keller Williams CRM</p>
              <span className="inline-block mt-1 bg-white/10 text-white/40 text-xs px-2 py-0.5 rounded-full uppercase tracking-widest font-semibold">
                Manual Sync
              </span>
            </div>
            <p className="text-white/40 text-xs">KW Command CRM integration</p>
          </div>
        </div>
      </section>

      {/* Admin Account */}
      <section className="mt-8">
        <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
          Admin Account
        </h2>
        <div className="bg-dark-card border border-dark-border p-6 rounded-xl">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white font-semibold text-sm">Admin Password</p>
              <p className="text-white/40 text-xs mt-1">
                Change your admin panel login password
              </p>
            </div>
            <button
              onClick={() => setShowPasswordForm((v) => !v)}
              className="text-xs text-gold border border-gold/30 hover:bg-gold/10 px-4 py-2 rounded transition-colors cursor-pointer flex-shrink-0"
            >
              Change Password
            </button>
          </div>

          {showPasswordForm && (
            <div className="mt-6 pt-6 border-t border-dark-border">
              <div className="bg-gold/10 border border-gold/20 rounded p-4 mb-4">
                <p className="text-gold text-sm font-medium">This feature is coming soon.</p>
              </div>
              <div className="space-y-3 opacity-50 pointer-events-none">
                <div>
                  <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                    Current Password
                  </label>
                  <input
                    type="password"
                    value={passwordForm.current_password}
                    onChange={(e) =>
                      setPasswordForm((f) => ({ ...f, current_password: e.target.value }))
                    }
                    className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold"
                  />
                </div>
                <div>
                  <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                    New Password
                  </label>
                  <input
                    type="password"
                    value={passwordForm.new_password}
                    onChange={(e) =>
                      setPasswordForm((f) => ({ ...f, new_password: e.target.value }))
                    }
                    className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold"
                  />
                </div>
                <div>
                  <label className="text-white/40 text-xs uppercase tracking-widest block mb-1">
                    Confirm New Password
                  </label>
                  <input
                    type="password"
                    value={passwordForm.confirm}
                    onChange={(e) =>
                      setPasswordForm((f) => ({ ...f, confirm: e.target.value }))
                    }
                    className="w-full bg-dark-surface border border-dark-border text-white text-sm px-3 py-2 rounded focus:outline-none focus:border-gold"
                  />
                </div>
                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    className="text-xs bg-gold text-dark-surface font-bold uppercase tracking-widest px-4 py-2 rounded"
                  >
                    Update Password
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Site */}
      <section className="mt-8">
        <h2 className="text-white/40 text-xs uppercase tracking-widest font-semibold mb-4">
          Site
        </h2>
        <div className="bg-dark-card border border-dark-border p-6 rounded-xl space-y-4">
          {[
            { label: 'Site Name', value: 'SoldWithSweeney.com' },
            { label: 'Agent Name', value: 'Brandon Sweeney' },
            { label: 'License', value: 'REALTOR\u00AE \u2014 Licensed in MA & NH' },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-start justify-between gap-4">
              <p className="text-white/40 text-xs uppercase tracking-widest flex-shrink-0 mt-0.5">
                {label}
              </p>
              <p className="text-white/80 text-sm text-right">{value}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
