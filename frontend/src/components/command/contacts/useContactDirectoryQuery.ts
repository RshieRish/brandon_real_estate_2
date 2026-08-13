'use client';

import { useCallback, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type {
  ContactDirectoryRequest,
  ContactOrigin,
  ContactSortKey,
  ContactSource,
  ContactSmartView,
  SortDirection,
} from '@/lib/command/contacts';

export const CONTACT_QUERY_KEYS = [
  'query', 'stage', 'owner_actor_id', 'assignee_actor_id', 'tag', 'source', 'origin',
  'health_min', 'health_max', 'birthday_month', 'anniversary_month', 'smart_view',
  'sort', 'direction', 'page', 'page_size',
] as const;

export type ContactDirectoryQueryController = Readonly<{
  request: ContactDirectoryRequest;
  replace: (patch: Partial<ContactDirectoryRequest>) => void;
  reset: () => void;
}>;

export type ContactDetailQueryView =
  | 'timeline' | 'opportunities' | 'smart_plans' | 'tasks' | 'notes'
  | 'saved_searches' | 'evidence' | 'bookings';
export type ContactTaskQueryView = 'to_do' | 'completed' | 'archived';
export type ContactDetailSelection = Readonly<{
  view: ContactDetailQueryView;
  taskView: ContactTaskQueryView;
}>;

const DEFAULT_REQUEST = {
  smart_view: 'all',
  sort: 'name',
  direction: 'asc',
  page: 1,
  page_size: 50,
} as const satisfies ContactDirectoryRequest;

const SMART_VIEWS: readonly ContactSmartView[] = [
  'all', 'never_contacted', 'recently_active', 'birthdays_this_month',
  'anniversaries_this_month',
];
const SORT_KEYS: readonly ContactSortKey[] = [
  'name', 'stage', 'health_score', 'last_contacted_at', 'last_interaction_at',
  'created_at', 'updated_at',
];
const DIRECTIONS: readonly SortDirection[] = ['asc', 'desc'];
const SOURCES: readonly ContactSource[] = ['kw_command', 'internal_crm', 'legacy_lead'];
const ORIGINS: readonly ContactOrigin[] = [
  'recovered', 'lead_backed', 'legacy_only', 'internal_only',
];
const PAGE_SIZES = [25, 50, 100] as const;
const RESET_PAGE_KEYS = CONTACT_QUERY_KEYS.filter((key) => key !== 'page') as readonly Exclude<
  (typeof CONTACT_QUERY_KEYS)[number],
  'page'
>[];

function oneOf<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return value !== null && allowed.includes(value as T) ? value as T : undefined;
}

function text(value: string | null, maximum: number): string | undefined {
  if (value === null) return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 && Array.from(trimmed).length <= maximum ? trimmed : undefined;
}

