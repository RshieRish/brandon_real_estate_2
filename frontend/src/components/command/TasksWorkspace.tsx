'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Plus, WarningCircle } from '@phosphor-icons/react';
import { TaskEditor } from '@/components/command/TaskEditor';
import { applyTaskWorkspaceView, type TaskWorkspaceView } from '@/components/command/workspaceFilters';
import {
  commandApi,
  CommandConflictError,
  CommandOutcomeUncertainError,
  type Agreement,
  type Contact,
  type Listing,
  type Opportunity,
  type Task,
  type TaskLink,
} from '@/lib/command/api';

type LinkableRecords = {
  contact: Contact[];
  opportunity: Opportunity[];
  agreement: Agreement[];
  listing: Listing[];
};

export function TasksWorkspace({
  initialView = { tab: 'all', due: 'all' },
}: {
  initialView?: TaskWorkspaceView;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState('');
  const [contactId, setContactId] = useState('');
  const [priority, setPriority] = useState<Task['priority']>('normal');
  const [dueAt, setDueAt] = useState('');
  const [status, setStatus] = useState<TaskWorkspaceView['tab']>(initialView.tab);
  const [dueScope, setDueScope] = useState<TaskWorkspaceView['due']>(initialView.due);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [links, setLinks] = useState<Record<number, readonly TaskLink[]>>({});
  const [entityType, setEntityType] = useState<keyof LinkableRecords>('opportunity');
  const [entityId, setEntityId] = useState('');
  const [records, setRecords] = useState<LinkableRecords>({
    contact: [],
    opportunity: [],
    agreement: [],
    listing: [],
  });
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const createPendingRef = useRef(false);
  const [creating, setCreating] = useState(false);

  const refetchAllTasks = useCallback(async () => {
    const rows = await commandApi.tasks({ visibility: 'all' });
    setTasks([...rows]);
  }, []);

  useEffect(() => {
    void refetchAllTasks().catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : 'Unable to load tasks');
    });
  }, [refetchAllTasks]);

  const reconcileMutationFailure = useCallback(async (caught: unknown, fallback: string) => {
    if (caught instanceof CommandOutcomeUncertainError || caught instanceof CommandConflictError) {
      try {
        await refetchAllTasks();
      } catch {
        // The original mutation result remains the error the user must reconcile.
      }
    }
    setError(caught instanceof Error ? caught.message : fallback);
  }, [refetchAllTasks]);

  useEffect(() => {
    const loadContacts = async () => {
      const rows: Contact[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await commandApi.contacts(100, offset);
        rows.push(...page);
        if (page.length < 100) break;
      }
      setRecords((current) => ({ ...current, contact: rows }));
    };
    void loadContacts().catch((caught) => {
      setError(caught instanceof Error ? caught.message : 'Unable to load contacts');
    });
  }, []);

  async function add() {
    if (!title.trim() || createPendingRef.current) return;
    createPendingRef.current = true;
    setCreating(true);
    try {
      const task = await commandApi.createTask({
        title: title.trim(),
        description: '',
        priority,
        contact_id: contactId ? Number(contactId) : null,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      }, crypto.randomUUID());
      setTasks((all) => [...all, task]);
      setTitle('');
      setContactId('');
      setDueAt('');
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to create task');
    } finally {
      createPendingRef.current = false;
      setCreating(false);
    }
  }

  async function complete(task: Task) {
    try {
      const updated = await commandApi.updateTask(task.id, {
        expected_version: task.version,
        status: task.status === 'completed' ? 'open' : 'completed',
      });
      setTasks((all) => all.map((item) => item.id === task.id ? updated : item));
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to update task');
    }
  }

  async function assignContact(task: Task, nextContactId: string) {
    try {
      const updated = await commandApi.updateTask(task.id, {
        expected_version: task.version,
        contact_id: nextContactId ? Number(nextContactId) : null,
      });
      setTasks((all) => all.map((item) => item.id === task.id ? updated : item));
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to assign task contact');
    }
  }

  async function showLinks(taskId: number) {
    try {
      const rows = await commandApi.taskLinks(taskId);
      setLinks((all) => ({ ...all, [taskId]: rows }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load task links');
    }
  }

  async function openLinker(taskId: number) {
    setSelected(taskId);
    setEntityId('');
    setLoadingRecords(true);
    try {
      const contacts: Contact[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await commandApi.contacts(100, offset);
        contacts.push(...page);
        if (page.length < 100) break;
      }
      const [opportunity, agreement, listing] = await Promise.all([
        commandApi.opportunities(),
        commandApi.agreements(),
        commandApi.listings(),
      ]);
      setRecords({ contact: contacts, opportunity, agreement, listing });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load internal records');
    } finally {
      setLoadingRecords(false);
    }
  }

  async function linkTask() {
    if (!selected || !entityId) return;
    const task = tasks.find((candidate) => candidate.id === selected);
    if (!task) return;
    try {
      const created = await commandApi.addTaskLink(selected, {
        expected_version: task.version,
        entity_type: entityType,
        entity_id: Number(entityId),
      });
      setTasks((all) => all.map((item) => item.id === selected
        ? { ...item, version: created.task_version }
        : item));
      await showLinks(selected);
      setEntityId('');
      setSelected(null);
    } catch (caught) {
      await reconcileMutationFailure(caught, 'Unable to link task');
    }
  }

  function recordLabel(type: keyof LinkableRecords, record: Contact | Opportunity | Agreement | Listing) {
    if (type === 'contact') {
      const contact = record as Contact;
      return `${contact.first_name} ${contact.last_name}`.trim();
    }
    if (type === 'listing') return (record as Listing).address;
    if (type === 'opportunity') return (record as Opportunity).name;
    return (record as Agreement).title;
  }

  const visibleTasks = applyTaskWorkspaceView(tasks, { tab: status, due: dueScope }, new Date());

  return (
    <div className="min-h-[100dvh] bg-[#080807] p-6 text-white">
      <main className="mx-auto max-w-5xl">
        <p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Internal CRM</p>
        <h1 className="mt-1 text-3xl font-black">Tasks</h1>
        <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto_auto]">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && void add()}
            placeholder="Add a task"
            className="rounded-xl border border-white/10 bg-white/5 px-4 py-3"
          />
          <select
            aria-label="Assign task contact"
            value={contactId}
            onChange={(event) => setContactId(event.target.value)}
            className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"
          >
            <option value="">No contact</option>
            {records.contact.map((contact) => (
              <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>
            ))}
          </select>
          <select
            aria-label="Task priority"
            value={priority}
            onChange={(event) => setPriority(event.target.value as Task['priority'])}
            className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"
          >
            <option value="low">low</option>
            <option value="normal">normal</option>
            <option value="high">high</option>
          </select>
          <input
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
            type="datetime-local"
            aria-label="Task due date"
            className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"
          />
          <button type="button" disabled={creating} onClick={() => void add()} aria-label="Add task" className="rounded-xl bg-[#eac469] px-4 text-black disabled:opacity-50">
            <Plus size={19} />
          </button>
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <select
            aria-label="Task status"
            value={status}
            onChange={(event) => setStatus(event.target.value as TaskWorkspaceView['tab'])}
            className="rounded-lg border border-white/10 bg-black/40 p-2 text-sm"
          >
            <option value="all">All statuses</option>
            <option value="todo">To do</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <select
            aria-label="Task due scope"
            value={dueScope}
            onChange={(event) => setDueScope(event.target.value as TaskWorkspaceView['due'])}
            className="rounded-lg border border-white/10 bg-black/40 p-2 text-sm"
          >
            <option value="all">All due dates</option>
            <option value="past">Past due</option>
          </select>
        </div>
        {error ? <p className="mt-4 flex gap-2 text-red-300"><WarningCircle size={18} />{error}</p> : null}
        <div className="mt-6 space-y-2">
          {visibleTasks.map((task) => (
            <div key={task.id} className="rounded-xl border border-white/10 bg-white/[.035] p-4">
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => void complete(task)}
                  aria-label={`Toggle ${task.title}`}
                  className={`grid h-6 w-6 place-items-center rounded-full border ${task.status === 'completed' ? 'border-[#eac469] bg-[#eac469] text-black' : 'border-white/30'}`}
                >
                  {task.status === 'completed' ? <Check size={15} /> : null}
                </button>
                <span className={task.status === 'completed' ? 'text-white/35 line-through' : 'font-medium'}>{task.title}</span>
                <button type="button" onClick={() => setEditing(task)} className="ml-auto text-xs text-white/55">Edit</button>
                <button type="button" onClick={() => void openLinker(task.id)} className="text-xs font-bold text-[#eac469]">Link record</button>
                <button type="button" onClick={() => void showLinks(task.id)} className="text-xs text-white/55">Show links</button>
                <span className="text-xs uppercase text-white/45">{task.priority}</span>
              </div>
              {task.description ? <p className="mt-2 text-sm text-white/60">{task.description}</p> : null}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/40">
                <span>{task.due_at ? `Due ${new Date(task.due_at).toLocaleString()}` : 'No due date'}</span>
                <select
                  aria-label={`Assign ${task.title} contact`}
                  value={task.contact_id ?? ''}
                  onChange={(event) => void assignContact(task, event.target.value)}
                  className="rounded bg-black/30 px-2 py-1 text-xs"
                >
                  <option value="">No contact</option>
                  {records.contact.map((contact) => (
                    <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>
                  ))}
                </select>
              </div>
              {links[task.id]?.length ? (
                <p className="mt-2 text-xs text-white/45">
                  {links[task.id].map((link) => `${link.entity_type}: ${link.display_name}`).join(' · ')}
                </p>
              ) : null}
            </div>
          ))}
          {visibleTasks.length === 0 ? (
            <p className="rounded-xl border border-dashed border-white/15 p-10 text-center text-white/40">No matching tasks.</p>
          ) : null}
        </div>
        {selected ? (
          <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4">
            <section className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#12110f] p-6">
              <h2 className="text-lg font-bold">Link internal record</h2>
              <div className="mt-4 grid gap-3">
                <select
                  aria-label="Internal record type"
                  value={entityType}
                  onChange={(event) => {
                    setEntityType(event.target.value as keyof LinkableRecords);
                    setEntityId('');
                  }}
                  className="rounded-lg bg-black/40 p-3 text-sm"
                >
                  <option value="opportunity">Opportunity</option>
                  <option value="agreement">Agreement</option>
                  <option value="listing">Listing</option>
                  <option value="contact">Contact</option>
                </select>
                <select
                  aria-label="Internal record to link"
                  disabled={loadingRecords}
                  value={entityId}
                  onChange={(event) => setEntityId(event.target.value)}
                  className="rounded-lg bg-black/40 p-3 text-sm"
                >
                  <option value="">{loadingRecords ? 'Loading internal records…' : 'Select internal record'}</option>
                  {records[entityType].map((record) => (
                    <option key={record.id} value={record.id}>{recordLabel(entityType, record)}</option>
                  ))}
                </select>
              </div>
              <div className="mt-5 flex justify-end gap-3">
                <button type="button" onClick={() => setSelected(null)} className="text-sm text-white/60">Cancel</button>
                <button
                  type="button"
                  disabled={!entityId || loadingRecords}
                  onClick={() => void linkTask()}
                  className="rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50"
                >
                  Link
                </button>
              </div>
            </section>
          </div>
        ) : null}
        {editing ? (
          <TaskEditor
            task={editing}
            onClose={() => setEditing(null)}
            onUpdated={(updated) => setTasks((all) => all.map((item) => item.id === updated.id ? updated : item))}
            onMutationError={(caught) => reconcileMutationFailure(caught, 'Unable to save task')}
          />
        ) : null}
      </main>
    </div>
  );
}
