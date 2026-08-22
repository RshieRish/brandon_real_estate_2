export type CapturedTaskSuggestionHandoff = Readonly<{
  handoff: string | null;
  invalid_query_secret: boolean;
  invalid_handoff: boolean;
}>;

export type TaskSuggestionHandoffBootstrapMetadata = Readonly<{
  has_handoff: boolean;
  invalid_query_secret: boolean;
  invalid_handoff: boolean;
}>;

type HandoffWindow = Window & {
  __swsTaskSuggestionHandoff?: () => CapturedTaskSuggestionHandoff;
  __swsTaskSuggestionHadHandoff?: boolean;
};

const emptyCapture: CapturedTaskSuggestionHandoff = Object.freeze({
  handoff: null,
  invalid_query_secret: false,
  invalid_handoff: false,
});

export function installTaskSuggestionHandoffBootstrap(
  target: Window,
): TaskSuggestionHandoffBootstrapMetadata {
  const handoffWindow = target as HandoffWindow;
  const url = new URL(target.location.href);
  const forbiddenQueryKeys = new Set(['handoff', 'approval', 'token', 'nonce']);
  const invalidQuerySecret = Array.from(url.searchParams.keys()).some((key) =>
    forbiddenQueryKeys.has(key.toLowerCase()),
  );
  const safeSearch = new URLSearchParams(url.searchParams);
  for (const key of Array.from(safeSearch.keys())) {
    if (forbiddenQueryKeys.has(key.toLowerCase())) safeSearch.delete(key);
  }
  let handoff: string | null = null;
  let invalidHandoff = false;
  if (url.hash.startsWith('#handoff=')) {
    const candidate = url.hash.slice('#handoff='.length);
    if (/^[A-Za-z0-9_-]{43}$/.test(candidate) && !invalidQuerySecret) handoff = candidate;
    else invalidHandoff = true;
  }
  if (invalidQuerySecret || url.hash.startsWith('#handoff=')) {
    const query = safeSearch.size === 0 ? '' : `?${safeSearch.toString()}`;
    target.history.replaceState(target.history.state, '', `${url.pathname}${query}`);
  }
  let consumed = false;
  Object.defineProperty(handoffWindow, '__swsTaskSuggestionHandoff', {
    configurable: true,
    enumerable: false,
    value: () => {
      if (consumed) return emptyCapture;
      consumed = true;
      const result = {
        handoff,
        invalid_query_secret: invalidQuerySecret,
        invalid_handoff: invalidHandoff,
      };
      handoff = null;
      Reflect.deleteProperty(handoffWindow, '__swsTaskSuggestionHandoff');
      return result;
    },
  });
  Object.defineProperty(handoffWindow, '__swsTaskSuggestionHadHandoff', {
    configurable: true,
    enumerable: false,
    value: handoff !== null,
  });
  return Object.freeze({
    has_handoff: handoff !== null,
    invalid_query_secret: invalidQuerySecret,
    invalid_handoff: invalidHandoff,
  });
}

export function hadTaskSuggestionHandoff(target: Window = window): boolean {
  return (target as HandoffWindow).__swsTaskSuggestionHadHandoff === true;
}

export function consumeTaskSuggestionHandoffBootstrap(
  target: Window = window,
): CapturedTaskSuggestionHandoff {
  const handoffWindow = target as HandoffWindow;
  const consume = handoffWindow.__swsTaskSuggestionHandoff;
  return consume === undefined ? emptyCapture : consume();
}
