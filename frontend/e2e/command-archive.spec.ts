import { expect, test } from './fixtures/command';

const bundle = {
  entry_type: 'artifact', id: 21, domain: 'docusign', path: 'docusign_full/download_bundles/Complete_with_DocuSign_2024_Lease_352_Mammot.zip',
  source_path: 'docusign_full/download_bundles/Complete_with_DocuSign_2024_Lease_352_Mammot.zip', filename: 'Complete_with_DocuSign_2024_Lease_352_Mammot.zip',
  artifact_type: 'zip', sha256: 'a'.repeat(64), size_bytes: 476918, download_available: true, content_kind: 'document_bundle',
};
const summary = { files: 169, folders: 11, document_bundles: 149, documents: 0, source_captures: 14, data_exports: 5, supporting_files: 1, unavailable_files: 0 };
const folder = (path: string, count: number) => ({ entry_type: 'folder', path, name: path.split('/').at(-1), file_count: count });

test('archive exposes imported folders and original PDF names without horizontal overflow', async ({ commandPage }, testInfo) => {
  await commandPage.route('**/api/v1/command/archive/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.searchParams.get('path') || '';
    const query = url.searchParams.get('query') || '';
    const members = url.pathname.endsWith('/members');
    const entries = members
      ? [{ entry_type: 'member', member_index: 0, path: '2024_Lease_352_Mammoth.pdf', filename: '2024_Lease_352_Mammoth.pdf', artifact_type: 'pdf', size_bytes: 43105, content_kind: 'document', download_available: true, unavailable_reason: null, unsafe_path: false }]
      : path === 'docusign_full/download_bundles' ? [bundle]
        : path === 'docusign_full' ? [folder('docusign_full/download_bundles', 148), folder('docusign_full/templates', 4)]
          : [folder('docusign', 4), folder('docusign_full', 164), folder('docusign_records', 1)];
    await route.fulfill({ json: { entries: query ? [] : entries, total: query ? 0 : entries.length, path, query, limit: 100, offset: 0, summary: members ? { ...summary, files: 1, folders: 0, documents: 1, document_bundles: 0, source_captures: 0, data_exports: 0, supporting_files: 0 } : summary, domains: { docusign: 169, kw_command: 6424 }, ...(members ? { bundle } : {}) } });
  });
  await commandPage.goto('/admin/command/archive');
  await expect(commandPage.getByRole('heading', { name: 'Recovered archive' })).toBeVisible();
  await commandPage.getByRole('button', { name: /^DocuSign/ }).click();
  await commandPage.getByRole('button', { name: 'Open folder docusign_full' }).click();
  await commandPage.getByRole('button', { name: 'Open folder download_bundles' }).click();
  await expect(commandPage.getByRole('button', { name: `Open bundle ${bundle.filename}` })).toBeVisible();
  await commandPage.evaluate(() => window.scrollTo(0, 0));
  await commandPage.screenshot({ path: testInfo.outputPath('archive-bundles.png'), fullPage: true, animations: 'disabled' });
  expect(await commandPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await commandPage.getByRole('button', { name: `Open bundle ${bundle.filename}` }).click();
  await expect(commandPage.getByRole('button', { name: 'Download 2024_Lease_352_Mammoth.pdf' })).toBeEnabled();
  await expect(commandPage.getByText('Original document', { exact: true })).toBeVisible();
  await commandPage.evaluate(() => window.scrollTo(0, 0));
  await commandPage.screenshot({ path: testInfo.outputPath('archive-pdfs.png'), fullPage: true, animations: 'disabled' });
  expect(await commandPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
