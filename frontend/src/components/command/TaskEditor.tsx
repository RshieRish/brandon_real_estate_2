'use client';

import { useState } from 'react';
import { FloppyDisk, X } from '@phosphor-icons/react';
import { commandApi, type Task } from '@/lib/command/api';

export function TaskEditor({ task, onClose, onUpdated, onMutationError }: { task: Task; onClose: () => void; onUpdated: (task: Task) => void; onMutationError?: (error: unknown) => void | Promise<void> }) {
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState<Task['priority']>(task.priority);
  const [dueAt, setDueAt] = useState(task.due_at ? task.due_at.slice(0, 16) : '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function save() {
    if (!title.trim()) { setError('Task title is required.'); return; }
    setSaving(true); setError('');
    try { onUpdated(await commandApi.updateTask(task.id, { expected_version: task.version, title: title.trim(), description, priority, due_at: dueAt ? new Date(dueAt).toISOString() : null })); onClose(); }
    catch (err) { await onMutationError?.(err); setError(err instanceof Error ? err.message : 'Unable to save task'); }
    finally { setSaving(false); }
  }
  return <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4"><section role="dialog" aria-modal="true" aria-label="Edit task" className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#12110f] p-6 text-white"><div className="flex items-center justify-between"><h2 className="text-lg font-bold">Edit task</h2><button onClick={onClose} aria-label="Close task editor" className="text-white/55"><X size={19}/></button></div><div className="mt-5 grid gap-3"><input value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Task title" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><textarea value={description} onChange={(event) => setDescription(event.target.value)} aria-label="Task description" placeholder="Task details" className="min-h-24 rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/><div className="grid gap-3 sm:grid-cols-2"><select value={priority} onChange={(event) => setPriority(event.target.value as Task['priority'])} aria-label="Task priority" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"><option value="low">low</option><option value="normal">normal</option><option value="high">high</option></select><input value={dueAt} onChange={(event) => setDueAt(event.target.value)} type="datetime-local" aria-label="Task due date" className="rounded-lg border border-white/10 bg-black/30 p-3 text-sm"/></div></div>{error && <p role="alert" className="mt-3 text-sm text-red-200">{error}</p>}<div className="mt-5 flex justify-end gap-3"><button onClick={onClose} className="text-sm text-white/60">Cancel</button><button disabled={saving} onClick={save} className="inline-flex items-center gap-2 rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50"><FloppyDisk size={16}/>{saving ? 'Saving…' : 'Save task'}</button></div></section></div>;
}
