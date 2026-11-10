// Store, bundle and package loading for the storefront (split out of App.jsx, T-R11).
import { useEffect, useState } from 'react';
import { publicGet } from './coreApi.ts';

export function useStoreCatalog(coreFetch, reloadKey) {
  const [catalog, setCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [bundles, setBundles] = useState([]);
  const [bundleId, setBundleId] = useState('');
  const [pkgLoading, setPkgLoading] = useState(false);
  const [apiState, setApiState] = useState('در حال اتصال به Core');
  const [storeId, setStoreId] = useState('');
  const [hasBot, setHasBot] = useState(false);
  useEffect(() => {
    setCatalogLoading(true);
    // A reseller's own domain shows that reseller's store; any other host (main domain, localhost) shows the main store.
    coreFetch(`/api/v1/stores/by-domain/${encodeURIComponent(window.location.hostname.toLowerCase())}`, {
      headers: { Accept: 'application/json' },
    })
      .then((r) => (r.ok ? r : coreFetch(`/api/v1/stores/main`, { headers: { Accept: 'application/json' } })))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((store) => {
        setStoreId(store.id);
        setHasBot(Boolean(store.bot_username));
        return publicGet(`/api/v1/stores/${store.id}/bundles`);
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : data.items || [];
        setBundles(list);
        setBundleId((cur) => (list.some((x) => x.id === cur) ? cur : list.length === 1 ? list[0].id : ''));
        setApiState('اتصال Core برقرار است');
      })
      .catch(() => {
        setBundles([]);
        setApiState('Core در دسترس نیست؛ سرویس‌ها موقتاً نمایش داده نمی‌شود');
      })
      .finally(() => setCatalogLoading(false));
  }, [reloadKey, coreFetch]);
  useEffect(() => {
    setCatalog([]);
    if (!storeId || !bundleId) return;
    let live = true;
    setPkgLoading(true);
    publicGet(`/api/v1/stores/${storeId}/bundles/${bundleId}/packages`)
      .then((data) => live && setCatalog(Array.isArray(data) ? data : data.items || []))
      .catch(() => live && setCatalog([]))
      .finally(() => live && setPkgLoading(false));
    return () => {
      live = false;
    };
  }, [storeId, bundleId, reloadKey]);
  return { catalog, catalogLoading, bundles, bundleId, setBundleId, pkgLoading, apiState, storeId, hasBot };
}
