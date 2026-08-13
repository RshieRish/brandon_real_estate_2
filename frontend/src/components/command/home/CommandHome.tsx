'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { commandApi, type Goal } from '@/lib/command/api';
import {
  loadCommandHome,
  type CommandHomeModel,
} from '@/lib/command/home';
import { CommandModuleHeader } from '../ui/CommandModuleHeader';
import { CommandOverlay } from '../ui/CommandOverlay';
import { CommandStatePanel } from '../ui/CommandStatePanel';
import { FollowUpReadinessHero } from './FollowUpReadinessHero';
import { HomeContextPanels } from './HomeContextPanels';
import { HomeGoals } from './HomeGoals';
import { HomeKpiStrip } from './HomeKpiStrip';
import { HomeShortcutStrip } from './HomeShortcutStrip';
import { HomeTaskQueue } from './HomeTaskQueue';

export type CommandHomeProps = Readonly<{
  loadHome?: (signal?: AbortSignal) => Promise<CommandHomeModel>;
}>;

type HomeLoadState =
  | Readonly<{ kind: 'loading' }>
  | Readonly<{ kind: 'error'; message: string }>
  | Readonly<{ kind: 'ready'; model: CommandHomeModel }>;

type HomePreferences = Readonly<{
  goals: boolean;
  context: boolean;
  evidence: boolean;
}>;

const defaultLoadHome = (signal?: AbortSignal) => loadCommandHome(commandApi, new Date(), signal);

function isAbortError(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'name' in error
    && error.name === 'AbortError';
}

