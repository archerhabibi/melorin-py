import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { getAccessToken, setTokens } from './auth.js';
import AdminAuth from './AdminAuth.jsx';
import './styles.css';
import './theme.js';

function Root() {
  const [signedIn, setSignedIn] = useState(() => Boolean(getAccessToken()));
  const [checking, setChecking] = useState(() => !getAccessToken());
  const base = (import.meta.env?.VITE_MELORIN_API_URL || window.location.origin).replace(/\/$/, '');
  React.useEffect(() => {
    if (getAccessToken()) return setChecking(false);
    fetch(`${base}/api/v1/auth/refresh`, { method: "POST", headers: {"Content-Type":"application/json"}, credentials: "include", body: "{}" })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(pair => { setTokens(pair); setSignedIn(true); })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [base]);
  if (checking) return <main className="grid min-h-screen place-items-center bg-[var(--nav)] text-white/80"><div className="skel h-2 w-40" aria-label="در حال بررسی نشست" /></main>;
  return signedIn
    ? <App onLogout={() => setSignedIn(false)} />
    : <AdminAuth base={base} onSuccess={() => setSignedIn(true)} />;
}

createRoot(document.getElementById('root')).render(<Root />);
