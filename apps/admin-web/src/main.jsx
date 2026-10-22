import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { getAccessToken, setTokens } from './auth.js';
import AdminAuth from './AdminAuth.jsx';
import './styles.css';
import './theme.js';

class AdminErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
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

createRoot(document.getElementById('root')).render(
  <AdminErrorBoundary>
    <Root />
  </AdminErrorBoundary>,
);
