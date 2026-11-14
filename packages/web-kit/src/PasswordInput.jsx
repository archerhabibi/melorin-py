// PasswordInput.jsx — password field with an eye toggle, shared by admin-web and store-web.
// Icons are inline SVG (lucide shapes) so web-kit needs no icon dependency of its own.
import { useState } from 'react';

const Svg = (props) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props} />
);
const Eye = () => (
  <Svg>
    <path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);
const EyeOff = () => (
  <Svg>
    <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c4.5 0 8.3 2.9 9.94 7a10.8 10.8 0 0 1-1.67 2.68" />
    <path d="M6.61 6.61A10.7 10.7 0 0 0 2.06 12c1.64 4.1 5.44 7 9.94 7a10.4 10.4 0 0 0 5.39-1.61" />
    <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
    <path d="m2 2 20 20" />
  </Svg>
);

/** Extra props go to the <input>. */
export function PasswordInput({ className = '', wrapClassName = '', ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div className={`relative ${wrapClassName}`}>
      <input {...props} dir="ltr" type={show ? 'text' : 'password'} className={`${className} !pl-10`} />
      <button
        type="button"
        aria-label={show ? 'پنهان‌کردن رمز' : 'نمایش رمز'}
        title={show ? 'پنهان‌کردن' : 'نمایش'}
        className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--mu)]"
        onClick={() => setShow((v) => !v)}
      >
        {show ? <EyeOff /> : <Eye />}
      </button>
    </div>
  );
}
