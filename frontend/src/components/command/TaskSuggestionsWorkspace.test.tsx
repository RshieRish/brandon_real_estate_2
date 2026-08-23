import { StrictMode } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ApprovalPrepare,
  TaskSuggestion,
  TaskSuggestionList,
  TaskSuggestionPreview,
} from '@/lib/command/task-suggestions';
import { CommandHttpError } from '@/lib/command/http';
import AdminLoginPage from '@/app/admin/login/page';
import AdminLayout from '@/app/admin/layout';
import { installTaskSuggestionHandoffBootstrap } from '@/lib/command/task-suggestion-handoff';
import { TaskSuggestionsWorkspace } from './TaskSuggestionsWorkspace';

const navigationMocks = vi.hoisted(() => ({
  push: vi.fn(),
  search: '',
  pathname: '/admin/command/task-suggestions',
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: navigationMocks.push }),
  useSearchParams: () => new URLSearchParams(navigationMocks.search),
  usePathname: () => navigationMocks.pathname,
}));

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  edit: vi.fn(),
  preview: vi.fn(),
  prepareApproval: vi.fn(),
  exchangeHandoff: vi.fn(),
  approve: vi.fn(),
  dismiss: vi.fn(),
  consumeHandoff: vi.fn(),
}));

vi.mock('@/lib/command/task-suggestions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/command/task-suggestions')>();
  return {
    ...actual,
    consumeTaskSuggestionHandoffBootstrap: apiMocks.consumeHandoff,
    taskSuggestionsApi: {
      list: apiMocks.list,
      get: apiMocks.get,
      edit: apiMocks.edit,
      preview: apiMocks.preview,
      prepareApproval: apiMocks.prepareApproval,
      exchangeHandoff: apiMocks.exchangeHandoff,
      approve: apiMocks.approve,
      dismiss: apiMocks.dismiss,
    },
  };
});

const suggestionId = '11111111-1111-4111-8111-111111111111';
const payloadHash = 'a'.repeat(64);
const approvalToken = `${'B'.repeat(42)}A`;

const suggestion: TaskSuggestion = {
  id: suggestionId,
  source_type: 'gmail_message',
  title: 'Send Jane the disclosure package',
  description: 'Jane requested the signed disclosure package.',
  priority: 'high',
  due_at: '2026-08-25T14:00:00Z',
  contact_id: 41,
  status: 'open',
  state: 'pending_review',
  clarification_state: 'not_required',
  blocker_codes: [],
  resolution_requirements: [],
  confidence: 0.94,
  rationale: 'The message explicitly requests a disclosure follow-up.',
  model_schema_version: 'gmail-task-v1',
  sources: [{
    direction: 'received',
    source_label: `gmail:received:${'1'.repeat(32)}`,
    created_at: '2026-08-22T12:00:00Z',
  }],
  audit_trail: [{
    suggestion_version: 7,
    event_type: 'edit',
    actor_type: 'command_admin',
    action_audited: true,
    created_at: '2026-08-22T12:04:00Z',
  }],
  payload_hash: payloadHash,
  version: 7,
  applied_task_id: null,
  created_at: '2026-08-22T12:00:00Z',
  updated_at: '2026-08-22T12:05:00Z',
};

const preview: TaskSuggestionPreview = {
  suggestion_id: suggestionId,
  suggestion_version: 7,
  payload_hash: payloadHash,
  task: {
    title: suggestion.title,
    description: suggestion.description,
    priority: suggestion.priority,
    due_at: suggestion.due_at,
    contact_id: suggestion.contact_id,
    status: 'open',
  },
};

const prepared: ApprovalPrepare = {
  ...preview,
  approval: approvalToken,
  expires_at: '2026-08-22T12:10:00Z',
};

const appliedSuggestion: TaskSuggestion = {
  ...suggestion,
  state: 'applied',
  blocker_codes: [],
  resolution_requirements: [],
  version: 8,
  applied_task_id: 91,
  audit_trail: [
    {
      suggestion_version: 8,
      event_type: 'apply',
      actor_type: 'command_admin',
      action_audited: true,
      created_at: '2026-08-22T12:06:00Z',
    },
    {
      suggestion_version: 7,
      event_type: 'approve',
      actor_type: 'command_admin',
      action_audited: true,
      created_at: '2026-08-22T12:06:00Z',
    },
  ],
};

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<Value>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function listOf(...suggestions: TaskSuggestion[]): TaskSuggestionList {
  return { suggestions };
}

