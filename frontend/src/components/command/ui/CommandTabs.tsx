'use client';

import { useId, useRef, useState } from 'react';

export type CommandTab<Value extends string = string> = Readonly<{
  value: Value;
  label: string;
  disabled?: boolean;
}>;

export type CommandTabsProps<Value extends string = string> = Readonly<{
  idBase?: string;
  ariaLabel: string;
  tabs: readonly CommandTab<Value>[];
  value: Value;
  onValueChange: (value: Value) => void;
}>;

function safeId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '');
}

export function CommandTabs<Value extends string>({
  idBase,
  ariaLabel,
  tabs,
  value,
  onValueChange,
}: CommandTabsProps<Value>) {
  const generatedId = useId().replace(/:/g, '');
  const base = safeId(idBase ?? `command-tabs-${generatedId}`);
  const initialFocus = tabs.find((tab) => tab.value === value && !tab.disabled)?.value
    ?? tabs.find((tab) => !tab.disabled)?.value
    ?? value;
  const [focusState, setFocusState] = useState(() => ({
    controlledValue: value,
    focusedValue: initialFocus,
  }));
  const focusedValue = focusState.controlledValue === value
    ? focusState.focusedValue
    : initialFocus;
  const tabRefs = useRef(new Map<Value, HTMLButtonElement>());

  function rememberFocus(nextValue: Value) {
    setFocusState({ controlledValue: value, focusedValue: nextValue });
  }

  function focusTab(next: CommandTab<Value> | undefined) {
    if (!next || next.disabled) return;
    rememberFocus(next.value);
    tabRefs.current.get(next.value)?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, currentValue: Value) {
    const enabledTabs = tabs.filter((tab) => !tab.disabled);
    const currentIndex = enabledTabs.findIndex((tab) => tab.value === currentValue);
    if (currentIndex < 0 || enabledTabs.length === 0) return;

    let target: CommandTab<Value> | undefined;
    if (event.key === 'ArrowRight') {
      target = enabledTabs[(currentIndex + 1) % enabledTabs.length];
    } else if (event.key === 'ArrowLeft') {
      target = enabledTabs[(currentIndex - 1 + enabledTabs.length) % enabledTabs.length];
    } else if (event.key === 'Home') {
      target = enabledTabs[0];
    } else if (event.key === 'End') {
      target = enabledTabs[enabledTabs.length - 1];
    }

    if (target) {
      event.preventDefault();
      focusTab(target);
    }
  }

  return (
    <div role="tablist" aria-label={ariaLabel} className="command-tabs">
      {tabs.map((tab) => {
        const selected = tab.value === value;
        return (
          <button
            key={tab.value}
            ref={(element) => {
              if (element) tabRefs.current.set(tab.value, element);
              else tabRefs.current.delete(tab.value);
            }}
            id={`${base}-tab-${safeId(tab.value)}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`${base}-panel-${safeId(tab.value)}`}
            disabled={tab.disabled}
            tabIndex={tab.value === focusedValue ? 0 : -1}
            className={`command-tab${selected ? ' is-selected' : ''}`}
            onFocus={() => rememberFocus(tab.value)}
            onKeyDown={(event) => handleKeyDown(event, tab.value)}
            onClick={() => onValueChange(tab.value)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
