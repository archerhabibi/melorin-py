// GoogleSignIn.jsx — "Sign in with Google" for store-web (Google Identity Services, ID-token flow).
//
// Follows Google's official guidance (developers.google.com/identity/gsi/web):
//  - the button is Google's own, rendered by google.accounts.id.renderButton (never a hand-made lookalike), so it
//    always carries the correct logo, colours, typography, localisation and Google's own error messages;
//  - google.accounts.id.initialize() runs once per page with a server-issued nonce: the ID token is bound to this
//    browser (GET /api/v1/auth/google/nonce) and verified server-side;
//  - the button follows the app theme (outline on light, filled_black on dark), is 200–400px wide, and keeps its
//    reserved size while loading so the layout does not jump.
// This file is identical in admin-web and store-web except for SURFACE.

import { useCallback, useEffect, useRef, useState } from "react";

const ENV_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ""; // legacy build-time fallback
const API_BASE = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, "");
const SURFACE = "store"; // which login surface this app is: its toggle lives in Admin > Settings > Google
const GSI_SRC = "https://accounts.google.com/gsi/client";
const NONCE_REFRESH_MS = 8 * 60 * 1000; // the server-side nonce cookie lives 10 minutes
const MIN_W = 200; // Google: button width must be 200–400px
const MAX_W = 400;
const BTN_H = 40; // height of Google's "large" button

/* ───────────────────────────── runtime config ───────────────────────────── */

// The Client ID is configured at runtime in the admin panel (Settings > Google login); no rebuild is needed.
// One shared request per page load. If Core is unreachable we fall back to the build-time env value.
let configPromise = null;
function loadConfig() {
  if (!configPromise) {
    configPromise = fetch(`${API_BASE}/api/v1/auth/google/config`, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("config"))))
      .catch(() => ({ enabled: !!ENV_CLIENT_ID, client_id: ENV_CLIENT_ID, admin_login: true, store_login: true }));
  }
  return configPromise;
}

/** Returns { client_id } when Google sign-in is on for this app, otherwise null. */
export function useGoogleConfig() {
  const [cfg, setCfg] = useState(null);
  useEffect(() => {
    let alive = true;
    loadConfig().then((c) => { if (alive) setCfg(c); });
    return () => { alive = false; };
  }, []);
  return cfg && cfg.enabled && cfg.client_id && cfg[`${SURFACE}_login`] !== false ? cfg : null;
}

/* ───────────────────────────── GIS loader / initialiser ───────────────────────────── */

let gsiPromise = null;
function loadGsi() {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!gsiPromise) {
    gsiPromise = new Promise((resolve, reject) => {
      let s = document.querySelector("script[data-gsi]");
      const fail = () => { s?.remove(); gsiPromise = null; reject(new Error("gsi_load")); };
      if (!s) {
        s = document.createElement("script");
        s.src = GSI_SRC; s.async = true; s.defer = true; s.dataset.gsi = "1";
        document.head.appendChild(s);
      }
      const timer = setTimeout(fail, 15000);
      s.addEventListener("load", () => { clearTimeout(timer); window.google?.accounts?.id ? resolve() : fail(); }, { once: true });
      s.addEventListener("error", () => { clearTimeout(timer); fail(); }, { once: true });
    });
  }
  return gsiPromise;
}

async function fetchNonce() {
  const r = await fetch(`${API_BASE}/api/v1/auth/google/nonce`, { credentials: "include", cache: "no-store", headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("nonce");
  const { nonce } = await r.json();
  if (!nonce) throw new Error("nonce");
  return nonce;
}

// Module-level state: GIS is initialised once per page (calling initialize() repeatedly makes Google log warnings).
// `handlers` is the stack of mounted buttons' callbacks (the most recently mounted one receives the credential), so we
// also know whether to re-arm a fresh nonce after a sign-in attempt consumed the previous one.
const gis = { key: "", ready: null, handlers: [], epoch: 0 };

function forget() { gis.key = ""; gis.ready = null; }

function onGoogleCredential(response) {
  const h = gis.handlers.at(-1);
  if (!h || !response?.credential) return;
  Promise.resolve(h(response.credential)).catch(() => {}).finally(() => {
    // A successful sign-in consumes the nonce cookie and a failed one may have too: arm a fresh nonce.
    forget();
    if (gis.handlers.length > 0) window.dispatchEvent(new Event("melorin:gsi-rearm"));
  });
}

/** Resolves once google.accounts.id is initialised for this Client ID with a fresh nonce. */
function prepare(clientId) {
  if (gis.ready && gis.key === clientId) return gis.ready;
  gis.key = clientId;
  const epoch = ++gis.epoch;
  gis.ready = Promise.all([loadGsi(), fetchNonce()]).then(([, nonce]) => {
    if (epoch !== gis.epoch) return; // superseded by a newer prepare()
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: onGoogleCredential,
      nonce,
      ux_mode: "popup",
      auto_select: false,
      cancel_on_tap_outside: true,
      itp_support: true,
    });
  }).catch((e) => { if (epoch === gis.epoch) forget(); throw e; });
  return gis.ready;
}

