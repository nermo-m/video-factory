"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches. Layout is decided in CSS. This is for the few places
 * where behaviour differs by width, such as a field that is read only on a small screen.
 * On the server, and until the page is live in the browser, it answers `onServer`.
 */
export function useMedia(query: string, onServer: boolean): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => onServer,
  );
}

/** 1024 px and up: the desktop layouts of design doc section 11.5. */
export const useIsDesktop = () => useMedia("(min-width: 1024px)", true);

/** Under 640 px: the phone layouts. */
export const useIsPhone = () => useMedia("(max-width: 639.98px)", false);
