"use client";

import { useEffect, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Native <dialog>: focus is trapped and Escape closes it, which screen readers handle well. */
export default function ConfirmDialog({ open, title, children, confirmLabel, cancelLabel = "Cancel", danger, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      cancelRef.current?.focus();
    } else if (!open && d.open) {
      d.close();
    }
  }, [open]);

  return (
    <dialog ref={ref} aria-labelledby="dlg-title" aria-describedby="dlg-body" onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      <h2 id="dlg-title">{title}</h2>
      <div id="dlg-body">{children}</div>
      <div className="btn-row two">
        <button ref={cancelRef} type="button" className="btn" onClick={onCancel}>{cancelLabel}</button>
        <button type="button" className={`btn ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}
