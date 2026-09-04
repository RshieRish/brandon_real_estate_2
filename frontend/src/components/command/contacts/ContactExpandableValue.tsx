'use client';

import { useId, useMemo, useState } from 'react';
import { CaretDown, CaretUp } from '@phosphor-icons/react';
import { motion, useReducedMotion } from 'framer-motion';
import { contactPresentationText } from '@/lib/command/contacts';

type ContactExpandableElement = 'h3' | 'h4' | 'p' | 'strong';

export function ContactExpandableValue({
  value,
  limit,
  element,
  label,
}: Readonly<{
  value: string;
  limit: number;
  element: ContactExpandableElement;
  label: string;
}>) {
  const [expanded, setExpanded] = useState(false);
  const reduceMotion = useReducedMotion();
  const id = useId().replace(/:/g, '');
  const presentation = useMemo(() => contactPresentationText(value, limit), [limit, value]);
  const visible = expanded ? presentation.full : presentation.preview;

  return (
    <motion.div
      layout={!reduceMotion}
      transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 100, damping: 20 }}
      className={`command-contact-expandable is-${element}`}
    >
      {element === 'h3' ? <h3 id={id}>{visible}</h3> : null}
      {element === 'h4' ? <h4 id={id}>{visible}</h4> : null}
      {element === 'p' ? <p id={id}>{visible}</p> : null}
      {element === 'strong' ? <strong id={id}>{visible}</strong> : null}
      {presentation.truncated ? (
        <button
          type="button"
          className="command-inline-button command-contact-expand-toggle command-print-hidden"
          aria-controls={id}
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? <CaretUp aria-hidden="true" size={15} /> : <CaretDown aria-hidden="true" size={15} />}
          {expanded ? `Collapse ${label}` : `Show full ${label}`}
        </button>
      ) : null}
    </motion.div>
  );
}
