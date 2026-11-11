export function configureGoogleSignIn(opts: { surface: 'admin' | 'store'; apiBase?: string; envClientId?: string }): void;
export function useGoogleConfig(): { client_id?: string; enabled?: boolean; [k: string]: unknown } | null;
export function googleSignOut(): void;
export function GoogleSignInButton(props: {
  onCredential: (idToken: string) => void | Promise<void>;
  text?: 'continue_with' | 'signin_with' | 'signup_with';
  disabled?: boolean;
  className?: string;
}): JSX.Element | null;