/** Call on sign-out so Google does not silently re-select the previous account next time. */
export function googleSignOut() {
  try { window.google?.accounts?.id?.disableAutoSelect(); } catch { /* GIS not loaded: nothing to do */ }
}

/* ───────────────────────────── hooks ───────────────────────────── */

function useColorScheme() {
  const read = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  const [scheme, setScheme] = useState(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setScheme(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return scheme;
}

function useWidth(ref, active) {
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return undefined;
    const clamp = (v) => Math.min(MAX_W, Math.max(MIN_W, Math.floor(v || MAX_W)));
    setW(clamp(el.getBoundingClientRect().width));
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setW((prev) => { const n = clamp(e.contentRect.width); return n === prev ? prev : n; }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, active]);
  return w;
}

/* ───────────────────────────── component ───────────────────────────── */

/**
 * Google's official sign-in button.
 *  - onCredential(idToken): called with the Google ID token (may be async; the button is re-armed afterwards).
 *  - text: "continue_with" (sign in or sign up, default) | "signin_with" | "signup_with" — Google localises the label.
 *  - disabled: dims the button and blocks clicks while the host form is busy or not ready.
 */
export function GoogleSignInButton({ onCredential: handler, text = "continue_with", disabled = false, className = "" }) {
  const cfg = useGoogleConfig();
  const scheme = useColorScheme();
  const wrap = useRef(null);
  const holder = useRef(null);
  const width = useWidth(wrap, !!cfg);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [attempt, setAttempt] = useState(0);
  const cb = useRef(handler);
  cb.current = handler;
  const clientId = cfg?.client_id || "";

  // While mounted, this button owns the shared GIS callback and keeps the nonce fresh.
  useEffect(() => {
    if (!clientId) return undefined;
    const mine = (token) => cb.current(token);
    gis.handlers.push(mine);
    const rearm = () => setAttempt((n) => n + 1);
    window.addEventListener("melorin:gsi-rearm", rearm);
    const timer = setInterval(() => { forget(); rearm(); }, NONCE_REFRESH_MS);
    return () => {
      gis.handlers = gis.handlers.filter((h) => h !== mine);
      window.removeEventListener("melorin:gsi-rearm", rearm); clearInterval(timer);
    };
  }, [clientId]);

  useEffect(() => {
    if (!clientId || !width || !holder.current) return undefined;
    let dead = false;
    prepare(clientId).then(() => {
      if (dead || !holder.current) return;
      holder.current.replaceChildren();
      window.google.accounts.id.renderButton(holder.current, {
        type: "standard", size: "large", shape: "rectangular", logo_alignment: "left", locale: "fa",
        theme: scheme === "dark" ? "filled_black" : "outline", text, width,
      });
      setStatus("ready");
    }).catch(() => { if (!dead) setStatus("error"); });
    return () => { dead = true; };
  }, [clientId, width, scheme, text, attempt]);

  const retry = useCallback(() => { forget(); setStatus("loading"); setAttempt((n) => n + 1); }, []);

  if (!cfg) return null;
  const dark = scheme === "dark";
  return (
    <div ref={wrap} role="group" aria-label="ورود با گوگل" aria-busy={status === "loading"} className={className}>
      {status !== "error" ? (
        <div className="relative mx-auto" style={{ width: width || "100%", maxWidth: MAX_W, minHeight: BTN_H }}>
          {status === "loading" && (
            <div aria-hidden className="absolute inset-0 animate-pulse" style={{ height: BTN_H, borderRadius: 4, background: dark ? "rgba(255,255,255,.10)" : "rgba(0,0,0,.06)" }} />
          )}
          <div
            ref={holder} dir="ltr" aria-disabled={disabled || undefined}
            // Google's button is an iframe: pin its colour-scheme to the theme we asked for, otherwise a mismatch with the
            // page paints an opaque box around the button.
            style={{ colorScheme: scheme, opacity: disabled ? 0.55 : 1, pointerEvents: disabled ? "none" : "auto", transition: "opacity .15s" }}
          />
        </div>
      ) : (
        <div role="alert" className="text-center text-xs leading-6" style={{ borderRadius: 12, padding: 12, color: dark ? "#f28b82" : "#d93025", background: dark ? "rgba(242,139,130,.10)" : "rgba(217,48,37,.07)", border: `1px solid ${dark ? "rgba(242,139,130,.3)" : "rgba(217,48,37,.25)"}` }}>
          بارگذاری ورود با گوگل انجام نشد. اتصال اینترنت یا افزونه‌ی مرورگر را بررسی کنید.
          <button type="button" onClick={retry} className="mx-auto mt-1 block font-bold underline">تلاش دوباره</button>
        </div>
      )}
    </div>
  );
}
