import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Loading, PageTitle } from './ui.jsx';
import Pricing from './ResellerPricing.jsx';
import Broadcast from './ResellerBroadcast.jsx';
import EventCenter from './ResellerEventCenter.jsx';
import ResellerReferral from './ResellerReferral.jsx';
import ResellerLoyalty from './ResellerLoyalty.jsx';
import ResellerCoupons from './ResellerCoupons.jsx';
import ResellerPanelAdmin from './ResellerPanelAdmin.jsx';
import ResellerUsage from './ResellerUsage.jsx';
import ResellerSubBranding from './ResellerSubBranding.jsx';
import BankSms from './ResellerBankSms.jsx';
import { OwnerAccounts, Overview, Customers, Payments } from './reseller/ResellerData.jsx';
import { Keys, Hooks } from './reseller/ResellerSecurity.jsx';
import { Branding, PayConfig } from './reseller/ResellerSettings.jsx';
import { Apply, tabs } from './reseller/ResellerApply.jsx';

export default function Reseller({ coreFetch, notify }) {
  const [stores, setStores] = useState(null);
  const [tab, setTab] = useState('overview');
  const pricingDirty = useRef(false); // unsaved price edits: leaving the tab would silently drop them
  const go = (k) => {
    if (
      tab === 'pricing' &&
      k !== 'pricing' &&
      pricingDirty.current &&
      !window.confirm('تغییرات قیمت ذخیره نشده است. بدون ذخیره خارج می‌شوید؟')
    )
      return;
    setTab(k);
  };
  useEffect(() => {
    coreFetch('/api/v1/me/stores')
      .then((r) => (r.ok ? r.json() : []))
      .then(setStores)
      .catch(() => setStores([]));
  }, [coreFetch]);
  const mine = (stores || []).find((s) => s.kind === 'reseller' && s.role === 'owner');
  const base = mine ? `/api/v1/stores/${mine.id}/reseller` : '';
  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <PageTitle eyebrow="پنل نماینده" title={mine?.name || 'فروش همکاری'}>
        <a href="#/dashboard" className="btn-soft btn-pill !py-2.5">
          <ArrowRight size={16} />
          حساب من
        </a>
      </PageTitle>
      {stores === null ? (
        <Loading rows={2} />
      ) : !mine ? (
        <Apply coreFetch={coreFetch} notify={notify} stores={stores} />
      ) : (
        <div className="grid gap-8 md:grid-cols-[220px_1fr]">
          <nav
            aria-label="بخش‌های پنل نماینده"
            className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 md:sticky md:top-24 md:mx-0 md:h-fit md:flex-col md:gap-1 md:overflow-visible md:px-0"
          >
            {tabs.map(([k, l, Icon]) => (
              <button
                key={k}
                onClick={() => go(k)}
                aria-current={tab === k}
                className={`flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-4 py-3 text-sm font-bold transition ${tab === k ? 'bg-primary text-onprimary shadow-soft' : 'text-muted hover:bg-surface2 hover:text-ink'}`}
              >
                <Icon size={18} />
                {l}
              </button>
            ))}
          </nav>
          <section className="min-w-0">
            {tab === 'overview' && <Overview coreFetch={coreFetch} base={base} />}
            {tab === 'pricing' && <Pricing coreFetch={coreFetch} base={base} notify={notify} dirtyRef={pricingDirty} />}
            {tab === 'coupons' && (
              <ResellerCoupons coreFetch={coreFetch} storeId={mine.id} notify={notify} currency={mine.currency} />
            )}
            {tab === 'referral' && (
              <ResellerReferral coreFetch={coreFetch} storeId={mine.id} notify={notify} currency={mine.currency} />
            )}
            {tab === 'loyalty' && (
              <ResellerLoyalty coreFetch={coreFetch} storeId={mine.id} notify={notify} currency={mine.currency} />
            )}
            {tab === 'customers' && <Customers coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'accounts' && <OwnerAccounts coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'broadcast' && <Broadcast coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'events' && <EventCenter coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'payments' && <Payments coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'banksms' && <BankSms coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'keys' && <Keys coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'hooks' && <Hooks coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'paneladmin' && (
              <div className="space-y-4">
                <ResellerPanelAdmin coreFetch={coreFetch} base={base} notify={notify} />
                <ResellerSubBranding coreFetch={coreFetch} base={base} notify={notify} />
              </div>
            )}
            {tab === 'usage' && <ResellerUsage coreFetch={coreFetch} base={base} notify={notify} />}
            {tab === 'settings' && (
              <div className="space-y-4">
                <Branding coreFetch={coreFetch} base={base} storeId={mine.id} notify={notify} />
                <PayConfig coreFetch={coreFetch} base={base} notify={notify} />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
