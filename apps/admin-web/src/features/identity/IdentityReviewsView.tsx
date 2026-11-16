import { useMemo, useState } from 'react';
import { CheckCircle2, Fingerprint, Inbox, ShieldCheck, Users } from 'lucide-react';
import { typedClient, useCall } from '../../api/api.ts';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, SortSelect, Stat, errText, useRows } from '../../shared/kit.tsx';
import type { Json, Toast } from '../../shared/types.ts';
import { PROVIDERS, ReviewCard } from './IdentityReviewParts';
import { ReviewDrawer } from './IdentityReviewDrawer';

export default function IdentityReviewsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/identity-link-reviews?status=all');
  const [status, setStatus] = useState('open');
  const [provider, setProvider] = useState('all');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('new');
  const [sel, setSel] = useState<Json>(null);

  const all = (rows || []).filter((r) => !r.auto);
  const count = (f: Json) => all.filter(f).length;
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = all.filter(
      (r) =>
        (status === 'all' || r.status === status) &&
        (provider === 'all' || r.provider === provider) &&
        (!t ||
          [
            r.email,
            r.reason,
            r.source_user?.display_name,
            r.source_user?.email,
            ...(r.candidates || []).flatMap((c: Json) => [c.display_name, c.email]),
          ].some((x) =>
            String(x || '')
              .toLowerCase()
              .includes(t),
          )),
    );
    return list.sort(
      (a, b) => (sort === 'new' ? -1 : 1) * (new Date(a.created_at).getTime() - new Date(b.created_at).getTime()),
    );
  }, [all, status, provider, q, sort]);

  const quick = async (r: Json) => {
    const { response: res } = await typedClient(api.base).post(
      '/api/v1/admin/identity-link-reviews/{review_id}/dismiss',
      {
        params: { path: { review_id: r.id } },
      },
    );
    if (res.ok) {
      toast('درخواست رد شد');
      load();
    } else toast(await errText(res, 'ناموفق'));
  };
  const done = () => {
    setSel(null);
    load();
  };
  const current = sel && all.find((r) => r.id === sel.id);

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="در انتظار تصمیم"
          value={count((r: Json) => r.status === 'open')}
          tone="wn"
          Icon={Inbox}
          active={status === 'open'}
          onClick={() => setStatus('open')}
          sub="نیازمند بررسی دستی"
        />
        <Stat
          label="رد شده"
          value={count((r: Json) => r.status === 'dismissed')}
          tone="mu"
          Icon={CheckCircle2}
          active={status === 'dismissed'}
          onClick={() => setStatus('dismissed')}
        />
        <Stat
          label="متصل شده"
          value={count((r: Json) => r.status === 'linked')}
          tone="ok"
          Icon={Users}
          active={status === 'linked'}
          onClick={() => setStatus('linked')}
        />
        <Stat
          label="همه موارد"
          value={all.length}
          tone="in"
          Icon={Fingerprint}
          active={status === 'all'}
          onClick={() => setStatus('all')}
        />
      </KpiBar>
      <div className="tool">
        <SearchBox value={q} onChange={setQ} label="جستجو در موارد" placeholder="ایمیل، نام یا دلیل…" />
        <Pills
          label="ارائه‌دهنده"
          value={provider}
          onChange={setProvider}
          options={[
            ['all', 'همه', all.length],
            ...Object.entries(PROVIDERS).map(([k, v]) => [k, v.label, count((r: Json) => r.provider === k)]),
          ]}
        />
        <span className="mr-auto" />
        <SortSelect
          value={sort}
          onChange={setSort}
          options={[
            ['new', 'جدیدترین'],
            ['old', 'قدیمی‌ترین'],
          ]}
        />
      </div>
      <p className="px-1 text-xs leading-6 text-[var(--mu)]">
        اگر یکی از دو حساب خالی باشد، سیستم خودش ادغام می‌کند (تب «انجام‌شده خودکار»). وقتی هر دو حساب سابقه دارند، هرگز
        ادغام خودکار انجام نمی‌شود و مورد اینجا برای تصمیم شما می‌ماند.
      </p>
      {failed && <ErrorBar onRetry={load}>دریافت فهرست ناموفق بود.</ErrorBar>}
      {rows === null ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skel h-44" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <Empty
          Icon={ShieldCheck}
          title={status === 'open' && !q && provider === 'all' ? 'صف بررسی خالی است' : 'موردی پیدا نشد'}
          text={
            status === 'open' && !q && provider === 'all'
              ? 'هیچ تعارض هویتی منتظر تصمیم شما نیست.'
              : 'فیلتر یا عبارت جستجو را تغییر دهید.'
          }
        />
      ) : (
        <div className="grid gap-3">
          {shown.map((r) => (
            <ReviewCard key={r.id} r={r} onOpen={setSel} onQuick={quick} />
          ))}
        </div>
      )}
      {current && (
        <ReviewDrawer
          key={current.id + current.status}
          r={current}
          call={call}
          base={api.base}
          toast={toast}
          onClose={() => setSel(null)}
          onDone={done}
        />
      )}
    </div>
  );
}
