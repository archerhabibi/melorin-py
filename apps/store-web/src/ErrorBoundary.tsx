import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = { children: ReactNode; onRetry?: () => void };

/** Keep a rendering failure from leaving the storefront with a blank page. */
export class StoreErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Store rendering failed', error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const retry = this.props.onRetry ?? (() => window.location.reload());
    return (
      <main dir="rtl" role="alert" className="grid min-h-screen place-items-center p-6">
        <section className="max-w-lg text-center">
          <h1 className="text-2xl font-extrabold">مشکلی در نمایش صفحه پیش آمد</h1>
          <p className="mt-3 text-sm leading-7">صفحه را دوباره بارگذاری کنید و وضعیت پرداخت خود را بررسی کنید.</p>
          <button type="button" className="btn-primary mt-5" onClick={retry}>
            بارگذاری دوباره
          </button>
        </section>
      </main>
    );
  }
}
