// ADR-R3: the storefront speaks in the STORE's own name, never in the platform's by assumption.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App.tsx';
import { Logo } from '../src/landing.tsx';
import { WhySection } from '../src/InfoSections.tsx';
import { SiteFooter } from '../src/SiteFooter.tsx';
import {
  NEUTRAL_STORE_NAME,
  StoreBrandProvider,
  cleanStoreName,
  storeMonogram,
  useDocumentBrand,
} from '../src/storeBrand.tsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** Core stub: `store` is what both store lookups answer (null = Core is down); everything else is a 404. */
function stubCore(store) {
  const calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input) => {
      const url = String(input?.url || input);
      calls.push(url);
      if (url.includes('/api/v1/stores/by-domain/') || url.endsWith('/api/v1/stores/main')) {
        return store ? json(store) : json({ detail: 'down' }, 503);
      }
      if (store && url.endsWith(`/api/v1/stores/${store.id}/bundles`)) return json([]);
      return json({ detail: 'not found' }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  window.location.hash = '';
  // jsdom does not load index.html: give the page the neutral description element the real shell has
  document.head.querySelector('meta[name="description"]')?.remove();
  const meta = document.createElement('meta');
  meta.name = 'description';
  meta.content = 'neutral';
  document.head.appendChild(meta);
});
afterEach(() => vi.unstubAllGlobals());

const noPlatformName = (root) => {
  expect(root.textContent).not.toMatch(/ملورین/);
  expect(root.textContent).not.toMatch(/melorin/i);
};

describe('store name helpers', () => {
  it('cleans a received name and ignores anything that is not a string', () => {
    expect(cleanStoreName('  Paris   VPN ')).toBe('Paris VPN');
    expect(cleanStoreName(undefined)).toBe('');
    expect(cleanStoreName(42)).toBe('');
  });

  it('takes the emblem from the first letter or digit of the name', () => {
    expect(storeMonogram('Paris VPN')).toBe('P');
    expect(storeMonogram('paris')).toBe('P');
    expect(storeMonogram('فروشگاه پارس')).toBe('ف');
    expect(storeMonogram('  «۲۴ ساعته»')).toBe('۲');
    expect(storeMonogram('— —')).toBe('•');
  });
});

describe('brand components', () => {
  const brand = (name, loading = false) => ({ name, loading });

  it('Logo, why-section and footer show the store name and never the platform name', () => {
    const { container } = render(
      <StoreBrandProvider value={brand('Paris VPN')}>
        <Logo />
        <WhySection />
        <SiteFooter />
      </StoreBrandProvider>,
    );
    expect(screen.getAllByText('Paris VPN').length).toBeGreaterThanOrEqual(2); // header-style logo + footer logo
    expect(screen.getByText('چرا Paris VPN؟')).toBeInTheDocument();
    expect(screen.getByText(/Paris VPN برای کسی ساخته شده/)).toBeInTheDocument();
    expect(screen.getAllByText(/©/)[0]).toHaveTextContent(/© \S+ Paris VPN · تمامی حقوق محفوظ است/);
    expect(screen.getAllByLabelText('Paris VPN؛ صفحه اصلی').length).toBeGreaterThan(0);
    noPlatformName(container);
  });

  it('without a name the text is neutral, not the platform name', () => {
    const { container } = render(
      <StoreBrandProvider value={brand(NEUTRAL_STORE_NAME)}>
        <Logo />
        <WhySection />
      </StoreBrandProvider>,
    );
    expect(screen.getByText('چرا فروشگاه؟')).toBeInTheDocument();
    noPlatformName(container);
  });

  it('shows a placeholder, not a wrong name, while the store is loading', () => {
    const { container } = render(
      <StoreBrandProvider value={brand(NEUTRAL_STORE_NAME, true)}>
        <Logo />
      </StoreBrandProvider>,
    );
    expect(within(container).queryByText(NEUTRAL_STORE_NAME)).toBeNull();
    expect(container.querySelector('.animate-pulse')).not.toBeNull();
  });

  it('writes the page title and description in the store name, and waits while loading', () => {
    const Probe = ({ value }) => {
      useDocumentBrand(value);
      return null;
    };
    document.title = 'before';
    const { rerender } = render(<Probe value={brand('Paris VPN', true)} />);
    expect(document.title).toBe('before');
    rerender(<Probe value={brand('Paris VPN')} />);
    expect(document.title).toMatch(/^Paris VPN \| /);
  });
});

describe('storefront App', () => {
  it("renders the store's own name from Core: header, title and the sign-in dialog", async () => {
    stubCore({ id: 's1', name: 'Tehran Net', bot_username: null });
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getAllByText('Tehran Net').length).toBeGreaterThan(0));
    expect(document.title).toMatch(/^Tehran Net \| /);
    expect(document.querySelector('meta[name="description"]').getAttribute('content')).toContain('Tehran Net');

    await userEvent.click(screen.getAllByRole('button', { name: /ورود/ })[0]);
    expect(await screen.findByRole('dialog')).toHaveTextContent('ورود به Tehran Net');
    noPlatformName(container);
  });

  it('falls back to a neutral name when Core knows the store but sent no name', async () => {
    stubCore({ id: 's1', bot_username: null });
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getAllByText(NEUTRAL_STORE_NAME).length).toBeGreaterThan(0));
    noPlatformName(container);
  });

  it('stays neutral when Core is down', async () => {
    stubCore(null);
    const { container } = render(<App />);
    expect(await screen.findByText(/Core در دسترس نیست/)).toBeInTheDocument();
    expect(screen.getAllByText(NEUTRAL_STORE_NAME).length).toBeGreaterThan(0);
    noPlatformName(container);
  });
});
