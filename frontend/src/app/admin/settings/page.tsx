'use client';

import { useState } from 'react';
import { CheckCircle, Warning, ArrowsClockwise } from '@phosphor-icons/react';

export default function SettingsPage() {
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm: '',
  });

  return (
    <div className="p-8 max-w-3xl">
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
            <Warning size={24} weight="fill" className="text-yellow-400" />
            <div>
              <p className="text-white font-semibold text-sm">Google Calendar</p>
              <span className="inline-block mt-1 bg-yellow-500/20 text-yellow-400 text-xs px-2 py-0.5 rounded-full uppercase tracking-widest font-semibold">
                Not Configured
              </span>
            </div>
            <p className="text-white/40 text-xs">Add credentials to enable booking</p>
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
