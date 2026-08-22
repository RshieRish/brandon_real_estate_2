import { installTaskSuggestionHandoffBootstrap } from './lib/command/task-suggestion-handoff';
import type { TaskSuggestionHandoffBootstrapMetadata } from './lib/command/task-suggestion-handoff';

const LOGIN_REOPEN_NOTICE = '/admin/login?approval_notice=reopen_task_handoff';

export function initializeTaskSuggestionHandoff(
  target: Window,
  redirect: (destination: string) => void = (destination) => target.location.replace(destination),
): TaskSuggestionHandoffBootstrapMetadata | null {
  if (target.location.pathname !== '/admin/command/task-suggestions') return null;
  const metadata = installTaskSuggestionHandoffBootstrap(target);
  let adminToken: string | null = null;
  try {
    adminToken = target.localStorage.getItem('admin_token');
  } catch {
    adminToken = null;
  }
  if (metadata.has_handoff && !adminToken?.trim()) redirect(LOGIN_REOPEN_NOTICE);
  return metadata;
}

initializeTaskSuggestionHandoff(window);
