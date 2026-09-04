import { describe, expect, it } from 'vitest';
import {
  commandNavigation,
  findCommandDestination,
  isCommandDestinationActive,
} from './commandNavigation';

describe('Command navigation registry', () => {
  it('contains every existing Command destination once', () => {
    expect(commandNavigation.map((item) => item.href)).toEqual([
      '/admin/command',
      '/admin/command/contacts',
      '/admin/command/tasks',
      '/admin/command/task-suggestions',
      '/admin/command/cards',
      '/admin/command/smart-plans',
      '/admin/command/opportunities',
      '/admin/command/referrals',
      '/admin/command/marketing',
      '/admin/command/agreements',
      '/admin/command/reports',
      '/admin/command/listings',
      '/admin/command/websites',
      '/admin/command/archive',
      '/admin/command/ai',
      '/admin/command/import',
      '/admin/command/saved-searches',
    ]);
  });

  it('matches Home exactly and nested module routes by prefix', () => {
    expect(isCommandDestinationActive('/admin/command', '/admin/command')).toBe(true);
    expect(isCommandDestinationActive('/admin/command/contacts', '/admin/command')).toBe(false);
    expect(
      isCommandDestinationActive('/admin/command/contacts/42', '/admin/command/contacts'),
    ).toBe(true);
    expect(findCommandDestination('/admin/command/tasks/9')?.label).toBe('Tasks');
    expect(findCommandDestination('/admin/command/task-suggestions')?.label).toBe('Task review');
    expect(findCommandDestination('/admin/command/cards/campaign-id')?.label).toBe('Client cards');
  });
});
