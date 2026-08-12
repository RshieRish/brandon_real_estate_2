'use client';

import { useEffect, useState } from 'react';
import { Check, Plus, WarningCircle } from '@phosphor-icons/react';
import { commandApi, type Agreement, type Contact, type Listing, type Opportunity, type Task, type TaskLink } from '@/lib/command/api';

type LinkableRecords = { contact: Contact[]; opportunity: Opportunity[]; agreement: Agreement[]; listing: Listing[] };

export function TasksWorkspace() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState('');
  const [contactId, setContactId] = useState('');
  const [priority, setPriority] = useState('normal');
  const [dueAt, setDueAt] = useState('');
  const [status, setStatus] = useState('all');
  const [dueBefore, setDueBefore] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [links, setLinks] = useState<Record<number, TaskLink[]>>({});
  const [entityType, setEntityType] = useState<keyof LinkableRecords>('opportunity');
  const [entityId, setEntityId] = useState('');
  const [records, setRecords] = useState<LinkableRecords>({ contact: [], opportunity: [], agreement: [], listing: [] });
  const [loadingRecords, setLoadingRecords] = useState(false);

  const load = () => commandApi.tasks({ status: status === 'all' ? undefined : status, due_before: dueBefore ? `${dueBefore}T23:59:59Z` : undefined }).then(setTasks).catch((err) => setError(err.message));
  useEffect(() => { void load(); }, [status, dueBefore]);
  useEffect(() => {
    const loadContacts = async () => {
      const rows: Contact[] = [];
      for (let offset = 0;; offset += 100) {
        const page = await commandApi.contacts(100, offset);
        rows.push(...page);
        if (page.length < 100) break;
      }
      setRecords((current) => ({ ...current, contact: rows }));
    };
    void loadContacts().catch((err) => setError(err instanceof Error ? err.message : 'Unable to load contacts'));
  }, []);

  async function add() {
    if (!title.trim()) return;
    try {
      const task = await commandApi.createTask({ title: title.trim(), description: '', priority, contact_id: contactId ? Number(contactId) : null, due_at: dueAt ? new Date(dueAt).toISOString() : null });
      setTasks((all) => [...all, task]); setTitle(''); setContactId(''); setDueAt('');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create task'); }
  }
  async function complete(task: Task) { try { const updated = await commandApi.updateTask(task.id, { status: task.status === 'completed' ? 'open' : 'completed' }); setTasks((all) => all.map((item) => item.id === task.id ? updated : item)); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update task'); } }
  async function edit(task: Task) { const nextTitle = window.prompt('Task title', task.title); if (nextTitle === null || !nextTitle.trim()) return; const description = window.prompt('Task details', task.description); if (description === null) return; const nextPriority = window.prompt('Priority: low, normal, or high', task.priority); if (nextPriority === null || !['low', 'normal', 'high'].includes(nextPriority)) return; const nextDueAt = window.prompt('Due date/time (ISO, blank to clear)', task.due_at ?? ''); if (nextDueAt === null) return; try { const updated = await commandApi.updateTask(task.id, { title: nextTitle.trim(), description, priority: nextPriority, due_at: nextDueAt || null }); setTasks((all) => all.map((item) => item.id === task.id ? updated : item)); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to edit task'); } }
  async function assignContact(task: Task, nextContactId: string) { try { const updated = await commandApi.updateTask(task.id, { contact_id: nextContactId ? Number(nextContactId) : null }); setTasks((all) => all.map((item) => item.id === task.id ? updated : item)); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to assign task contact'); } }
  async function showLinks(taskId: number) { try { const rows = await commandApi.taskLinks(taskId); setLinks((all) => ({ ...all, [taskId]: rows })); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load task links'); } }
  async function openLinker(taskId: number) {
    setSelected(taskId); setEntityId(''); setLoadingRecords(true);
    try {
      const contacts: Contact[] = [];
      for (let offset = 0;; offset += 100) { const page = await commandApi.contacts(100, offset); contacts.push(...page); if (page.length < 100) break; }
      const [opportunity, agreement, listing] = await Promise.all([commandApi.opportunities(), commandApi.agreements(), commandApi.listings()]);
      setRecords({ contact: contacts, opportunity, agreement, listing });
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load internal records'); }
    finally { setLoadingRecords(false); }
  }
  async function linkTask() { if (!selected || !entityId) return; try { await commandApi.addTaskLink(selected, entityType, Number(entityId)); await showLinks(selected); setEntityId(''); setSelected(null); } catch (err) { setError(err instanceof Error ? err.message : 'Unable to link task'); } }
  const recordLabel = (type: keyof LinkableRecords, record: Contact | Opportunity | Agreement | Listing) => {
    if (type === 'contact') { const contact = record as Contact; return `${contact.first_name} ${contact.last_name}`.trim(); }
    if (type === 'listing') return (record as Listing).address;
    if (type === 'opportunity') return (record as Opportunity).name;
    return (record as Agreement).title;
  };

  return <div className="min-h-[100dvh] bg-[#080807] p-6 text-white"><main className="mx-auto max-w-5xl"><p className="text-xs uppercase tracking-[.25em] text-[#eac469]">Internal CRM</p><h1 className="mt-1 text-3xl font-black">Tasks</h1><div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto_auto]"><input value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && add()} placeholder="Add a task" className="rounded-xl border border-white/10 bg-white/5 px-4 py-3" /><select aria-label="Assign task contact" value={contactId} onChange={(event) => setContactId(event.target.value)} className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"><option value="">No contact</option>{records.contact.map((contact) => <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>)}</select><select value={priority} onChange={(event) => setPriority(event.target.value)} className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm"><option value="low">low</option><option value="normal">normal</option><option value="high">high</option></select><input value={dueAt} onChange={(event) => setDueAt(event.target.value)} type="datetime-local" aria-label="Task due date" className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm" /><button onClick={add} className="rounded-xl bg-[#eac469] px-4 text-black"><Plus size={19} /></button></div><div className="mt-4 flex flex-wrap gap-3"><select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-lg border border-white/10 bg-black/40 p-2 text-sm"><option value="all">All statuses</option><option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select><input value={dueBefore} onChange={(event) => setDueBefore(event.target.value)} type="date" className="rounded-lg border border-white/10 bg-black/40 p-2 text-sm" aria-label="Due by" /></div>{error && <p className="mt-4 flex gap-2 text-red-300"><WarningCircle size={18} />{error}</p>}<div className="mt-6 space-y-2">{tasks.map((task) => <div key={task.id} className="rounded-xl border border-white/10 bg-white/[.035] p-4"><div className="flex items-center gap-4"><button onClick={() => complete(task)} aria-label={`Toggle ${task.title}`} className={`grid h-6 w-6 place-items-center rounded-full border ${task.status === 'completed' ? 'border-[#eac469] bg-[#eac469] text-black' : 'border-white/30'}`}>{task.status === 'completed' && <Check size={15} />}</button><span className={task.status === 'completed' ? 'text-white/35 line-through' : 'font-medium'}>{task.title}</span><button onClick={() => edit(task)} className="ml-auto text-xs text-white/55">Edit</button><button onClick={() => openLinker(task.id)} className="text-xs font-bold text-[#eac469]">Link record</button><button onClick={() => showLinks(task.id)} className="text-xs text-white/55">Show links</button><span className="text-xs uppercase text-white/45">{task.priority}</span></div>{task.description && <p className="mt-2 text-sm text-white/60">{task.description}</p>}<div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/40"><span>{task.due_at ? `Due ${new Date(task.due_at).toLocaleString()}` : 'No due date'}</span><select aria-label={`Assign ${task.title} contact`} value={task.contact_id ?? ''} onChange={(event) => assignContact(task, event.target.value)} className="rounded bg-black/30 px-2 py-1 text-xs"><option value="">No contact</option>{records.contact.map((contact) => <option key={contact.id} value={contact.id}>{contact.first_name} {contact.last_name}</option>)}</select></div>{links[task.id]?.length ? <p className="mt-2 text-xs text-white/45">{links[task.id].map((link) => `${link.entity_type}: ${link.display_name}`).join(' · ')}</p> : null}</div>)}{!tasks.length && <p className="rounded-xl border border-dashed border-white/15 p-10 text-center text-white/40">No matching tasks.</p>}</div>{selected && <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4"><section className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#12110f] p-6"><h2 className="text-lg font-bold">Link internal record</h2><div className="mt-4 grid gap-3"><select value={entityType} onChange={(event) => { setEntityType(event.target.value as keyof LinkableRecords); setEntityId(''); }} className="rounded-lg bg-black/40 p-3 text-sm"><option value="opportunity">Opportunity</option><option value="agreement">Agreement</option><option value="listing">Listing</option><option value="contact">Contact</option></select><select aria-label="Internal record to link" disabled={loadingRecords} value={entityId} onChange={(event) => setEntityId(event.target.value)} className="rounded-lg bg-black/40 p-3 text-sm"><option value="">{loadingRecords ? 'Loading internal records…' : 'Select internal record'}</option>{records[entityType].map((record) => <option key={record.id} value={record.id}>{recordLabel(entityType, record)}</option>)}</select></div><div className="mt-5 flex justify-end gap-3"><button onClick={() => setSelected(null)} className="text-sm text-white/60">Cancel</button><button disabled={!entityId || loadingRecords} onClick={linkTask} className="rounded-lg bg-[#eac469] px-4 py-2 text-sm font-bold text-black disabled:opacity-50">Link</button></div></section></div>}</main></div>;
}