export function CommandHome({ loadHome = defaultLoadHome }: CommandHomeProps) {
  const { replace } = useRouter();
  const searchParams = useSearchParams();
  const createToken = searchParams.get('create') ?? '';
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const refreshControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(false);
  const refreshIdRef = useRef(0);
  const [loadState, setLoadState] = useState<HomeLoadState>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [preferences, setPreferences] = useState<HomePreferences>({
    goals: true,
    context: true,
    evidence: true,
  });
  const [taskOpen, setTaskOpen] = useState(createToken === 'task');
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [taskPriority, setTaskPriority] = useState('normal');
  const [taskDueAt, setTaskDueAt] = useState('');
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskSaved, setTaskSaved] = useState(false);
  const [taskError, setTaskError] = useState('');

  useEffect(() => {
    if (createToken === 'task') setTaskOpen(true);
  }, [createToken]);

  useEffect(() => {
    const controller = new AbortController();
    const loadId = refreshIdRef.current + 1;
    refreshIdRef.current = loadId;
    void loadHome(controller.signal).then(
      (model) => {
        if (!controller.signal.aborted && refreshIdRef.current === loadId) {
          setLoadState({ kind: 'ready', model });
        }
      },
      (error: unknown) => {
        if (
          !controller.signal.aborted
          && refreshIdRef.current === loadId
          && !isAbortError(error)
        ) {
          setLoadState({
            kind: 'error',
            message: error instanceof Error ? error.message : 'Command Home is unavailable.',
          });
        }
      },
    );
    return () => {
      controller.abort();
    };
  }, [attempt, loadHome]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      refreshControllerRef.current?.abort();
    };
  }, []);

  function retryHome() {
    refreshControllerRef.current?.abort();
    setLoadState({ kind: 'loading' });
    setAttempt((current) => current + 1);
  }

  const openTask = useCallback(() => {
    setTaskError('');
    setTaskSaved(false);
    setTaskOpen(true);
  }, []);

  const closeTask = useCallback(() => {
    setTaskOpen(false);
    setTaskError('');
    replace('/admin/command', { scroll: false });
  }, [replace]);

  const changeTaskOpen = useCallback((open: boolean) => {
    if (!open) closeTask();
  }, [closeTask]);

  async function createTask() {
    if (!taskTitle.trim()) {
      setTaskError('Task title is required.');
      return;
    }
    setTaskSaving(true);
    setTaskError('');
    try {
      await commandApi.createTask({
        title: taskTitle.trim(),
        description: taskDescription.trim(),
        priority: taskPriority,
        contact_id: null,
        due_at: taskDueAt ? new Date(taskDueAt).toISOString() : null,
      });
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : 'Unable to create task.');
      setTaskSaving(false);
      return;
    }

    if (!mountedRef.current) return;
    setTaskSaved(true);
    refreshControllerRef.current?.abort();
    const refreshController = new AbortController();
    refreshControllerRef.current = refreshController;
    const refreshId = refreshIdRef.current + 1;
    refreshIdRef.current = refreshId;
    try {
      const refreshedModel = await loadHome(refreshController.signal);
      if (
        !mountedRef.current
        || refreshController.signal.aborted
        || refreshIdRef.current !== refreshId
      ) return;
      setLoadState({ kind: 'ready', model: refreshedModel });
      setTaskTitle('');
      setTaskDescription('');
      setTaskPriority('normal');
      setTaskDueAt('');
      closeTask();
    } catch (error) {
      if (
        !mountedRef.current
        || refreshController.signal.aborted
        || refreshIdRef.current !== refreshId
        || isAbortError(error)
      ) return;
      const detail = error instanceof Error ? ` ${error.message}` : '';
      setTaskError(`Task saved, but Home could not refresh.${detail}`);
    } finally {
      if (mountedRef.current && refreshControllerRef.current === refreshController) {
        setTaskSaving(false);
        refreshControllerRef.current = null;
      }
    }
  }

  function updateGoal(goal: Goal) {
    setLoadState((current) => current.kind === 'ready'
      ? {
          ...current,
          model: {
            ...current.model,
            goals: current.model.goals?.map((candidate) => candidate.id === goal.id ? goal : candidate) ?? null,
          },
        }
      : current);
  }

  function togglePreference(key: keyof HomePreferences) {
    setPreferences((current) => ({ ...current, [key]: !current[key] }));
  }

  const headerActions = (
    <>
      <button
        ref={createTriggerRef}
        type="button"
        className="command-primary-button command-touch-target"
        onClick={openTask}
      >
        Create task
      </button>
      <div className="command-home-customize">
        <button
          type="button"
          className="command-secondary-button command-touch-target"
          aria-label="Customize Home"
          aria-expanded={customizeOpen}
          onClick={() => setCustomizeOpen((open) => !open)}
        >
          Customize
        </button>
        {customizeOpen ? (
          <div className="command-home-customize-menu" role="group" aria-label="Home panel preferences">
            <label>
              <input
                type="checkbox"
                checked={preferences.goals}
                onChange={() => togglePreference('goals')}
              />
              Show goals
            </label>
            <label>
              <input
                type="checkbox"
                checked={preferences.context}
                onChange={() => togglePreference('context')}
              />
              Show context panels
            </label>
            <label>
              <input
                type="checkbox"
                checked={preferences.evidence}
                onChange={() => togglePreference('evidence')}
              />
              Show recovered evidence
            </label>
          </div>
        ) : null}
      </div>
    </>
  );

  return (
    <div className="command-home">
      <CommandModuleHeader
        breadcrumbs={[{ label: 'Internal CRM' }, { label: 'Home' }]}
        title="Welcome home, Brandon"
        description="Your next best actions across contacts, tasks, pipeline, and agreements."
        actions={headerActions}
      />
      {taskSaved && !taskOpen ? (
        <p
          className="command-sr-only"
          role="status"
          aria-label="Task creation status"
          aria-live="polite"
          aria-atomic="true"
        >
          Task saved
        </p>
      ) : null}

      <div className="command-home-body command-content-gutters">
        {loadState.kind === 'loading' ? (
          <div data-testid="home-loading-skeleton" className="command-home-loading">
            <CommandStatePanel
              kind="loading"
              title="Loading Command Home"
              message="Retrieving verified internal CRM regions."
            />
            <div className="command-home-loading-grid" aria-hidden="true">
              <span />
              <span />
              <span />
              <span />
            </div>
          </div>
        ) : loadState.kind === 'error' ? (
          <CommandStatePanel
            kind="error"
            title="Command Home unavailable"
            message={loadState.message}
            actionLabel="Retry Home"
            onAction={retryHome}
          />
        ) : (
          <>
            <HomeShortcutStrip shortcuts={loadState.model.shortcuts} />
            {Object.keys(loadState.model.regionErrors).length > 0 ? (
              <CommandStatePanel
                kind="error"
                title="Some Home data is unavailable"
                message="Available regions remain visible. Retry to refresh the unavailable regions."
                actionLabel="Retry unavailable regions"
                onAction={retryHome}
              />
            ) : null}
            <FollowUpReadinessHero
              readiness={loadState.model.readiness}
              nextActions={loadState.model.nextActions}
            />
            <HomeKpiStrip kpis={loadState.model.kpis} />
            <div className="command-home-columns">
              <div className="command-home-primary-column">
                <HomeTaskQueue
                  tasks={loadState.model.tasks}
                  errorMessage={loadState.model.regionErrors.tasks}
                  onCreateTask={openTask}
                />
                {preferences.goals ? (
                  <HomeGoals
                    goals={loadState.model.goals}
                    errorMessage={loadState.model.regionErrors.goals}
                    onGoalUpdated={updateGoal}
                  />
                ) : null}
              </div>
              {preferences.context ? <HomeContextPanels model={loadState.model} /> : null}
            </div>
            {preferences.evidence ? (
              <details className="command-home-recovered-evidence">
                <summary>Recovered dashboard evidence</summary>
                <p>
                  Captured placeholders are source evidence only; they are not presented as normalized contacts,
                  revenue, profit share, or lead-pool records.
                </p>
                {Object.keys(loadState.model.regionErrors).length > 0 ? (
                  <ul>
                    {Object.entries(loadState.model.regionErrors).map(([region, message]) => (
                      <li key={region}><strong>{region}</strong>: {message}</li>
                    ))}
                  </ul>
                ) : null}
              </details>
            ) : null}
          </>
        )}
      </div>

      <CommandOverlay
        open={taskOpen}
        labelledBy="command-home-create-task-heading"
        triggerRef={createToken === 'task' ? undefined : createTriggerRef}
        onOpenChange={changeTaskOpen}
      >
        <form
          className="command-home-task-form"
          onSubmit={(event) => {
            event.preventDefault();
            void createTask();
          }}
        >
          <h2 id="command-home-create-task-heading">Create task</h2>
          <label>
            Task title
            <input
              aria-label="Task title"
              value={taskTitle}
              onChange={(event) => setTaskTitle(event.target.value)}
            />
          </label>
          <label>
            Description
            <textarea
              aria-label="Task description"
              value={taskDescription}
              onChange={(event) => setTaskDescription(event.target.value)}
            />
          </label>
          <div className="command-home-form-grid">
            <label>
              Priority
              <select
                aria-label="Task priority"
                value={taskPriority}
                onChange={(event) => setTaskPriority(event.target.value)}
              >
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </select>
            </label>
            <label>
              Due date
              <input
                type="datetime-local"
                aria-label="Task due date"
                value={taskDueAt}
                onChange={(event) => setTaskDueAt(event.target.value)}
              />
            </label>
          </div>
          {taskError ? (
            <p role="alert" aria-live="assertive" aria-atomic="true" className="command-home-error-copy">
              {taskError}
            </p>
          ) : null}
          <div className="command-home-form-actions">
            <button type="button" className="command-secondary-button command-touch-target" onClick={closeTask}>
              Cancel
            </button>
            <button
              type="submit"
              className="command-primary-button command-touch-target"
              disabled={taskSaving || taskSaved}
            >
              {taskSaving ? 'Saving…' : taskSaved ? 'Task saved' : 'Save task'}
            </button>
          </div>
        </form>
      </CommandOverlay>
    </div>
  );
}
