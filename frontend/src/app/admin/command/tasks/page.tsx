import { TasksWorkspace } from '@/components/command/TasksWorkspace';
import { parseTaskWorkspaceQuery } from '@/components/command/workspaceFilters';

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <TasksWorkspace initialView={parseTaskWorkspaceQuery(await searchParams)} />;
}
