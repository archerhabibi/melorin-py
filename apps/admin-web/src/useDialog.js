import { useEffect, useRef } from 'react';

// Phase 6.4 — one accessible-overlay behaviour for every modal, drawer and palette.
// Keep this file byte-identical in admin-web and store-web (a Core test enforces it).
//
//  - focus moves into the dialog on open ([data-autofocus] first, else the first control) and returns on close
//  - Tab / Shift+Tab are trapped inside the dialog
//  - Escape closes only the TOPMOST dialog (a confirm opened over a drawer closes alone)
//  - background scroll is locked while any dialog is open

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const stack = [];
let scrollLocks = 0;

export function useDialog(onClose) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const token = {};
    stack.push(token);
    const previous = document.activeElement;
    if (scrollLocks++ === 0) document.body.style.overflow = 'hidden';

    const controls = () =>
      [...node.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest('[hidden],[aria-hidden="true"]'));
    if (!node.contains(document.activeElement)) {
      (node.querySelector('[data-autofocus]') || controls()[0] || node).focus();
    }

    const onKey = (e) => {
      if (stack[stack.length - 1] !== token) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        closeRef.current?.();
        return;
      }
      if (e.key !== 'Tab') return;
      const list = controls();
      if (!list.length) {
        e.preventDefault();
        node.focus();
        return;
      }
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === node)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      stack.splice(stack.indexOf(token), 1);
      if (--scrollLocks === 0) document.body.style.overflow = '';
      if (previous && document.contains(previous)) previous.focus?.();
    };
  }, []);

  return ref;
}

// Backdrop props: closes on a press that STARTS on the backdrop itself (not a drag that ends there).
export const backdropProps = (onClose) => ({
  role: 'presentation',
  onMouseDown: (e) => {
    if (e.target === e.currentTarget) onClose();
  },
});

// Callback ref for inline editors that should take focus when they appear (replaces the autoFocus prop).
export const focusOnMount = (el) => {
  if (el) el.focus();
};
