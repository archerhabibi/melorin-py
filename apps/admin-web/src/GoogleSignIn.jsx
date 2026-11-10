// GoogleSignIn.jsx — thin per-app binding of the shared Google sign-in (packages/web-kit, T14).
import { configureGoogleSignIn } from '@melorin/web-kit/GoogleSignIn.jsx';

configureGoogleSignIn({
  surface: 'admin',
  apiBase: import.meta.env?.VITE_MELORIN_API_URL || window.location.origin,
  envClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
});

export { useGoogleConfig, googleSignOut, GoogleSignInButton } from '@melorin/web-kit/GoogleSignIn.jsx';
