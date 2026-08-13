'use client';

import { useState } from 'react';
import { commandApi, type Goal } from '@/lib/command/api';
import { CommandStatePanel } from '../ui/CommandStatePanel';

export function HomeGoals({
  goals,
  errorMessage,
  onGoalUpdated,
}: {
  goals: readonly Goal[] | null;
  errorMessage?: string;
  onGoalUpdated: (goal: Goal) => void;
}) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [progress, setProgress] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function save(goal: Goal) {
    const value = Number(progress);
    if (!Number.isInteger(value) || value < 0) {
      setError('Progress must be a whole number of zero or more.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const updated = await commandApi.updateGoalProgress(goal.id, value);
      onGoalUpdated(updated);
      setEditingId(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to update goal progress.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="command-home-panel" aria-labelledby="home-goals-heading">
      <div className="command-home-panel-heading">
        <div>
          <span className="command-eyebrow">PACE</span>
          <h2 id="home-goals-heading">Goals</h2>
        </div>
      </div>
      {goals === null ? (
        <CommandStatePanel
          kind="partial_capture"
          title="Goals unavailable"
          message={errorMessage ?? 'The goals region was not supplied.'}
        />
      ) : goals.length === 0 ? (
        <p className="command-home-neutral-copy">No goals set yet.</p>
      ) : (
        <ul className="command-home-goals">
          {goals.map((goal) => {
            const percent = goal.target_value > 0
              ? Math.min(100, Math.round((goal.current_value / goal.target_value) * 100))
              : 0;
            return (
              <li key={goal.id}>
                <div className="command-home-goal-heading">
                  <strong>{goal.name}</strong>
                  <span>{goal.current_value} / {goal.target_value}</span>
                </div>
                <div
                  className="command-home-goal-track"
                  role="progressbar"
                  aria-label={`${goal.name} progress`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={percent}
                >
                  <span style={{ width: `${percent}%` }} />
                </div>
                {editingId === goal.id ? (
                  <div className="command-home-goal-editor">
                    <label>
                      <span>{goal.name} progress</span>
                      <input
                        type="number"
                        min="0"
                        aria-label={`${goal.name} progress`}
                        value={progress}
                        onChange={(event) => setProgress(event.target.value)}
                      />
                    </label>
                    <button
                      type="button"
                      className="command-primary-button command-touch-target"
                      disabled={saving}
                      aria-label={`Save ${goal.name} progress`}
                      onClick={() => void save(goal)}
                    >
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="command-inline-button command-touch-target"
                    aria-label={`Update ${goal.name}`}
                    onClick={() => {
                      setEditingId(goal.id);
                      setProgress(String(goal.current_value));
                      setError('');
                    }}
                  >
                    Update progress
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {error ? <p role="alert" className="command-home-error-copy">{error}</p> : null}
    </section>
  );
}
