import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { TaskSuggestionsWorkspace } from '@/components/command/TaskSuggestionsWorkspace';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const metadata: Metadata = {
  title: 'Task Review | SWS Command',
  referrer: 'no-referrer',
};

function selectedSuggestionId(value: string | string[] | undefined): string | null {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) return null;
  return value;
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const suggestionId = selectedSuggestionId(params.suggestion);
  const forbiddenQuerySecret = Object.keys(params).some((key) =>
    ['handoff', 'approval', 'token', 'nonce'].includes(key.toLowerCase()),
  );
  if (forbiddenQuerySecret) {
    const safeParams = new URLSearchParams({ approval_error: 'query_secret' });
    if (suggestionId !== null) safeParams.set('suggestion', suggestionId);
    redirect(`/admin/command/task-suggestions?${safeParams.toString()}`);
  }
  return (
    <TaskSuggestionsWorkspace
      initialSuggestionId={suggestionId}
      initialSecurityError={params.approval_error === 'query_secret' ? 'query_secret' : null}
    />
  );
}