function integer(
  value: string | null,
  minimum: number,
  maximum = Number.MAX_SAFE_INTEGER,
): number | undefined {
  if (value === null || !/^(0|[1-9][0-9]*)$/.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum
    ? parsed
    : undefined;
}

function setOf<T extends string>(
  values: readonly string[],
  allowed: readonly T[],
): readonly T[] | undefined {
  const result = [...new Set(values.filter((value): value is T => allowed.includes(value as T)))].sort();
  return result.length > 0 ? result : undefined;
}

function idSet(values: readonly string[]): readonly number[] | undefined {
  const result = [...new Set(values
    .map((value) => integer(value, 1))
    .filter((value): value is number => value !== undefined))]
    .sort((left, right) => left - right);
  return result.length > 0 ? result : undefined;
}

export function parseContactDirectoryRequest(
  params: Pick<URLSearchParams, 'get' | 'getAll' | 'has'>,
  initialView: ContactSmartView = 'all',
): ContactDirectoryRequest {
  const query = text(params.get('query'), 200);
  const stage = text(params.get('stage'), 50);
  const ownerActorId = text(params.get('owner_actor_id'), 255);
  const assigneeActorId = text(params.get('assignee_actor_id'), 255);
  const tag = idSet(params.getAll('tag'));
  const source = setOf(params.getAll('source'), SOURCES);
  const origin = setOf(params.getAll('origin'), ORIGINS);
  const parsedHealthMin = integer(params.get('health_min'), 0, 100);
  const parsedHealthMax = integer(params.get('health_max'), 0, 100);
  const reversedHealthRange = parsedHealthMin !== undefined
    && parsedHealthMax !== undefined
    && parsedHealthMin > parsedHealthMax;
  const healthMin = reversedHealthRange ? undefined : parsedHealthMin;
  const healthMax = reversedHealthRange ? undefined : parsedHealthMax;
  const birthdayMonth = integer(params.get('birthday_month'), 1, 12);
  const anniversaryMonth = integer(params.get('anniversary_month'), 1, 12);
  const smartView = oneOf(params.get('smart_view'), SMART_VIEWS)
    ?? (params.has('smart_view') ? DEFAULT_REQUEST.smart_view : initialView);
  const sort = oneOf(params.get('sort'), SORT_KEYS) ?? DEFAULT_REQUEST.sort;
  const direction = oneOf(params.get('direction'), DIRECTIONS) ?? DEFAULT_REQUEST.direction;
  const page = integer(params.get('page'), 1) ?? DEFAULT_REQUEST.page;
  const rawPageSize = integer(params.get('page_size'), 1, 100);
  const pageSize = rawPageSize !== undefined && PAGE_SIZES.some((size) => size === rawPageSize)
    ? rawPageSize
    : DEFAULT_REQUEST.page_size;

  return {
    ...(query ? { query } : {}),
    ...(stage ? { stage } : {}),
    ...(ownerActorId ? { owner_actor_id: ownerActorId } : {}),
    ...(assigneeActorId ? { assignee_actor_id: assigneeActorId } : {}),
    ...(tag ? { tag } : {}),
    ...(source ? { source } : {}),
    ...(origin ? { origin } : {}),
    ...(healthMin !== undefined ? { health_min: healthMin } : {}),
    ...(healthMax !== undefined ? { health_max: healthMax } : {}),
    ...(birthdayMonth !== undefined ? { birthday_month: birthdayMonth } : {}),
    ...(anniversaryMonth !== undefined ? { anniversary_month: anniversaryMonth } : {}),
    smart_view: smartView,
    sort,
    direction,
    page,
    page_size: pageSize,
  };
}

function appendCanonical(params: URLSearchParams, request: ContactDirectoryRequest): void {
  const appendText = (key: string, value: string | undefined): void => {
    if (value) params.append(key, value);
  };
  const appendMany = (key: string, values: readonly (string | number)[] | undefined): void => {
    values?.forEach((value) => params.append(key, String(value)));
  };
  const appendInteger = (key: string, value: number | undefined): void => {
    if (value !== undefined) params.append(key, String(value));
  };

  appendText('query', request.query);
  appendText('stage', request.stage);
  appendText('owner_actor_id', request.owner_actor_id);
  appendText('assignee_actor_id', request.assignee_actor_id);
  appendMany('tag', request.tag);
  appendMany('source', request.source);
  appendMany('origin', request.origin);
  appendInteger('health_min', request.health_min);
  appendInteger('health_max', request.health_max);
  appendInteger('birthday_month', request.birthday_month);
  appendInteger('anniversary_month', request.anniversary_month);
  if (request.smart_view !== DEFAULT_REQUEST.smart_view) appendText('smart_view', request.smart_view);
  if (request.sort !== DEFAULT_REQUEST.sort) appendText('sort', request.sort);
  if (request.direction !== DEFAULT_REQUEST.direction) appendText('direction', request.direction);
  appendInteger('page', request.page ?? DEFAULT_REQUEST.page);
  appendInteger('page_size', request.page_size ?? DEFAULT_REQUEST.page_size);
}

function appendUnrelated(
  result: URLSearchParams,
  rawParams: Pick<URLSearchParams, 'entries'>,
  excluded: readonly string[] = [],
): void {
  for (const [key, value] of rawParams.entries()) {
    if (CONTACT_QUERY_KEYS.includes(key as (typeof CONTACT_QUERY_KEYS)[number])) continue;
    if (key === 'filter' || excluded.includes(key)) continue;
    result.append(key, value);
  }
}

export function canonicalContactLocationParams(
  input: Pick<URLSearchParams, 'entries' | 'get' | 'getAll' | 'has'>,
  initialView: ContactSmartView = 'all',
): URLSearchParams {
  const request = parseContactDirectoryRequest(input, initialView);
  const result = new URLSearchParams();
  appendCanonical(result, request);
  if (!input.has('page')) result.delete('page');
  if (!input.has('page_size')) result.delete('page_size');
  appendUnrelated(result, input);
  return result;
}

export function contactLocationParamsForRequest(
  request: ContactDirectoryRequest,
  rawParams: URLSearchParams,
): URLSearchParams {
  const result = new URLSearchParams();
  appendCanonical(result, request);
  if (!rawParams.has('page') && request.page === DEFAULT_REQUEST.page) result.delete('page');
  if (!rawParams.has('page_size') && request.page_size === DEFAULT_REQUEST.page_size) {
    result.delete('page_size');
  }
  appendUnrelated(result, rawParams);
  return result;
}

export function contactDetailLocationParams(
  request: ContactDirectoryRequest,
  rawParams: URLSearchParams,
  contactView?: string,
  taskState?: string,
): URLSearchParams {
  const result = new URLSearchParams();
  appendCanonical(result, request);
  if (!rawParams.has('page') && request.page === DEFAULT_REQUEST.page) result.delete('page');
  if (!rawParams.has('page_size') && request.page_size === DEFAULT_REQUEST.page_size) {
    result.delete('page_size');
  }
  if (contactView && contactView !== 'timeline') result.append('contact_view', contactView);
  if (contactView === 'tasks' && taskState && taskState !== 'to_do') {
    result.append('task_state', taskState);
  }
  appendUnrelated(result, rawParams, ['contact_view', 'task_state']);
  return result;
}

export function parseContactDetailSelection(
  params: Pick<URLSearchParams, 'get'>,
): ContactDetailSelection {
  const rawView = params.get('contact_view');
  const view: ContactDetailQueryView = rawView === 'opportunities' || rawView === 'smart_plans'
    || rawView === 'tasks' || rawView === 'notes' || rawView === 'saved_searches'
    || rawView === 'evidence' || rawView === 'bookings'
    ? rawView
    : 'timeline';
  const rawTask = params.get('task_state');
  const taskView: ContactTaskQueryView = view === 'tasks' && (rawTask === 'completed' || rawTask === 'archived')
    ? rawTask
    : 'to_do';
  return { view, taskView };
}

export function contactDetailHref(
  contactId: number,
  params: URLSearchParams,
): string {
  if (!Number.isSafeInteger(contactId) || contactId < 1) {
    throw new TypeError('contactId must be a positive safe integer');
  }
  const query = canonicalContactLocationParams(params).toString();
  return `/admin/command/contacts/${contactId}${query ? `?${query}` : ''}`;
}

function mergeRequest(
  current: ContactDirectoryRequest,
  patch: Partial<ContactDirectoryRequest>,
): ContactDirectoryRequest {
  const boundedText = (value: string | undefined, maximum: number): string | undefined => {
    if (value === undefined) return undefined;
    const trimmed = value.trim();
    return trimmed.length > 0 && Array.from(trimmed).length <= maximum ? trimmed : undefined;
  };
  const bounded = (
    value: number | undefined,
    minimum: number,
    maximum: number,
  ): number | undefined => (
    value === undefined
      || !Number.isSafeInteger(value)
      || value < minimum
      || value > maximum
      ? undefined
      : value
  );
  const changed = RESET_PAGE_KEYS.some((key) => (
    Object.hasOwn(patch, key)
    && JSON.stringify(patch[key]) !== JSON.stringify(current[key])
  ));
  const next = {
    ...current,
    ...patch,
    page: changed ? 1 : (patch.page ?? current.page ?? DEFAULT_REQUEST.page),
    page_size: patch.page_size ?? current.page_size ?? DEFAULT_REQUEST.page_size,
  };
  const {
    query,
    stage,
    owner_actor_id: ownerActorId,
    assignee_actor_id: assigneeActorId,
    health_min: rawHealthMin,
    health_max: rawHealthMax,
    birthday_month: rawBirthdayMonth,
    anniversary_month: rawAnniversaryMonth,
    ...base
  } = next;
  let healthMin = bounded(rawHealthMin, 0, 100);
  let healthMax = bounded(rawHealthMax, 0, 100);
  if (healthMin !== undefined && healthMax !== undefined && healthMin > healthMax) {
    if (Object.hasOwn(patch, 'health_min') && !Object.hasOwn(patch, 'health_max')) healthMax = undefined;
    else if (Object.hasOwn(patch, 'health_max') && !Object.hasOwn(patch, 'health_min')) healthMin = undefined;
    else {
      healthMin = undefined;
      healthMax = undefined;
    }
  }
  const normalizedQuery = boundedText(query, 200);
  const normalizedStage = boundedText(stage, 50);
  const normalizedOwner = boundedText(ownerActorId, 255);
  const normalizedAssignee = boundedText(assigneeActorId, 255);
  const birthdayMonth = bounded(rawBirthdayMonth, 1, 12);
  const anniversaryMonth = bounded(rawAnniversaryMonth, 1, 12);
  return {
    ...base,
    ...(normalizedQuery ? { query: normalizedQuery } : {}),
    ...(normalizedStage ? { stage: normalizedStage } : {}),
    ...(normalizedOwner ? { owner_actor_id: normalizedOwner } : {}),
    ...(normalizedAssignee ? { assignee_actor_id: normalizedAssignee } : {}),
    ...(healthMin !== undefined ? { health_min: healthMin } : {}),
    ...(healthMax !== undefined ? { health_max: healthMax } : {}),
    ...(birthdayMonth !== undefined ? { birthday_month: birthdayMonth } : {}),
    ...(anniversaryMonth !== undefined ? { anniversary_month: anniversaryMonth } : {}),
    page: bounded(next.page, 1, Number.MAX_SAFE_INTEGER) ?? DEFAULT_REQUEST.page,
    page_size: next.page_size !== undefined && PAGE_SIZES.some((size) => size === next.page_size)
      ? next.page_size
      : DEFAULT_REQUEST.page_size,
    ...(next.tag ? { tag: [...new Set(next.tag)].sort((left, right) => left - right) } : {}),
    ...(next.source ? { source: [...new Set(next.source)].sort() } : {}),
    ...(next.origin ? { origin: [...new Set(next.origin)].sort() } : {}),
  };
}

export function useContactDirectoryQuery(
  initialView: ContactSmartView = 'all',
): ContactDirectoryQueryController {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const parsedRequest = useMemo(
    () => parseContactDirectoryRequest(new URLSearchParams(searchString), initialView),
    [initialView, searchString],
  );
  const [optimistic, setOptimistic] = useState<Readonly<{
    baseParams: object;
    request: ContactDirectoryRequest;
  }> | null>(null);
  const request = optimistic?.baseParams === searchParams ? optimistic.request : parsedRequest;

  const write = useCallback((next: ContactDirectoryRequest) => {
    const params = new URLSearchParams(searchString);
    CONTACT_QUERY_KEYS.forEach((key) => params.delete(key));
    params.delete('filter');
    if (params.get('sort') === 'recent_activity') params.delete('sort');
    appendCanonical(params, next);
    const query = params.toString();
    router.replace(`${pathname}${query ? `?${query}` : ''}`, { scroll: false });
  }, [pathname, router, searchString]);

  const replace = useCallback((patch: Partial<ContactDirectoryRequest>) => {
    const next = mergeRequest(request, patch);
    setOptimistic({ baseParams: searchParams, request: next });
    write(next);
  }, [request, searchParams, write]);
  const reset = useCallback(() => {
    setOptimistic({ baseParams: searchParams, request: DEFAULT_REQUEST });
    write(DEFAULT_REQUEST);
  }, [searchParams, write]);

  return useMemo(() => ({ request, replace, reset }), [replace, request, reset]);
}
