'use client';

import Link from 'next/link';
import { useState } from 'react';
import type { Task } from '@/lib/command/api';
import { CommandTabs } from '../ui/CommandTabs';

const taskTabs = [
  { value: 'my', label: 'My Tasks' },
  { value: 'team', label: 'Team Tasks' },
  { value: 'all', label: 'All Tasks' },
] as const;

type TaskScope = (typeof taskTabs)[number]['value'];
const taskDueCutoff = Date.now();

export function HomeTaskQueue({
  tasks,
  onCreateTask,
}: {
  tasks: readonly Task[];
  onCreateTask: () => void;
}) {
  const [scope, setScope] = useState<TaskScope>('my');
  const [dueFilter, setDueFilter] = useState('all');
  const filteredTasks = scope === 'team'
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
        {scope === 'team' ? (
          <p className="command-home-neutral-copy">Team task ownership is unavailable in the current internal API.</p>
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
