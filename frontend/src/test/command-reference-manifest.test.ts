import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  commandSourceReferences,
  resolveCommandVisualSourceManifest,
} from '../../e2e/visual/command-reference-manifest';

const originalManifest = process.env.COMMAND_VISUAL_SOURCE_MANIFEST;

const dimensions = {
  'contacts-list-live': [1800, 982],
  'contact-detail-live': [1793, 1166],
  'contact-opportunities-live': [1793, 1166],
  'contact-notes-live': [1793, 1166],
} as const;

function png(width: number, height: number): Buffer {
  const bytes = Buffer.alloc(24);
  Buffer.from('89504e470d0a1a0a', 'hex').copy(bytes, 0);
  bytes.write('IHDR', 12, 'ascii');
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return bytes;
}

function validPrivateFixture() {
  const directory = mkdtempSync(path.join(tmpdir(), 'command-private-manifest-'));
  const references: Record<string, { path: string; width: number; height: number }> = {};
  for (const [alias, [width, height]] of Object.entries(dimensions)) {
    const source = path.join(directory, `${alias}.png`);
    writeFileSync(source, png(width, height));
    references[alias] = { path: source, width, height };
  }
  const manifest = path.join(directory, 'manifest.json');
  writeFileSync(manifest, JSON.stringify({ schema_version: 1, references }));
  chmodSync(manifest, 0o600);
  return { directory, manifest, references };
}

afterEach(() => {
  if (originalManifest === undefined) delete process.env.COMMAND_VISUAL_SOURCE_MANIFEST;
  else process.env.COMMAND_VISUAL_SOURCE_MANIFEST = originalManifest;
});

