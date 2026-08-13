import { lstatSync, readFileSync, realpathSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

export type CommandReferenceQuality = 'valid' | 'limitation';
export type CommandReferenceAlias =
  | 'contacts-list-live'
  | 'contact-detail-live'
  | 'contact-opportunities-live'
  | 'contact-notes-live';

export type SourceBrandMask = Readonly<{
  x: number;
  y: number;
  width: number;
  height: number;
  reason: 'source vendor mark' | 'source vendor utilities' | 'source account identity' | 'dynamic private text';
}>;

export type CommandSourceReference = Readonly<{
  filename: string;
  alias?: CommandReferenceAlias;
  route: string;
  width: number;
  height: number;
  quality: CommandReferenceQuality;
  observedState: string;
  brandMasks: readonly SourceBrandMask[];
}>;

export type ResolvedCommandReference = Readonly<{
  alias: CommandReferenceAlias;
  sourcePath: string;
  width: number;
  height: number;
}>;

const shellBrandMasks: readonly SourceBrandMask[] = Object.freeze([
  { x: 0, y: 0, width: 80, height: 64, reason: 'source vendor mark' },
  { x: 1180, y: 0, width: 180, height: 64, reason: 'source vendor utilities' },
  { x: 1430, y: 0, width: 290, height: 64, reason: 'source account identity' },
]);

const CONTACT_ALIASES: Readonly<Record<CommandReferenceAlias, Readonly<{ width: number; height: number }>>> = {
  'contacts-list-live': { width: 1800, height: 982 },
  'contact-detail-live': { width: 1793, height: 1166 },
  'contact-opportunities-live': { width: 1793, height: 1166 },
  'contact-notes-live': { width: 1793, height: 1166 },
};

function rendered(filename: string, route: string, width = 1800, height = 982, observedState = 'authenticated rendered module view', alias?: CommandReferenceAlias): CommandSourceReference {
  return { filename, alias, route, width, height, quality: 'valid', observedState, brandMasks: shellBrandMasks };
}

function limitation(filename: string, route: string, width = 1800, height = 982, observedState = 'blank, incomplete, retry, or error capture; never a visual target'): CommandSourceReference {
  return { filename, route, width, height, quality: 'limitation', observedState, brandMasks: shellBrandMasks };
}

export const commandSourceReferences: readonly CommandSourceReference[] = Object.freeze([
  rendered('command-home-live.png', '/admin/command', 1800, 2249, 'authenticated full Home with persistent shell'),
  rendered('contacts-list-live', '/admin/command/contacts', 1800, 982, 'contacts list with toolbar, rows, and pagination', 'contacts-list-live'),
  rendered('tasks-to-do-live.png', '/admin/command/tasks?tab=todo', 1800, 982, 'To Do tasks with filters and dense rows'),
  rendered('smartplans-live-current.png', '/admin/command/smart-plans', 1800, 982, 'Smart Plans list with notice, tabs, and evidence count'),
  rendered('opportunities-live-current.png', '/admin/command/opportunities', 1800, 982, 'opportunity phase board and module tabs'),
  rendered('marketing-dashboard-live.png', '/admin/command/marketing', 1800, 982, 'marketing dashboard with nested module tabs'),
  rendered('referrals-dashboard-live.png', '/admin/command/referrals', 1800, 982, 'referrals dashboard with rendered network state'),
  rendered('contact-detail-live', '/admin/command/contacts/:id', 1793, 1166, 'split contact detail canvas with sticky navigation', 'contact-detail-live'),
  rendered('contact-opportunities-live', '/admin/command/contacts/:id?contact_view=opportunities', 1793, 1166, 'contact Opportunities panel', 'contact-opportunities-live'),
  rendered('contact-notes-live', '/admin/command/contacts/:id?contact_view=notes', 1793, 1166, 'contact Notes panel', 'contact-notes-live'),
  limitation('top-home.png', '/admin/command', 1800, 982, 'top-only shell capture without valid Home content'),
  limitation('contacts-list.png', '/admin/command/contacts', 1800, 982, 'incomplete contacts capture'),
  limitation('opportunities-board.png', '/admin/command/opportunities', 1800, 982, 'incomplete opportunity board capture'),
  limitation('smartplans-my.png', '/admin/command/smart-plans', 1800, 982, 'incomplete Smart Plans capture'),
  limitation('referrals-dashboard-error-state.png', '/admin/command/referrals', 1800, 982, 'rendered referral error state'),
  limitation('contacts-live-list-retry.png', '/admin/command/contacts', 1793, 1063, 'retry capture'),
  limitation('listings-live-retry.png', '/admin/command/listings', 1800, 982, 'retry capture'),
  limitation('websites-live-retry.png', '/admin/command/websites', 1800, 982, 'retry capture'),
]);

function privateManifestError(reason: string): never {
  throw new Error(`Command visual source manifest rejected: ${reason}`);
}

function regularNonSymlink(filePath: string, label: string): string {
  let stat: ReturnType<typeof lstatSync> | undefined;
  try { stat = lstatSync(filePath, { throwIfNoEntry: false }); } catch { privateManifestError(`${label} cannot be inspected`); }
  if (!stat || stat.isSymbolicLink() || !stat.isFile()) privateManifestError(`${label} must be a regular non-symlink file`);
  try { return realpathSync(filePath); } catch { return privateManifestError(`${label} cannot be resolved`); }
}

function inside(candidate: string, root: string): boolean {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function pngDimensions(filePath: string): Readonly<{ width: number; height: number }> {
  let bytes: Buffer;
  try { bytes = readFileSync(filePath); } catch { return privateManifestError('source cannot be read'); }
  if (bytes.length < 24 || bytes.toString('hex', 0, 8) !== '89504e470d0a1a0a' || bytes.toString('ascii', 12, 16) !== 'IHDR') privateManifestError('source must be a valid PNG');
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

function strictJson(text: string): unknown {
  let index = 0;
  const whitespace = () => { while (/\s/.test(text[index] ?? '')) index += 1; };
  const string = (): string => {
    const start = index;
    if (text[index++] !== '"') privateManifestError('manifest must contain strict JSON');
    while (index < text.length) {
      if (text[index] === '\\') index += 2;
      else if (text[index++] === '"') {
        try { return JSON.parse(text.slice(start, index)) as string; } catch { return privateManifestError('manifest must contain strict JSON'); }
      }
    }
    return privateManifestError('manifest must contain strict JSON');
  };
  const value = (): unknown => {
    whitespace();
    if (text[index] === '"') return string();
    if (text[index] === '{') {
      index += 1; whitespace();
      const object: Record<string, unknown> = {};
      const keys = new Set<string>();
      if (text[index] === '}') { index += 1; return object; }
      while (true) {
        whitespace(); const key = string();
        if (keys.has(key)) privateManifestError('manifest contains duplicate keys');
        keys.add(key); whitespace();
        if (text[index++] !== ':') privateManifestError('manifest must contain strict JSON');
        object[key] = value(); whitespace();
        const delimiter = text[index++];
        if (delimiter === '}') return object;
        if (delimiter !== ',') privateManifestError('manifest must contain strict JSON');
      }
    }
    if (text[index] === '[') {
      index += 1; whitespace(); const result: unknown[] = [];
      if (text[index] === ']') { index += 1; return result; }
      while (true) {
        result.push(value()); whitespace(); const delimiter = text[index++];
        if (delimiter === ']') return result;
        if (delimiter !== ',') privateManifestError('manifest must contain strict JSON');
      }
    }
    const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(index));
    if (!match) privateManifestError('manifest must contain strict JSON');
    index += match[0].length;
    return JSON.parse(match[0]);
  };
  const result = value(); whitespace();
  if (index !== text.length) privateManifestError('manifest must contain strict JSON');
  return result;
}

function repositoryRoots(checkoutRoot: string): readonly string[] {
  const roots = new Set<string>();
  try {
    roots.add(realpathSync(checkoutRoot));
    const output = execFileSync('git', ['worktree', 'list', '--porcelain'], { cwd: checkoutRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    for (const line of output.split('\n')) if (line.startsWith('worktree ')) roots.add(realpathSync(line.slice(9)));
    const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], { cwd: checkoutRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    roots.add(realpathSync(path.dirname(common)));
  } catch { privateManifestError('repository roots cannot be verified'); }
  return [...roots];
}

export function resolveCommandVisualSourceManifest(
  manifestInput = process.env.COMMAND_VISUAL_SOURCE_MANIFEST,
  checkoutRoot = path.resolve(process.cwd(), '..'),
): ReadonlyMap<CommandReferenceAlias, ResolvedCommandReference> {
  if (!manifestInput || !path.isAbsolute(manifestInput)) privateManifestError('COMMAND_VISUAL_SOURCE_MANIFEST must be an absolute path');
  const manifestPath = regularNonSymlink(manifestInput, 'manifest');
  try {
    if ((lstatSync(manifestPath).mode & 0o077) !== 0) privateManifestError('manifest permissions must exclude group and other access');
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Command visual source manifest rejected:')) throw error;
    privateManifestError('manifest permissions cannot be verified');
  }
  if (path.extname(manifestPath).toLowerCase() !== '.json') privateManifestError('manifest extension must be .json');
  const repository = repositoryRoots(checkoutRoot);
  const roots = [...repository, ...repository.flatMap((root) => [
    path.resolve(root, 'frontend/public'), path.resolve(root, 'frontend/artifacts'),
    path.resolve(root, 'frontend/.next'), path.resolve(root, 'frontend/out'),
  ])];
  if (roots.some((root) => inside(manifestPath, root))) privateManifestError('manifest is inside a forbidden root');
  let manifestText: string;
  try { manifestText = readFileSync(manifestPath, 'utf8'); } catch { return privateManifestError('manifest cannot be read'); }
  const raw = strictJson(manifestText);
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw) || Object.keys(raw).sort().join(',') !== 'references,schema_version') privateManifestError('manifest has invalid top-level keys');
  const object = raw as Record<string, unknown>;
  if (object.schema_version !== 1 || typeof object.references !== 'object' || object.references === null || Array.isArray(object.references)) privateManifestError('manifest schema_version must be 1');
  const references = object.references as Record<string, unknown>;
  const aliases = Object.keys(CONTACT_ALIASES).sort();
  if (Object.keys(references).sort().join(',') !== aliases.join(',')) privateManifestError('manifest aliases must exactly match the known aliases');
  const resolved = new Map<CommandReferenceAlias, ResolvedCommandReference>();
  aliases.forEach((rawAlias) => {
    const alias = rawAlias as CommandReferenceAlias;
    const value = references[alias];
    if (typeof value !== 'object' || value === null || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'height,path,width') privateManifestError(`${alias} has invalid keys`);
    const row = value as Record<string, unknown>;
    const expected = CONTACT_ALIASES[alias];
    if (typeof row.path !== 'string' || !path.isAbsolute(row.path) || path.extname(row.path).toLowerCase() !== '.png') privateManifestError(`${alias} path must be an absolute PNG`);
    if (row.width !== expected.width || row.height !== expected.height) privateManifestError(`${alias} declared dimensions do not match the alias`);
    const sourcePath = regularNonSymlink(row.path, alias);
    if (roots.some((root) => inside(sourcePath, root))) privateManifestError(`${alias} is inside a forbidden root`);
    const actual = pngDimensions(sourcePath);
    if (actual.width !== expected.width || actual.height !== expected.height) privateManifestError(`${alias} PNG dimensions do not match the alias`);
    resolved.set(alias, { alias, sourcePath, ...expected });
  });
  return resolved;
}
