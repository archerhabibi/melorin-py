// The storefront speaks in the STORE's own name (docs/06 ADR-R3). "Melorin" is the platform's name, never assumed to be a store's:
// the main store and every reseller's site show whatever their owner called them, taken from `GET /stores/by-domain/...` or
// `/stores/main`. Until that name is known (or when Core is down) the text stays neutral instead of borrowing the platform's.
import { createContext, useContext, useEffect } from 'react';

export const NEUTRAL_STORE_NAME = 'فروشگاه';
export const STORE_TAGLINE = 'سرویس VPN ساده و پایدار';

export type StoreBrand = { name: string; loading: boolean };

const StoreBrandContext = createContext<StoreBrand>({ name: NEUTRAL_STORE_NAME, loading: false });

export const StoreBrandProvider = StoreBrandContext.Provider;

export function useStoreBrand(): StoreBrand {
  return useContext(StoreBrandContext);
}

/** The name as received: a string with whitespace collapsed, else '' (older or mocked Core answers carry no name). */
export function cleanStoreName(raw: unknown): string {
  return typeof raw === 'string' ? raw.replace(/\s+/g, ' ').trim() : '';
}

/** The emblem letter: the first letter or digit of the name (upper-cased for Latin scripts), a dot when there is none. */
export function storeMonogram(name: string): string {
  const first = Array.from(name).find((ch) => /[\p{L}\p{N}]/u.test(ch));
  return first ? first.toLocaleUpperCase() : '•';
}

/** Page title and meta description in the store's name; the static HTML shell is neutral. */
export function useDocumentBrand({ name, loading }: StoreBrand): void {
  useEffect(() => {
    if (loading) return;
    document.title = `${name} | ${STORE_TAGLINE}`;
    document
      .querySelector('meta[name="description"]')
      ?.setAttribute('content', `${name}؛ خرید و تمدید سرویس VPN با کیف پول، تحویل خودکار و پشتیبانی تیکتی.`);
  }, [name, loading]);
}
