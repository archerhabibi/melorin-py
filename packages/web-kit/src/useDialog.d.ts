import type { MouseEvent, RefObject } from 'react';

/** Accessible-overlay behaviour: focus trap, Escape-to-close (topmost only), scroll lock. */
export function useDialog<T extends HTMLElement = HTMLDivElement>(onClose?: () => void): RefObject<T>;
/** Props for a modal backdrop: closes on a press that STARTS on the backdrop itself. */
export function backdropProps(onClose: () => void): {
  role: 'presentation';
  onMouseDown: (e: MouseEvent<HTMLElement>) => void;
};
/** Callback ref for inline editors that take focus when they appear. */
export function focusOnMount(el: HTMLElement | null): void;