describe('Command source visual manifest', () => {
  it('uses logical aliases and excludes incomplete, retry, and private contact-name targets', () => {
    const valid = commandSourceReferences.filter((item) => item.quality === 'valid');
    expect(valid.map((item) => item.filename)).toEqual(expect.arrayContaining([
      'contacts-list-live',
      'contact-detail-live',
      'contact-opportunities-live',
      'contact-notes-live',
    ]));
    const contactAliases = valid.filter((item) => item.alias).map((item) => item.filename).sort();
    expect(contactAliases).toEqual([
      'contact-detail-live', 'contact-notes-live', 'contact-opportunities-live', 'contacts-list-live',
    ]);
    expect(valid.some((item) => item.filename === 'contacts-list.png' || item.filename.endsWith('-retry.png'))).toBe(false);
  });

  it('limits masks to the four approved reasons', () => {
    const reasons = new Set(commandSourceReferences.flatMap((item) => item.brandMasks.map((mask) => mask.reason)));
    expect([...reasons]).toEqual(expect.arrayContaining([
      'source vendor mark',
      'source vendor utilities',
      'source account identity',
    ]));
    expect([...reasons].every((reason) => [
      'source vendor mark', 'source vendor utilities', 'source account identity', 'dynamic private text',
    ].includes(reason))).toBe(true);
  });

  it('keeps limitation captures explicit and out of valid targets', () => {
    const limitations = commandSourceReferences.filter((item) => item.quality === 'limitation');
    expect(limitations.map((item) => item.filename)).toEqual(expect.arrayContaining([
      'top-home.png', 'contacts-list.png', 'opportunities-board.png', 'smartplans-my.png',
      'referrals-dashboard-error-state.png', 'contacts-live-list-retry.png',
    ]));
  });

  it.each([
    undefined,
    'relative/private.json',
  ])('rejects missing or relative private manifest paths without echoing them', (manifest) => {
    if (manifest === undefined) delete process.env.COMMAND_VISUAL_SOURCE_MANIFEST;
    else process.env.COMMAND_VISUAL_SOURCE_MANIFEST = manifest;
    expect(() => resolveCommandVisualSourceManifest()).toThrow('Command visual source manifest rejected');
    try { resolveCommandVisualSourceManifest(); } catch (error) {
      expect(String(error)).not.toContain('relative/private.json');
    }
  });

  it('rejects an invalid schema without exposing its absolute manifest path', () => {
    const directory = mkdtempSync(path.join(tmpdir(), 'command-private-manifest-'));
    const manifest = path.join(directory, 'manifest.json');
    writeFileSync(manifest, JSON.stringify({ schema_version: 2, references: {} }));
    chmodSync(manifest, 0o600);
    process.env.COMMAND_VISUAL_SOURCE_MANIFEST = manifest;
    expect(() => resolveCommandVisualSourceManifest()).toThrow('manifest schema_version must be 1');
    try { resolveCommandVisualSourceManifest(); } catch (error) {
      expect(String(error)).not.toContain(manifest);
      expect(String(error)).not.toContain(path.basename(manifest));
    }
  });

  it('resolves all four exact aliases from a private access-controlled manifest', () => {
    const fixture = validPrivateFixture();
    const resolved = resolveCommandVisualSourceManifest(fixture.manifest);
    expect([...resolved.keys()].sort()).toEqual(Object.keys(dimensions).sort());
    expect(resolved.get('contacts-list-live')).toMatchObject({ width: 1800, height: 982 });
  });

  it('rejects duplicate keys, unknown aliases, and extra object keys', () => {
    const fixture = validPrivateFixture();
    const base = JSON.stringify({ schema_version: 1, references: fixture.references });
    writeFileSync(fixture.manifest, base.replace('"schema_version":1', '"schema_version":1,"schema_version":1'));
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('duplicate keys');
    writeFileSync(fixture.manifest, JSON.stringify({ schema_version: 1, references: { ...fixture.references, unknown: fixture.references['contacts-list-live'] } }));
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('aliases must exactly match');
    writeFileSync(fixture.manifest, JSON.stringify({ schema_version: 1, references: fixture.references, extra: true }));
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('invalid top-level keys');
    writeFileSync(fixture.manifest, JSON.stringify({ schema_version: 1, references: { ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], extra: true } } }));
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('contacts-list-live has invalid keys');
    writeFileSync(fixture.manifest, '{"schema_version":1,"references":');
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('strict JSON');
  });

  it('rejects manifest directories, symlinks, wrong extensions, and permissive modes', () => {
    const fixture = validPrivateFixture();
    expect(() => resolveCommandVisualSourceManifest(fixture.directory)).toThrow('regular non-symlink file');
    const link = path.join(fixture.directory, 'manifest-link.json');
    symlinkSync(fixture.manifest, link);
    expect(() => resolveCommandVisualSourceManifest(link)).toThrow('regular non-symlink file');
    const wrongExtension = path.join(fixture.directory, 'manifest.txt');
    writeFileSync(wrongExtension, '{}'); chmodSync(wrongExtension, 0o600);
    expect(() => resolveCommandVisualSourceManifest(wrongExtension)).toThrow('extension must be .json');
    chmodSync(fixture.manifest, 0o644);
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('permissions must exclude');
  });

  it('rejects nonabsolute, non-PNG, symlink, declared, and native source mismatches', () => {
    const fixture = validPrivateFixture();
    const write = (references: typeof fixture.references) => { writeFileSync(fixture.manifest, JSON.stringify({ schema_version: 1, references })); chmodSync(fixture.manifest, 0o600); };
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: 'relative.png' } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('absolute PNG');
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: path.join(fixture.directory, 'source.jpg') } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('absolute PNG');
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], width: 1 } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('declared dimensions');
    const badNative = path.join(fixture.directory, 'bad-native.png'); writeFileSync(badNative, png(1, 1));
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: badNative } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('PNG dimensions');
    const sourceLink = path.join(fixture.directory, 'source-link.png'); symlinkSync(fixture.references['contacts-list-live'].path, sourceLink);
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: sourceLink } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('regular non-symlink file');
    const sourceDirectory = path.join(fixture.directory, 'source-directory.png'); mkdirSync(sourceDirectory);
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: sourceDirectory } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('regular non-symlink file');
    const invalidPng = path.join(fixture.directory, 'invalid.png'); writeFileSync(invalidPng, 'not a png');
    write({ ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: invalidPng } });
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('valid PNG');
  });

  it('sanitizes checkout-root and source filesystem failures', () => {
    const fixture = validPrivateFixture();
    const privateCheckout = path.join(fixture.directory, 'operator-checkout-name');
    expect(() => resolveCommandVisualSourceManifest(fixture.manifest, privateCheckout)).toThrow('repository roots cannot be verified');
    try { resolveCommandVisualSourceManifest(fixture.manifest, privateCheckout); } catch (error) {
      expect(String(error)).not.toContain(privateCheckout);
      expect(String(error)).not.toContain('operator-checkout-name');
    }

    const unreadable = fixture.references['contacts-list-live'].path;
    chmodSync(unreadable, 0o000);
    try {
      expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('source cannot be read');
    } finally {
      chmodSync(unreadable, 0o600);
    }
  });

  it('rejects repository, public, artifact, and build roots without exposing private paths', () => {
    const fixture = validPrivateFixture();
    const forbidden = path.resolve(process.cwd(), 'artifacts/forbidden-source.png');
    mkdirSync(path.dirname(forbidden), { recursive: true });
    try {
      writeFileSync(forbidden, png(1800, 982));
      writeFileSync(fixture.manifest, JSON.stringify({ schema_version: 1, references: { ...fixture.references, 'contacts-list-live': { ...fixture.references['contacts-list-live'], path: forbidden } } }));
      chmodSync(fixture.manifest, 0o600);
      expect(() => resolveCommandVisualSourceManifest(fixture.manifest)).toThrow('forbidden root');
    } finally {
      rmSync(forbidden, { force: true });
    }
    try { resolveCommandVisualSourceManifest('/private/path/that-does-not-exist.json'); } catch (error) {
      expect(String(error)).not.toContain('that-does-not-exist');
      expect(String(error)).not.toContain('/private/path');
    }
  });
});
