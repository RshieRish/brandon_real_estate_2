import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';


const navbarSource = readFileSync(new URL('./Navbar.tsx', import.meta.url), 'utf8');


describe('Navbar brokerage presentation', () => {
  it('keeps the header focused on Sold With Sweeney without an eXp lockup', () => {
    expect(navbarSource).toContain('src="/logos/sws-primary-white-gold.png"');
    expect(navbarSource).toContain('aria-label="Sold With Sweeney & Co."');
    expect(navbarSource).not.toContain('src="/logos/exp-realty-white.png"');
  });

  it('crops the padded logo into a readable responsive header mark', () => {
    expect(navbarSource).toMatch(
      /className="[^"]*h-16[^"]*w-28[^"]*overflow-hidden[^"]*sm:w-\[124px\][^"]*"/,
    );
    expect(navbarSource).toContain('width={152}');
    expect(navbarSource).toContain('height={80}');
    expect(navbarSource).toMatch(
      /className="[^"]*h-\[72px\][^"]*w-auto[^"]*max-w-none[^"]*sm:h-20[^"]*"/,
    );
    expect(navbarSource).not.toContain('width={76}');
  });
});
