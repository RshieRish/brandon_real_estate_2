import { describe, expect, it } from 'vitest';
import { commandSourceReferences } from '../../e2e/visual/command-reference-manifest';

describe('Command source visual manifest', () => {
  it('uses only known rendered targets for parity comparisons', () => {
    const valid = commandSourceReferences.filter((item) => item.quality === 'valid').map((item) => item.filename);
    expect(valid).toContain('command-home-live.png');
    expect(valid).toContain('contacts-live-current.png');
    expect(valid).toContain('tasks-to-do-live.png');
    expect(valid).not.toContain('top-home.png');
    expect(valid).not.toContain('contacts-list.png');
    expect(valid.some((filename) => filename.endsWith('-retry.png'))).toBe(false);
  });

  it('records source dimensions and brand-only mask rectangles', () => {
    const home = commandSourceReferences.find((item) => item.filename === 'command-home-live.png');
    expect(home).toMatchObject({ width: 1800, height: 2249, quality: 'valid' });
    expect(home?.brandMasks).toEqual(expect.arrayContaining([
      { x: 0, y: 0, width: 80, height: 64, reason: 'source vendor mark' },
    ]));
  });

  it('keeps limitation captures explicit and out of valid targets', () => {
    const limitations = commandSourceReferences.filter((item) => item.quality === 'limitation');
    expect(limitations.map((item) => item.filename)).toEqual(expect.arrayContaining([
      'top-home.png',
      'contacts-list.png',
      'opportunities-board.png',
      'smartplans-my.png',
      'referrals-dashboard-error-state.png',
    ]));
    expect(limitations.every((item) => item.observedState.length > 0)).toBe(true);
  });
});
