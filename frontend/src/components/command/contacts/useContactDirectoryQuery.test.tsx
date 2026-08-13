import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContactSmartView } from '@/lib/command/contacts';
import {
  CONTACT_QUERY_KEYS,
  useContactDirectoryQuery,
} from './useContactDirectoryQuery';

const navigation = vi.hoisted(() => ({
  pathname: '/admin/command/contacts',
  replace: vi.fn(),
  search: new URLSearchParams(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.search,
}));

function renderQuery(initialView: ContactSmartView = 'all') {
  return renderHook(
    ({ view }) => useContactDirectoryQuery(view),
    { initialProps: { view: initialView } },
  );
}

describe('useContactDirectoryQuery', () => {
  beforeEach(() => {
    navigation.pathname = '/admin/command/contacts';
    navigation.search = new URLSearchParams();
    navigation.replace.mockReset();
  });

  it('owns the exact stable query-key inventory and supplies server defaults', () => {
    expect(CONTACT_QUERY_KEYS).toEqual([
      'query', 'stage', 'owner_actor_id', 'assignee_actor_id', 'tag', 'source', 'origin',
      'health_min', 'health_max', 'birthday_month', 'anniversary_month', 'smart_view',
      'sort', 'direction', 'page', 'page_size',
    ]);

    const { result } = renderQuery();

    expect(result.current.request).toEqual({
      smart_view: 'all',
      sort: 'name',
      direction: 'asc',
      page: 1,
      page_size: 50,
    });
  });

  it('parses, bounds, deduplicates, and sorts all repeatable values', () => {
    navigation.search = new URLSearchParams(
      'query=Ada+%26+Co&stage=client&owner_actor_id=owner%2F1&assignee_actor_id=a%2Bb'
      + '&tag=7&tag=2&tag=7&source=legacy_lead&source=kw_command&source=legacy_lead'
      + '&origin=recovered&origin=internal_only&health_min=10&health_max=90'
      + '&birthday_month=8&anniversary_month=9&smart_view=recently_active'
      + '&sort=last_interaction_at&direction=desc&page=3&page_size=25',
    );

    const { result } = renderQuery();

    expect(result.current.request).toEqual({
      query: 'Ada & Co',
      stage: 'client',
      owner_actor_id: 'owner/1',
      assignee_actor_id: 'a+b',
      tag: [2, 7],
      source: ['kw_command', 'legacy_lead'],
      origin: ['internal_only', 'recovered'],
      health_min: 10,
      health_max: 90,
      birthday_month: 8,
      anniversary_month: 9,
      smart_view: 'recently_active',
      sort: 'last_interaction_at',
      direction: 'desc',
      page: 3,
      page_size: 25,
    });
  });

  it('drops invalid owned values and writes canonical defaults without losing unrelated params', () => {
    navigation.search = new URLSearchParams(
      'campaign=fall&query=&stage=' + 'x'.repeat(51)
      + '&tag=0&tag=03&source=other&origin=other&health_min=101&health_max=-1'
      + '&birthday_month=13&anniversary_month=0&smart_view=nope&sort=nope'
      + '&direction=sideways&page=00&page_size=101',
    );
    const { result } = renderQuery();

    expect(result.current.request).toEqual({
      smart_view: 'all',
      sort: 'name',
      direction: 'asc',
      page: 1,
      page_size: 50,
    });

    act(() => result.current.replace({}));

    expect(navigation.replace).toHaveBeenCalledWith(
      '/admin/command/contacts?campaign=fall&page=1&page_size=50',
      { scroll: false },
    );
  });

  it('drops a reversed health range instead of silently changing its meaning', () => {
    navigation.search = new URLSearchParams('health_min=90&health_max=10&page=4');
    const { result } = renderQuery();

    expect(result.current.request.health_min).toBeUndefined();
    expect(result.current.request.health_max).toBeUndefined();
    act(() => result.current.replace({}));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toBe(
      '/admin/command/contacts?page=4&page_size=50',
    );
  });

  it('never writes invalid interactive numeric patches to the URL or server request', () => {
    const { result } = renderQuery();

    act(() => result.current.replace({ health_min: 101, birthday_month: 13 }));
    expect(result.current.request.health_min).toBeUndefined();
    expect(result.current.request.birthday_month).toBeUndefined();
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toBe(
      '/admin/command/contacts?page=1&page_size=50',
    );

    act(() => result.current.replace({ health_min: 90 }));
    act(() => result.current.replace({ health_max: 10 }));
    expect(result.current.request.health_min).toBeUndefined();
    expect(result.current.request.health_max).toBe(10);
    expect(navigation.replace.mock.calls.at(-1)?.[0]).not.toContain('health_min=90');
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('health_max=10');
  });

  it('drops over-bound text patches while retaining arbitrary valid stages', () => {
    const { result } = renderQuery();

    act(() => result.current.replace({ query: 'x'.repeat(201), stage: 'zebra' }));
    expect(result.current.request.query).toBeUndefined();
    expect(result.current.request.stage).toBe('zebra');
    expect(navigation.replace.mock.calls.at(-1)?.[0]).not.toContain('query=');
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('stage=zebra');
  });

  it('serializes reserved characters in exact key order regardless of incoming order', () => {
    navigation.search = new URLSearchParams('z=last&direction=desc&page_size=25&page=4&a=first');
    const { result } = renderQuery();

    act(() => result.current.replace({
      query: 'A&B / +?',
      origin: ['recovered', 'internal_only', 'recovered'],
      source: ['legacy_lead', 'kw_command'],
      tag: [9, 1, 9],
      sort: 'stage',
    }));

    expect(navigation.replace).toHaveBeenCalledWith(
      '/admin/command/contacts?z=last&a=first&query=A%26B+%2F+%2B%3F&tag=1&tag=9'
      + '&source=kw_command&source=legacy_lead&origin=internal_only&origin=recovered'
      + '&sort=stage&direction=desc&page=1&page_size=25',
      { scroll: false },
    );
  });

  it('resets page for universe, sort, direction, and page-size changes but preserves page-only changes', () => {
    navigation.search = new URLSearchParams(
      'stage=lead&smart_view=never_contacted&sort=stage&direction=desc&page=8&page_size=25',
    );
    const first = renderQuery();

    act(() => first.result.current.replace({ stage: 'client' }));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('stage=client');
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('page=1&page_size=25');

    act(() => first.result.current.replace({ page: 3 }));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('page=3&page_size=25');
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('stage=client');

    act(() => first.result.current.replace({ page_size: 100 }));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toContain('page=1&page_size=100');
  });

  it('uses the server-page initial view only without canonical smart_view and cleans exact legacy aliases', () => {
    navigation.search = new URLSearchParams('filter=birthdays&campaign=spring&page=2');
    const { result } = renderQuery('birthdays_this_month');

    expect(result.current.request.smart_view).toBe('birthdays_this_month');
    act(() => result.current.replace({}));
    expect(navigation.replace).toHaveBeenCalledWith(
      '/admin/command/contacts?campaign=spring&smart_view=birthdays_this_month&page=2&page_size=50',
      { scroll: false },
    );

    navigation.replace.mockReset();
    navigation.search = new URLSearchParams(
      'filter=never_contacted&smart_view=recently_active&sort=recent_activity&page=4',
    );
    const canonical = renderQuery('never_contacted');
    expect(canonical.result.current.request.smart_view).toBe('recently_active');
    act(() => canonical.result.current.replace({}));
    expect(navigation.replace.mock.calls.at(-1)?.[0]).toBe(
      '/admin/command/contacts?smart_view=recently_active&page=4&page_size=50',
    );
  });

  it('resets all filters while retaining only canonical pagination defaults', () => {
    navigation.search = new URLSearchParams(
      'campaign=summer&query=Ada&stage=client&tag=2&smart_view=recently_active&page=9&page_size=25',
    );
    const { result } = renderQuery();

    act(() => result.current.reset());

    expect(navigation.replace).toHaveBeenCalledWith(
      '/admin/command/contacts?campaign=summer&page=1&page_size=50',
      { scroll: false },
    );
  });

  it('canonicalizes reordered equivalent inputs to identical output', () => {
    const write = (search: string) => {
      navigation.search = new URLSearchParams(search);
      navigation.replace.mockReset();
      const view = renderQuery();
      act(() => view.result.current.replace({}));
      view.unmount();
      return navigation.replace.mock.calls.at(-1)?.[0];
    };

    expect(write('page=2&tag=3&origin=recovered&tag=1&source=legacy_lead&x=1')).toBe(
      write('x=1&source=legacy_lead&tag=1&tag=3&origin=recovered&page=2'),
    );
  });

  it('retires optimistic state after navigation so browser back reflects the URL', () => {
    const view = renderQuery();

    act(() => view.result.current.replace({ stage: 'zebra' }));
    expect(view.result.current.request.stage).toBe('zebra');

    navigation.search = new URLSearchParams('stage=zebra&page=1&page_size=50');
    view.rerender({ view: 'all' });
    expect(view.result.current.request.stage).toBe('zebra');

    navigation.search = new URLSearchParams();
    view.rerender({ view: 'all' });
    expect(view.result.current.request.stage).toBeUndefined();
  });
});
