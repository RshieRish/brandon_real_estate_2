import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';


const navbarSource = readFileSync(new URL('./Navbar.tsx', import.meta.url), 'utf8');


describe('Navbar brokerage presentation', () => {
  it('keeps the header focused on Sold With Sweeney without an eXp lockup', () => {
    expect(navbarSource).toContain('src="/logos/sws-primary-white-gold.png"');
    expect(navbarSource).toContain('aria-label="Sold With Sweeney & Co."');
    expect(navbarSource).not.toContain('src="/logos/exp-realty-white.png"');
  });
});
