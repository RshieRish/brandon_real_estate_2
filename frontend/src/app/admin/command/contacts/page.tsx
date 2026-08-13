import { ContactsWorkspace } from '@/components/command/ContactsWorkspace';
import { parseContactWorkspaceQuery } from '@/components/command/workspaceFilters';

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <ContactsWorkspace initialView={parseContactWorkspaceQuery(await searchParams)} />;
}
