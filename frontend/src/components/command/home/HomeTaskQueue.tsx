'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { Task } from '@/lib/command/api';
import { CommandTabs } from '../ui/CommandTabs';
import { CommandStatePanel } from '../ui/CommandStatePanel';

const taskTabs = [
  { value: 'personal', label: 'Personal' },
  { value: 'team', label: 'Team' },
  { value: 'all', label: 'All' },
] as const;

type TaskScope = (typeof taskTabs)[number]['value'];
const taskDueCutoff = Date.now();

export function HomeTaskQueue({
  tasks,
  errorMessage,
  onCreateTask,
}: {
  tasks: readonly Task[] | null;
  errorMessage?: string;
  onCreateTask: () => void;
}) {
  const [scope, setScope] = useState<TaskScope>('all');
  const [dueFilter, setDueFilter] = useState('all');
  const filteredTasks = scope !== 'all' || tasks === null
    ? []
    : tasks.filter((task) => {
        if (dueFilter === 'undated') return task.due_at === null;
        if (dueFilter === 'overdue') return Boolean(task.due_at && Date.parse(task.due_at) < taskDueCutoff);
        return true;
      });

  return (
    <section className="command-home-panel command-home-task-queue" aria-labelledby="home-task-queue-heading">
      <div className="command-home-panel-heading">
        <div>
          <span className="command-eyebrow">WORK QUEUE</span>
          <h2 id="home-task-queue-heading">Tasks that need attention</h2>
        </div>
        <button
          type="button"
          className="command-secondary-button command-touch-target"
          aria-label="Create task from queue"
          onClick={onCreateTask}
        >
          Create task
        </button>
      </div>
      <CommandTabs
        idBase="home-task-scope"
        ariaLabel="Task scope"
        tabs={taskTabs}
        value={scope}
        onValueChange={setScope}
      />
      <div className="command-home-task-filters" aria-label="Task filters">
        <label>
          Due scope
          <select value={dueFilter} onChange={(event) => setDueFilter(event.target.value)}>
            <option value="all">All due dates</option>
            <option value="overdue">Overdue</option>
            <option value="undated">No due date</option>
          </select>
        </label>
        <label>
          Source
          <select value="internal" disabled aria-label="Task source">
            <option value="internal">Internal CRM</option>
          </select>
        </label>
      </div>
      <div
        id={`home-task-scope-panel-${scope}`}
        role="tabpanel"
        aria-labelledby={`home-task-scope-tab-${scope}`}
      >
        {tasks === null ? (
          <CommandStatePanel
            kind="partial_capture"
            title="Tasks unavailable"
            message={errorMessage ?? 'The task region was not supplied.'}
          />
        ) : scope !== 'all' ? (
          <CommandStatePanel
            kind="partial_capture"
            title={`${scope === 'personal' ? 'Personal' : 'Team'} task ownership is unavailable`}
            message="The current internal task records do not include owner evidence. Use All to view the verified queue."
          />
        ) : filteredTasks.length === 0 ? (
          <p className="command-home-positive-copy">No open tasks in scope.</p>
        ) : (
          <ul className="command-home-task-list">
            {filteredTasks.slice(0, 5).map((task) => (
              <li key={task.id}>
                <div>
                  <strong>{task.title}</strong>
                  <span>{task.due_at ? `Due ${new Date(task.due_at).toLocaleDateString()}` : 'No due date'}</span>
                </div>
                <small>{task.priority} · {task.status.replace('_', ' ')}</small>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Link className="command-home-view-all command-touch-target" href="/admin/command/tasks">
        View all tasks
      </Link>
    </section>
  );
}
