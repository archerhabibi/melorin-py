// GoogleSignIn.jsx — reusable Google Identity Services button for store-web
// Loads the GIS script once, initialises google.accounts.id, and renders a
// custom Persian button that matches the Melorin design system.

import { useEffect, useRef, useState } from "react";

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

export function useGoogleSignIn(onCredential) {
  const ready = useRef(false);
  // Always call the latest handler (GIS keeps the callback given at initialize() time).
  const latest = useRef(onCredential);
  latest.current = onCredential;

  useEffect(() => {
    if (!CLIENT_ID) return;            // env var not set → skip
    if (ready.current) return;

    function init() {
      ready.current = true;
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: (response) => latest.current(response.credential),
        ux_mode: "popup",
        cancel_on_tap_outside: true,
      });
    }

    if (window.google?.accounts?.id) { init(); return; }

    const existing = document.querySelector("script[data-gsi]");
    if (!existing) {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.defer = true;
      s.dataset.gsi = "1";
      s.onload = init;
      document.head.appendChild(s);
    } else {
      existing.addEventListener("load", init, { once: true });
    }
  }, []);
}

// SVG Google logo (official colours)
function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20c11 0 20-9 20-20 0-1.3-.1-2.5-.4-3.5z"/>
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.5 16 19 13 24 13c3.1 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.5 29.3 4 24 4 16.3 4 9.7 8.5 6.3 14.7z"/>
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.3 35.5 26.8 36 24 36c-5.2 0-9.7-3.1-11.3-7.5l-6.5 5C9.5 39.3 16.2 44 24 44z"/>
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.3 4.1-4.3 5.5l6.2 5.2C40.9 36.4 44 30.7 44 24c0-1.3-.1-2.5-.4-3.5z"/>
    </svg>
  );
}

export function GoogleSignInButton({ onCredential, label = "ورود با گوگل", className = "" }) {
  const [busy, setBusy] = useState(false);

  if (!CLIENT_ID) return null;        // hide button if env var missing

  function handleClick() {
    if (!window.google?.accounts?.id) return;
    setBusy(true);
    window.google.accounts.id.prompt((notification) => {
      // prompt cancelled or auto-select failed — busy state will be released
      // by the parent callback or user dismissal
      if (notification.isNotDisplayed() || notification.isSkippedMoment() || notification.isDismissedMoment()) {
        setBusy(false);
      }
    });
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      className={`btn-soft flex w-full items-center justify-center gap-2.5 !py-3 text-sm font-bold ${className}`}
      aria-label="ورود با گوگل"
    >
      <GoogleLogo />
      {busy ? "در حال اتصال به گوگل…" : label}
    </button>
  );
}
