import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const linkPackSource = readFileSync(new URL('./LinkPackPage.tsx', import.meta.url), 'utf8');

describe('LinkPackPage brokerage presentation', () => {
  it('does not render an eXp logo over the link-page background', () => {
    expect(linkPackSource).not.toContain('src="/logos/exp-realty-white.png"');
  });
});
