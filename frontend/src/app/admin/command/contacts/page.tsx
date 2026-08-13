import { ContactsWorkspace } from '@/components/command/ContactsWorkspace';
import { parseLegacyContactWorkspaceQuery } from '@/components/command/workspaceFilters';

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const view = parseLegacyContactWorkspaceQuery(await searchParams);
  return <ContactsWorkspace initialView={view.smart_view} />;
}
