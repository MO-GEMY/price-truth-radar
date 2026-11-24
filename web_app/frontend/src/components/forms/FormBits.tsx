"use client";

import type { ReactNode } from "react";

/**
 * Honeypot field: invisible to people, tempting to bots that fill every input.
 * A submission with this field filled is answered like a success and dropped by
 * the API. Kept in the layout (not `display: none`) so simple bots still see it.
 */
export function Honeypot({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="ptr-honeypot" aria-hidden="true">
      <label htmlFor={id}>Website</label>
      <input
        id={id}
        name="website"
        type="text"
        tabIndex={-1}
        autoComplete="off"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

/** Hint text under a form control. */
export function FieldHint({ children }: { children: ReactNode }) {
  return (
    <p className="mt-1.5 text-xs ptr-muted">{children}</p>
  );
}

/** Inline validation message, linked to its control through `aria-describedby`. */
export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p className="ptr-error mt-1.5" id={id} role="alert">
      {children}
    </p>
  );
}

/** Small pill marking a required field. */
export function Required() {
  return (
    <span className="ptr-required" aria-hidden="true">
      *
    </span>
  );
}

/** Moves keyboard focus to the first rejected field (by DOM id) after validation. */
export function focusFirstInvalid(ids: string[]): void {
  document.getElementById(ids[0])?.focus();
}