function renderWorkspace(initialSuggestionId: string | null = null) {
  return render(<TaskSuggestionsWorkspace initialSuggestionId={initialSuggestionId} />);
}

describe('TaskSuggestionsWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('admin_token', 'admin-test-token');
    apiMocks.consumeHandoff.mockReturnValue({
      handoff: null,
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    apiMocks.list.mockResolvedValue(listOf(suggestion));
    apiMocks.get.mockResolvedValue(suggestion);
    apiMocks.edit.mockResolvedValue(suggestion);
    apiMocks.preview.mockResolvedValue(preview);
    apiMocks.prepareApproval.mockResolvedValue(prepared);
    apiMocks.exchangeHandoff.mockResolvedValue(prepared);
    apiMocks.approve.mockResolvedValue({
      suggestion_id: suggestionId,
      suggestion_version: 8,
      task_id: 91,
      request_id: '22222222-2222-4222-8222-222222222222',
      replayed: false,
    });
    apiMocks.dismiss.mockResolvedValue({
      ...suggestion,
      state: 'dismissed',
      version: 8,
    });
    navigationMocks.search = '';
    navigationMocks.pathname = '/admin/command/task-suggestions';
  });

  it('renders a loading skeleton and then the empty state', async () => {
    const pending = deferred<TaskSuggestionList>();
    apiMocks.list.mockReturnValueOnce(pending.promise);
    renderWorkspace();

    expect(screen.getByRole('status', { name: 'Loading task suggestions' })).toBeInTheDocument();
    await act(async () => pending.resolve(listOf()));

    expect(await screen.findByText('Review queue is clear')).toBeInTheDocument();
  });

  it('renders a retryable error state and restores focus after a successful retry', async () => {
    apiMocks.list
      .mockRejectedValueOnce(new Error('Synthetic queue failure'))
      .mockResolvedValueOnce(listOf(suggestion));
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByRole('alert')).toHaveTextContent('Task suggestions unavailable');
    const retry = screen.getByRole('button', { name: 'Try again' });
    await user.click(retry);

    expect(await screen.findByRole('heading', { name: suggestion.title })).toHaveFocus();
  });

  it('shows the review ledger, structured fields, provenance, and payload hash', async () => {
    renderWorkspace();

    expect(await screen.findByRole('heading', { name: suggestion.title })).toBeInTheDocument();
    expect(screen.getAllByText('Gmail review').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByLabelText('Task title')).toHaveValue(suggestion.title);
    expect(screen.getByLabelText('Task description')).toHaveValue(suggestion.description);
    expect(screen.getByLabelText('Priority')).toHaveValue('high');
    expect(screen.getByLabelText('Contact ID')).toHaveValue(41);
    expect(screen.getAllByText(payloadHash).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('94% confidence')).toBeInTheDocument();
    expect(screen.getByText(`gmail:received:${'1'.repeat(32)}`)).toBeInTheDocument();
    expect(screen.getByText('No required fields missing')).toBeInTheDocument();
    expect(screen.getByText('Edited by Command admin')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeEnabled();
  });

  it('blocks invalid or unsaved edits from preview and approval', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });

    await user.clear(screen.getByLabelText('Task title'));
    expect(screen.getByLabelText('Task title')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Enter a task title.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save review changes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Preview final task' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeDisabled();

    await user.type(screen.getByLabelText('Task title'), 'Updated disclosure follow-up');
    await user.clear(screen.getByLabelText('Contact ID'));
    await user.type(screen.getByLabelText('Contact ID'), '1.5');
    expect(screen.getByLabelText('Contact ID')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Use a whole-number Contact ID from 1 to 2147483647.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save review changes' })).toBeDisabled();

    await user.clear(screen.getByLabelText('Contact ID'));
    await user.type(screen.getByLabelText('Contact ID'), '42');
    expect(screen.getByRole('button', { name: 'Save review changes' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Preview final task' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeDisabled();
  });

  it('distinguishes a pending Sydney question from timed-out manual review', async () => {
    const pendingQuestion: TaskSuggestion = {
      ...suggestion,
      state: 'needs_clarification',
      clarification_state: 'pending',
      blocker_codes: ['ambiguous_due_at'],
    };
    const timedOut: TaskSuggestion = {
      ...suggestion,
      id: '33333333-3333-4333-8333-333333333333',
      title: 'Confirm the inspection response',
      state: 'needs_clarification',
      clarification_state: 'timed_out',
      blocker_codes: ['ambiguous_contact'],
    };
    apiMocks.list.mockResolvedValueOnce(listOf(pendingQuestion, timedOut));
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByText('Sydney question pending')).toBeInTheDocument();
    expect(screen.getByText('Waiting for Sydney clarification')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: `Review ${timedOut.title}` }));
    expect(await screen.findByText('Clarification timed out')).toBeInTheDocument();
    expect(screen.getByText(/manual review/i)).toBeInTheDocument();
  });

  it('requires explicit owner, unsupported-link, detail, action, and duplicate resolutions', async () => {
    const blocked: TaskSuggestion = {
      ...suggestion,
      state: 'possible_duplicate',
      clarification_state: 'manual_review_required',
      blocker_codes: [
        'missing_required_field',
        'multiple_actions',
        'unsupported_owner',
        'unsupported_link',
      ],
      resolution_requirements: [
        'resolve_owner_as_brandon',
        'create_without_unsupported_link',
        'accept_current_task_details',
        'treat_as_single_action',
        'confirm_not_duplicate',
      ],
    };
    apiMocks.list.mockResolvedValueOnce(listOf(blocked));
    apiMocks.edit.mockResolvedValueOnce({
      ...blocked,
      state: 'pending_review',
      clarification_state: 'not_required',
      blocker_codes: [],
      resolution_requirements: [],
      version: 8,
      payload_hash: 'c'.repeat(64),
    });
    const confirm = vi.spyOn(window, 'confirm');
    const prompt = vi.spyOn(window, 'prompt');
    const user = userEvent.setup();
    renderWorkspace();

    await screen.findByRole('heading', { name: blocked.title });
    await user.click(screen.getByLabelText('Assign this task to Brandon'));
    await user.click(screen.getByLabelText('Create without the unsupported linked record'));
    await user.click(screen.getByLabelText('Accept the current task details'));
    await user.click(screen.getByLabelText('Treat this as one task'));
    await user.click(screen.getByLabelText('Confirm this is not a duplicate'));
    await user.click(screen.getByRole('button', { name: 'Save review changes' }));

    await waitFor(() =>
      expect(apiMocks.edit).toHaveBeenCalledWith(suggestionId, {
        expected_version: 7,
        expected_payload_hash: payloadHash,
        resolve_owner_as_brandon: true,
        create_without_unsupported_link: true,
        accept_current_task_details: true,
        treat_as_single_action: true,
        confirm_not_duplicate: true,
      }),
    );
    expect(await screen.findByText('Review changes saved')).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    expect(prompt).not.toHaveBeenCalled();
  });

  it('offers the owner decision, not task-detail acceptance, for owner ambiguity', async () => {
    const ownerAmbiguous: TaskSuggestion = {
      ...suggestion,
      state: 'needs_clarification',
      clarification_state: 'manual_review_required',
      blocker_codes: ['missing_required_field'],
      resolution_requirements: ['resolve_owner_as_brandon'],
    };
    apiMocks.list.mockResolvedValueOnce(listOf(ownerAmbiguous));
    apiMocks.edit.mockResolvedValueOnce({
      ...ownerAmbiguous,
      state: 'pending_review',
      clarification_state: 'not_required',
      blocker_codes: [],
      resolution_requirements: [],
      version: 8,
      payload_hash: 'd'.repeat(64),
    });
    const user = userEvent.setup();
    renderWorkspace();

    await screen.findByRole('heading', { name: ownerAmbiguous.title });
    expect(screen.getByLabelText('Assign this task to Brandon')).toBeInTheDocument();
    expect(screen.queryByLabelText('Accept the current task details')).not.toBeInTheDocument();
    await user.click(screen.getByLabelText('Assign this task to Brandon'));
    await user.click(screen.getByRole('button', { name: 'Save review changes' }));

    await waitFor(() => expect(apiMocks.edit).toHaveBeenCalledWith(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
      resolve_owner_as_brandon: true,
    }));
  });

  it('blocks approval when a late duplicate requires a version-bound confirmation', async () => {
    const lateDuplicate: TaskSuggestion = {
      ...suggestion,
      state: 'pending_review',
      blocker_codes: [],
      resolution_requirements: ['confirm_not_duplicate'],
    };
    apiMocks.list.mockResolvedValueOnce(listOf(lateDuplicate));
    const user = userEvent.setup();
    renderWorkspace();

    await screen.findByRole('heading', { name: lateDuplicate.title });
    expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeDisabled();
    await user.click(screen.getByLabelText('Confirm this is not a duplicate'));
    expect(screen.getByRole('button', { name: 'Save review changes' })).toBeEnabled();
  });

  it('shows an exact preview, prepares separately, and creates only on the later Approve click', async () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(
      '22222222-2222-4222-8222-222222222222',
    );
    apiMocks.get.mockResolvedValueOnce(appliedSuggestion);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });

    await user.click(screen.getByRole('button', { name: 'Preview final task' }));
    expect(await screen.findByRole('heading', { name: 'Final task preview' })).toBeInTheDocument();
    expect(screen.getAllByText(payloadHash).length).toBeGreaterThanOrEqual(2);
    expect(apiMocks.approve).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Prepare approval' }));

    expect(await screen.findByText('Approval prepared')).toBeInTheDocument();
    expect(apiMocks.prepareApproval).toHaveBeenCalledWith(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
    });
    expect(apiMocks.approve).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Approve task' }));

    await waitFor(() => expect(apiMocks.approve).toHaveBeenCalledTimes(1));
    expect(apiMocks.approve).toHaveBeenCalledWith(
      suggestionId,
      expect.objectContaining({
        approval: approvalToken,
        request_id: '22222222-2222-4222-8222-222222222222',
      }),
    );
    expect(apiMocks.get).toHaveBeenCalledWith(suggestionId);
    const success = await screen.findByText('Task 91 created');
    await waitFor(() => expect(success).toHaveFocus());
    expect(screen.getByText('Applied to CRM by Command admin')).toBeInTheDocument();
    expect(screen.getByText('Approved by Command admin')).toBeInTheDocument();
  });

  it('locks the applied row and clears stale audit provenance when the post-approval read fails', async () => {
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(
      '22222222-2222-4222-8222-222222222222',
    );
    apiMocks.get.mockRejectedValueOnce(new TypeError('Synthetic refresh failure'));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });
    await user.click(screen.getByRole('button', { name: 'Prepare approval' }));
    await user.click(await screen.findByRole('button', { name: 'Approve task' }));

    expect(await screen.findByText('Task 91 created')).toBeInTheDocument();
    expect(screen.getByText('No review mutations recorded yet.')).toBeInTheDocument();
    expect(screen.queryByText('Edited by Command admin')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Task title')).toBeDisabled();
  });

  it('reuses the prepared approval request ID after a lost approval response', async () => {
    const randomUUID = vi.spyOn(crypto, 'randomUUID').mockReturnValue(
      '22222222-2222-4222-8222-222222222222',
    );
    apiMocks.approve
      .mockRejectedValueOnce(new TypeError('Synthetic lost response'))
      .mockResolvedValueOnce({
        suggestion_id: suggestionId,
        suggestion_version: 8,
        task_id: 91,
        request_id: '22222222-2222-4222-8222-222222222222',
        replayed: true,
      });
    apiMocks.get.mockResolvedValueOnce(appliedSuggestion);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });
    await user.click(screen.getByRole('button', { name: 'Prepare approval' }));
    const approve = await screen.findByRole('button', { name: 'Approve task' });

    await user.click(approve);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    await user.click(approve);

    await waitFor(() => expect(apiMocks.approve).toHaveBeenCalledTimes(2));
    expect(apiMocks.approve.mock.calls[0]?.[1].request_id).toBe(
      apiMocks.approve.mock.calls[1]?.[1].request_id,
    );
    expect(randomUUID).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Task 91 created')).toBeInTheDocument();
  });

  it('keeps queue selection locked while approval preparation is in flight', async () => {
    const second = {
      ...suggestion,
      id: '33333333-3333-4333-8333-333333333333',
      title: 'Schedule the inspection follow-up',
      payload_hash: 'e'.repeat(64),
    };
    const pending = deferred<ApprovalPrepare>();
    apiMocks.list.mockResolvedValueOnce(listOf(suggestion, second));
    apiMocks.prepareApproval.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });

    await user.click(screen.getByRole('button', { name: 'Prepare approval' }));
    expect(screen.getByRole('button', { name: `Review ${second.title}` })).toBeDisabled();
    await act(async () => pending.resolve(prepared));
    expect(await screen.findByText('Approval prepared')).toBeInTheDocument();
  });

  it('refetches a stale suggestion and focuses the changed-server notice', async () => {
    const fresh = {
      ...suggestion,
      title: 'Send Jane the revised disclosure package',
      version: 8,
      payload_hash: 'd'.repeat(64),
    };
    apiMocks.edit.mockRejectedValueOnce(new CommandHttpError(409, 'suggestion_stale'));
    apiMocks.get.mockResolvedValueOnce(fresh);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });
    await user.clear(screen.getByLabelText('Task title'));
    await user.type(screen.getByLabelText('Task title'), 'My local edit');
    await user.click(screen.getByRole('button', { name: 'Save review changes' }));

    const notice = await screen.findByText('This suggestion changed elsewhere. Review the fresh version.');
    await waitFor(() => expect(notice).toHaveFocus());
    expect(screen.getByLabelText('Task title')).toHaveValue(fresh.title);
    expect(apiMocks.get).toHaveBeenCalledWith(suggestionId);
  });

  it('discards a prepared approval when a stale save refetches server state', async () => {
    const fresh = {
      ...suggestion,
      title: 'Send Jane the server-approved package',
      version: 8,
      payload_hash: 'd'.repeat(64),
    };
    apiMocks.edit.mockRejectedValueOnce(new CommandHttpError(409, 'suggestion_stale'));
    apiMocks.get.mockResolvedValueOnce(fresh);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });
    await user.click(screen.getByRole('button', { name: 'Prepare approval' }));
    expect(await screen.findByRole('button', { name: 'Approve task' })).toBeInTheDocument();

    await user.clear(screen.getByLabelText('Task title'));
    await user.type(screen.getByLabelText('Task title'), 'My stale local edit');
    await user.click(screen.getByRole('button', { name: 'Save review changes' }));

    expect(await screen.findByText('This suggestion changed elsewhere. Review the fresh version.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve task' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Final task preview' })).not.toBeInTheDocument();
  });

  it('dismisses only after a bounded reason and moves focus back to the queue', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });
    expect(screen.getByRole('button', { name: 'Dismiss suggestion' })).toBeDisabled();
    await user.type(screen.getByLabelText('Dismissal reason'), 'Already handled by Brandon');
    await user.click(screen.getByRole('button', { name: 'Dismiss suggestion' }));

    await waitFor(() =>
      expect(apiMocks.dismiss).toHaveBeenCalledWith(suggestionId, {
        expected_version: 7,
        expected_payload_hash: payloadHash,
        reason: 'Already handled by Brandon',
      }),
    );
    expect(await screen.findByText('Suggestion dismissed')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Review queue' })).toHaveFocus();
  });

  it('exchanges a captured handoff once, retains only stage two in memory, and still requires Approve', async () => {
    const handoff = 'A'.repeat(43);
    apiMocks.consumeHandoff.mockReturnValueOnce({
      handoff,
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    renderWorkspace(suggestionId);

    expect(await screen.findByText('Sydney handoff verified')).toBeInTheDocument();
    expect(apiMocks.exchangeHandoff).toHaveBeenCalledWith(suggestionId, {
      expected_version: 7,
      expected_payload_hash: payloadHash,
      handoff,
    });
    expect(apiMocks.exchangeHandoff).toHaveBeenCalledTimes(1);
    expect(apiMocks.prepareApproval).not.toHaveBeenCalled();
    expect(apiMocks.approve).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain(handoff);
    expect(document.body.textContent).not.toContain(approvalToken);
  });

  it('survives React Strict Mode effect replay without losing or reusing the handoff', async () => {
    const handoff = 'A'.repeat(43);
    apiMocks.consumeHandoff.mockReturnValueOnce({
      handoff,
      invalid_query_secret: false,
      invalid_handoff: false,
    });

    render(
      <StrictMode>
        <TaskSuggestionsWorkspace initialSuggestionId={suggestionId} />
      </StrictMode>,
    );

    expect(await screen.findByText('Sydney handoff verified')).toBeInTheDocument();
    expect(apiMocks.consumeHandoff).toHaveBeenCalledTimes(1);
    expect(apiMocks.exchangeHandoff).toHaveBeenCalledTimes(1);
  });

  it('fails closed before network for query secrets or an unauthenticated handoff', async () => {
    apiMocks.consumeHandoff.mockReturnValueOnce({
      handoff: null,
      invalid_query_secret: true,
      invalid_handoff: false,
    });
    const first = renderWorkspace(suggestionId);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Approval secrets are not accepted in the query string',
    );
    expect(apiMocks.list).not.toHaveBeenCalled();
    first.unmount();

    vi.clearAllMocks();
    localStorage.clear();
    apiMocks.consumeHandoff.mockReturnValueOnce({
      handoff: 'A'.repeat(43),
      invalid_query_secret: false,
      invalid_handoff: false,
    });
    renderWorkspace(suggestionId);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sign in, then reopen the unused Sydney link',
    );
    expect(apiMocks.list).not.toHaveBeenCalled();
    expect(apiMocks.exchangeHandoff).not.toHaveBeenCalled();
  });

  it('supports keyboard queue selection and moves focus to the selected review', async () => {
    const second = {
      ...suggestion,
      id: '33333333-3333-4333-8333-333333333333',
      title: 'Schedule the inspection follow-up',
      payload_hash: 'e'.repeat(64),
    };
    apiMocks.list.mockResolvedValueOnce(listOf(suggestion, second));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByRole('heading', { name: suggestion.title });

    const queue = screen.getByRole('region', { name: 'Task suggestion queue' });
    const secondButton = within(queue).getByRole('button', { name: `Review ${second.title}` });
    secondButton.focus();
    await user.keyboard('{Enter}');

    const secondHeading = await screen.findByRole('heading', { name: second.title });
    await waitFor(() => expect(secondHeading).toHaveFocus());
  });

  it.each(['approved', 'dismissed', 'applied', 'failed'] as const)(
    'locks mutation controls for the terminal %s state',
    async (state) => {
      apiMocks.list.mockResolvedValueOnce(listOf({ ...suggestion, state }));
      renderWorkspace();

      await screen.findByRole('heading', { name: suggestion.title });
      expect(screen.getByLabelText('Task title')).toBeDisabled();
      expect(screen.getByLabelText('Task description')).toBeDisabled();
      expect(screen.getByLabelText('Priority')).toBeDisabled();
      expect(screen.getByLabelText('Due date and time')).toBeDisabled();
      expect(screen.getByLabelText('Contact ID')).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Save review changes' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Preview final task' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Prepare approval' })).toBeDisabled();
      expect(screen.queryByRole('heading', { name: 'Dismiss suggestion' })).not.toBeInTheDocument();
    },
  );

  it('explains that an unauthenticated handoff remains unused after login redirect', () => {
    navigationMocks.search = 'approval_notice=reopen_task_handoff';
    render(<AdminLoginPage />);

    expect(screen.getByRole('status')).toHaveTextContent(
      'Sign in, then reopen the unused Sydney task link. The link was not exchanged.',
    );
  });

  it('preserves the reopen-link notice when a stored admin token is expired', async () => {
    localStorage.setItem('admin_token', 'expired-admin-token');
    window.history.replaceState(
      {},
      '',
      `/admin/command/task-suggestions?suggestion=${suggestionId}#handoff=${'A'.repeat(43)}`,
    );
    installTaskSuggestionHandoffBootstrap(window);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(null, { status: 401 }));

    render(<AdminLayout><div>Protected review</div></AdminLayout>);

    await waitFor(() => expect(navigationMocks.push).toHaveBeenCalledWith(
      '/admin/login?approval_notice=reopen_task_handoff',
    ));
    expect(localStorage.getItem('admin_token')).toBeNull();
  });
});
