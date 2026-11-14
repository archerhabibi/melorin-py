import type { ReactNode } from 'react';
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { getAccessToken, setTokens } from './auth.ts';
import AdminAuth from './AdminAuth.tsx';
import AcceptInvite, { isInviteHash } from './AcceptInvite.tsx';
import '@melorin/web-kit/tokens.css';
import './styles.css';
import './theme.ts';
import type { Json } from './types.ts';

class AdminErrorBoundary extends React.Component<{ children?: React.ReactNode }, { error: Json }> {
  constructor(props: Json) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Json) {
    return { error };
  }
  componentDidCatch(error: Json, info: Json) {
    console.error('admin-ui-error', error, info);
  }
  render() {
    if (this.state.error)
      return (
        <main dir="rtl" className="grid min-h-screen place-items-center bg-[var(--nav)] p-6">
          <section className="card max-w-lg p-8 text-center">
            <h1 className="text-2xl font-extrabold">بخشی از پنل ادمین با خطا مواجه شد</h1>
            <p className="mt-3 text-sm leading-7 text-[var(--mu)]">
              صفحه را دوباره بارگذاری کنید. نشست شما حفظ می‌شود.
            </p>
            <button className="btn mt-5" onClick={() => window.location.reload()}>
              بارگذاری دوباره
            </button>
          </section>
        </main>
      );
    return this.props.children;
  }
}

function Root() {
  // An admin invitation opens this page from an e-mail: it needs no session and must never trigger a refresh or a sign-in screen.
  const [invite, setInvite] = useState(() => isInviteHash(window.location.hash));
  React.useEffect(() => {
    const f = () => setInvite(isInviteHash(window.location.hash));
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  const [signedIn, setSignedIn] = useState(() => Boolean(getAccessToken()));
  const [checking, setChecking] = useState(() => !getAccessToken());
  const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
  React.useEffect(() => {
    if (getAccessToken()) return setChecking(false);
    fetch(`${base}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: '{}',
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((pair) => {
        setTokens(pair);
        setSignedIn(true);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [base]);
  if (invite) return <AcceptInvite base={base} />;
  if (checking)
    return (
      <main className="grid min-h-screen place-items-center bg-[var(--nav)] text-white/80">
        <div className="skel h-2 w-40" aria-label="در حال بررسی نشست" />
      </main>
    );
  return signedIn ? (
    <App onLogout={() => setSignedIn(false)} />
  ) : (
    <AdminAuth base={base} onSuccess={() => setSignedIn(true)} />
  );
}

createRoot(document.getElementById('root')!).render(
  <AdminErrorBoundary>
    <Root />
  </AdminErrorBoundary>,
);
