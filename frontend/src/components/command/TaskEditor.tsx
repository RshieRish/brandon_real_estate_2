'use client';

import { useCallback, useRef, useState } from 'react';
import { FloppyDisk, X } from '@phosphor-icons/react';
import { useFocusContainment } from '@/components/command/shell/useFocusContainment';
import { commandApi, type Task } from '@/lib/command/api';

type TaskEditorProps = Readonly<{
  task: Task;
  disabled?: boolean;
  onClose: () => void;
  onUpdated: (task: Task) => void;
  onMutationStart?: () => boolean;
  onMutationError?: (error: unknown) => void | Promise<void>;
}>;

function padDatePart(value: number): string {
  return String(value).padStart(2, '0');
}

export function taskInstantToLocalInput(value: string | null): string {
  if (value === null || value.trim().length === 0) return '';
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return '';
  const date = [
    String(instant.getFullYear()).padStart(4, '0'),
    padDatePart(instant.getMonth() + 1),
    padDatePart(instant.getDate()),
  ].join('-');
  let time = `${padDatePart(instant.getHours())}:${padDatePart(instant.getMinutes())}`;
  if (instant.getSeconds() !== 0 || instant.getMilliseconds() !== 0) {
    time += `:${padDatePart(instant.getSeconds())}`;
  }
  if (instant.getMilliseconds() !== 0) {
    time += `.${String(instant.getMilliseconds()).padStart(3, '0')}`;
  }
  return `${date}T${time}`;
}

export function TaskEditor({
  task,
  disabled = false,
  onClose,
  onUpdated,
  onMutationStart,
  onMutationError,
}: TaskEditorProps) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState<Task['priority']>(task.priority);
  const [dueAt, setDueAt] = useState(() => taskInstantToLocalInput(task.due_at));
  const [dueAtDirty, setDueAtDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const dialogRef = useRef<HTMLElement>(null);
  const dismissStateRef = useRef({ disabled, saving, onClose });
  dismissStateRef.current = { disabled, saving, onClose };
  const dismiss = useCallback(() => {
    const current = dismissStateRef.current;
    if (!current.saving && !current.disabled) current.onClose();
  }, []);

  useFocusContainment({
    active: true,
    containerRef: dialogRef,
    onDismiss: dismiss,
  });

  async function save() {
    if (disabled) return;
    if (!title.trim()) {
      setError('Task title is required.');
      return;
    }
    if (onMutationStart !== undefined && !onMutationStart()) return;
    setSaving(true);
    setError('');
    try {
      onUpdated(await commandApi.updateTask(task.id, {
        expected_version: task.version,
        title: title.trim(),
        description,
        priority,
        due_at: dueAtDirty
          ? dueAt ? new Date(dueAt).toISOString() : null
          : dueAt ? task.due_at : null,
      }));
      onClose();
    } catch (caught) {
      await onMutationError?.(caught);
      setError(caught instanceof Error ? caught.message : 'Unable to save task');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4">
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-label="Edit task" tabIndex={-1} className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#12110f] p-6 text-white">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Edit task</h2>
          <button type="button" disabled={saving || disabled} onClick={dismiss} aria-label="Close task editor" className="command-touch-target text-white/55 disabled:opacity-50"><X aria-hidden="true" size={19} /></button>
        </div>
        <div className="mt-5 grid gap-3">
          <input disabled={disabled} value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Task title" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm" />
          <textarea disabled={disabled} value={description} onChange={(event) => setDescription(event.target.value)} aria-label="Task description" placeholder="Task details" className="min-h-24 rounded-lg border border-white/10 bg-black/30 p-3 text-sm" />
          <div className="grid gap-3 sm:grid-cols-2">
            <select disabled={disabled} value={priority} onChange={(event) => setPriority(event.target.value as Task['priority'])} aria-label="Task priority" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm">
              <option value="low">low</option>
              <option value="normal">normal</option>
              <option value="high">high</option>
            </select>
            <input disabled={disabled} value={dueAt} onChange={(event) => { setDueAt(event.target.value); setDueAtDirty(true); }} type="datetime-local" aria-label="Task due date" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm" />
          </div>
        </div>
        {error ? <p role="alert" className="mt-3 text-sm text-red-200">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-3">
          <button type="button" disabled={saving || disabled} onClick={dismiss} className="command-touch-target text-sm text-white/60 disabled:opacity-50">Cancel</button>
          <button type="button" disabled={saving || disabled} onClick={() => void save()} className="command-touch-target inline-flex items-center gap-2 rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50">
            <FloppyDisk aria-hidden="true" size={16} />{saving ? 'Saving…' : 'Save task'}
          </button>
        </div>
      </section>
    </div>
  );
}
