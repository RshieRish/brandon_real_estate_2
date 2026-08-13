import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

function Probe() {
  const [open, setOpen] = useState(false);
  return (
    <button type="button" aria-expanded={open} onClick={() => setOpen(true)}>
      Open workspace
    </button>
  );
}

describe('Testing Library runtime', () => {
  it('renders and operates a React client component', async () => {
    const user = userEvent.setup();
    render(<Probe />);
    const button = screen.getByRole('button', { name: 'Open workspace' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await user.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
  });
});
