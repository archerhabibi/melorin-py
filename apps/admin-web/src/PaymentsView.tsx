// Payments screen — review queue, KPIs, filters, detail drawer and gateway settings.
// Data comes only from GET /api/v1/admin/payments (+ /settings); actions use the existing
// /review, /refund and /receipt endpoints, so no backend change is required.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Clock, Download, RefreshCw, ShieldAlert, TrendingUp, Undo2, Wallet, XCircle } from 'lucide-react';
import type { RequestBody } from '@melorin/api-client';
import { authFetch, typedClient } from './api.ts';
import { Empty, ErrorBar, KpiBar, Paginator, Pills, SearchBox, Stat, errText, num } from './kit.tsx';
import { Badge, confirmDialog, dt, promptDialog, sid } from './ui.tsx';
import BankSmsPanel from './BankSmsPanel.tsx';
import ReceiptOcrSettings from './ReceiptOcrSettings.tsx';

import { PAGE, prov, cur, reviewable, FILTERS, ago, sumBy, Metric, ProviderChip, Amount } from './paymentsShared.tsx';
import { RowActions, Queue, PaymentDrawer, GatewaySettings } from './PaymentParts.tsx';
import type { Json, Rec, Toast } from './types.ts';

type DestinationBody = RequestBody<'/api/v1/admin/payment-destinations/{provider}', 'put'>;

export default function PaymentsView({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCallback((p: Json, o = {}) => authFetch(api.base, p, o), [api.base]);
  const client = useMemo(() => typedClient(api?.base), [api?.base]);
  const [rows, setRows] = useState<Json>(null);
  const [failed, setFailed] = useState(false);
  const [settings, setSettings] = useState<Rec>({});
  const [tab, setTab] = useState('all');
  const [provider, setProvider] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState<Json>(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const { data: d, response } = await client.get('/api/v1/admin/payments');
      if (!response.ok) throw 0;
      setRows(Array.isArray(d) ? d : (d as Json)?.items || []);
      setFailed(false);
    } catch {
      setFailed(true);
      setRows((x: Json) => x || []);
    }
  }, [client]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    // main store destinations: the same per-store model resellers use (card number / holder / bank, Zarinpal merchant id + sandbox)
    client
      .get('/api/v1/admin/payment-destinations')
      .then((r) => (r.data as Json[] | undefined) ?? [])
      .then((rows: Json[]) =>
        setSettings({
          manual_card: rows.find((x) => x.provider === 'manual_card')?.public_config,
          zarinpal: (() => {
            const z = rows.find((x) => x.provider === 'zarinpal');
            return z && { merchant_id: z.merchant_id || '', sandbox: !!z.public_config?.sandbox };
          })(),
        }),
      )
      .catch(() => {});
  }, [call]);
  useEffect(() => setPage(0), [tab, provider, q]);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  const all = rows || [];
  const loading = rows === null;
  const counts = useMemo(
    () => Object.fromEntries(Object.entries(FILTERS).map(([k, f]) => [k, all.filter(f).length])),
    [all],
  );
  const providers = useMemo(() => [...new Set(all.map((p: Json) => p.provider))], [all]);
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return all.filter(
      (p: Json) =>
        (FILTERS as Rec)[tab](p) &&
        (!provider || p.provider === provider) &&
        (!s ||
          [p.id, p.user_id, p.store_id, p.provider, p.currency, String(p.amount)].some((v) =>
            String(v || '')
              .toLowerCase()
              .includes(s),
          )),
    );
  }, [all, tab, provider, q]);
  const pageRows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const queue = all.filter(reviewable);
  const ok = all.filter(FILTERS.succeeded);
  const bad = all.filter(FILTERS.failed);
  const rate = ok.length + bad.length ? ok.length / (ok.length + bad.length) : null;
  const filtering = !!(q || provider || tab !== 'all');

  // Review and refund are typed calls (literal path each, so the schema checks the body); the client consumes the
  // response body, so a failure's message comes from the parsed `error`.
  const run = async (
    p: Json,
    send: (id: string) => Promise<{ response: Response; error?: unknown }>,
    okMsg: Json,
    failMsg: Json,
  ) => {
    setBusy(p.id);
    try {
      const { response: r, error } = await send(String(p.id));
      if (r.ok) {
        toast(okMsg);
        await load();
        setSel(null);
      } else {
        const e = (error ?? {}) as { error?: { message?: string }; detail?: unknown };
        toast(e.error?.message || (typeof e.detail === 'string' ? e.detail : '') || failMsg);
      }
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };
  const review = (approve: boolean, reason: string) => (id: string) =>
    client.post('/api/v1/admin/payments/{payment_id}/review', {
      params: { path: { payment_id: id } },
      body: { approve, reason },
    });
  const refund = (reason: string) => (id: string) =>
    client.post('/api/v1/admin/payments/{payment_id}/refund', {
      params: { path: { payment_id: id } },
      body: { reason },
    });
  const on = {
    approve: async (p: Json) => {
      if (
        await confirmDialog(
          `پرداخت ${num(p.amount)} ${cur(p.currency)} تأیید شود؟ اعتبار یا سفارش مرتبط فعال خواهد شد.`,
          { title: 'تأیید پرداخت', ok: 'تأیید پرداخت' },
        )
      )
        run(p, review(true, ''), 'پرداخت تأیید شد', 'تأیید ناموفق بود');
    },
    reject: async (p: Json) => {
      const reason = await promptDialog('دلیل رد این پرداخت را بنویسید.', { title: 'رد پرداخت', ok: 'رد پرداخت' });
      if (reason !== null) run(p, review(false, reason), 'پرداخت رد شد', 'رد پرداخت ناموفق بود');
    },
    refund: async (p: Json) => {
      const reason = await promptDialog(
        `استرداد واقعی ${num(p.amount)} ${cur(p.currency)} انجام می‌شود. دلیل را بنویسید.`,
        { title: 'استرداد پرداخت', ok: 'استرداد' },
      );
      if (reason !== null)
        run(p, refund(reason || 'درخواست استرداد توسط Admin'), 'استرداد ثبت شد', 'استرداد ناموفق بود');
    },
    receipt: async (p: Json) => {
      try {
        const r = await call(`/api/v1/admin/payments/${p.id}/receipt`);
        if (!r.ok) return toast('نمایش رسید ناموفق بود');
        const url = URL.createObjectURL(await r.blob());
        window.open(url, '_blank', 'noopener');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch {
        toast('ارتباط با سرور برقرار نشد');
      }
    },
  };
  const saveSetting = async (provider: string, value: Json) => {
    const body =
      provider === 'zarinpal'
        ? {
            is_enabled: true,
            public_config: { sandbox: !!value.sandbox },
            secret: { merchant_id: value.merchant_id.trim() },
          }
        : { is_enabled: true, public_config: value };
    try {
      const { response: r } = await client.put('/api/v1/admin/payment-destinations/{provider}', {
        params: { path: { provider } },
        // the OpenAPI schema renders free-form objects as Record<string, never>; the server validates the real shape
        body: body as unknown as DestinationBody,
      });
      if (r.ok) {
        toast('تنظیمات ذخیره شد');
        setSettings((x) => ({ ...x, [provider]: value }));
      } else toast(await errText(r, 'ذخیره تنظیمات ناموفق بود'));
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
  };
  const exportCsv = () => {
    const head = ['id', 'user_id', 'store_id', 'provider', 'amount', 'currency', 'status', 'has_receipt', 'created_at'];
    const esc = (v: Json) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [head.join(','), ...filtered.map((p: Json) => head.map((k) => esc(p[k])).join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `payments-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  };
  const open = sel && all.find((p: Json) => p.id === sel);
  const toggle = (k: Json) => setTab(tab === k ? 'all' : k);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold">پرداخت‌ها</h2>
          <p className="mt-1 text-xs text-[var(--mu)]">
            بررسی رسیدها، پیگیری تراکنش‌ها و مدیریت درگاه‌ها · {num(all.length)} پرداخت اخیر
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-g !py-2" onClick={load}>
            <RefreshCw size={14} />
            به‌روزرسانی
          </button>
          <button className="btn btn-g !py-2" disabled={!filtered.length} onClick={exportCsv}>
            <Download size={14} />
            خروجی CSV
          </button>
        </div>
      </div>

      <KpiBar cols={4}>
        <Metric
          Icon={TrendingUp}
          tone="ok"
          label="دریافتی موفق"
          value={sumBy(ok)}
          sub={`${num(ok.length)} تراکنش`}
          loading={loading}
        />
        <Stat
          label="منتظر بررسی"
          value={counts.review}
          tone={counts.review ? 'wn' : 'mu'}
          Icon={Clock}
          sub={counts.review ? sumBy(queue) : 'صف خالی است'}
          active={tab === 'review'}
          onClick={() => toggle('review')}
        />
        <Stat
          label="ناموفق"
          value={counts.failed}
          tone={counts.failed ? 'bd' : 'mu'}
          Icon={XCircle}
          sub={rate === null ? undefined : `نرخ موفقیت ${num(Math.round(rate * 100))}٪`}
          ring={rate === null ? undefined : rate}
          active={tab === 'failed'}
          onClick={() => toggle('failed')}
        />
        <Stat
          label="مسترد / لغو"
          value={counts.closed}
          tone="in"
          Icon={Undo2}
          sub={sumBy(all.filter((p: Json) => p.status === 'refunded'))}
          active={tab === 'closed'}
          onClick={() => toggle('closed')}
        />
      </KpiBar>

      {!filtering && (
        <Queue items={queue.slice(0, 6)} total={queue.length} busy={busy} on={on} seeAll={() => setTab('review')} />
      )}

      <div className="tool">
        <Pills
          label="فیلتر وضعیت"
          value={tab}
          onChange={setTab}
          options={[
            ['all', 'همه', counts.all],
            ['review', 'نیازمند بررسی', counts.review, { warn: true }],
            ['succeeded', 'موفق', counts.succeeded],
            ['failed', 'ناموفق', counts.failed],
            ['closed', 'مسترد / لغو', counts.closed],
          ]}
        />
        <div className="mr-auto flex flex-wrap items-center gap-2">
          {providers.length > 1 && (
            <select
              aria-label="فیلتر درگاه"
              className="inp !w-auto !py-2 !text-xs font-bold"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              <option value="">همه درگاه‌ها</option>
              {providers.map((k) => (
                <option key={String(k)} value={String(k)}>
                  {prov(k).label}
                </option>
              ))}
            </select>
          )}
          <SearchBox label="جستجوی پرداخت" placeholder="شناسه، مبلغ، درگاه…" value={q} onChange={setQ} />
        </div>
      </div>

      {failed && (
        <ErrorBar onRetry={load}>
          <ShieldAlert size={16} />
          دریافت پرداخت‌ها ناموفق بود.
        </ErrorBar>
      )}

      {loading ? (
        <div className="card space-y-3 p-5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="skel h-10 w-full" />
          ))}
        </div>
      ) : !filtered.length ? (
        <Empty
          Icon={Wallet}
          title={filtering ? 'پرداختی با این فیلتر پیدا نشد' : 'هنوز پرداختی ثبت نشده است'}
          text={
            filtering
              ? 'جستجو یا فیلتر را تغییر دهید.'
              : 'وقتی مشتری‌ها پرداخت انجام دهند، تراکنش‌ها و رسیدهای منتظر بررسی اینجا نمایش داده می‌شوند.'
          }
        >
          {filtering && (
            <button
              className="btn btn-g"
              onClick={() => {
                setTab('all');
                setProvider('');
                setQ('');
              }}
            >
              پاک کردن فیلترها
            </button>
          )}
        </Empty>
      ) : (
        <section className="card rise overflow-hidden">
          {/* desktop table */}
          <div className="hidden max-h-[70vh] overflow-auto md:block">
            <table className="tbl2 min-w-[760px]">
              <thead>
                <tr>
                  <th>درگاه</th>
                  <th>مبلغ</th>
                  <th>وضعیت</th>
                  <th>زمان</th>
                  <th className="!text-left">اقدام</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((p: Json) => (
                  <tr
                    key={p.id}
                    className="pay-row"
                    tabIndex={0}
                    onClick={() => setSel(p.id)}
                    onKeyDown={(e) => e.key === 'Enter' && setSel(p.id)}
                  >
                    <td>
                      <ProviderChip k={p.provider} />
                      <span dir="ltr" className="mr-2 font-mono text-[11px] text-[var(--mu)]">
                        {sid(p.id)}
                      </span>
                    </td>
                    <td>
                      <Amount p={p} />
                    </td>
                    <td>
                      <Badge s={p.status} />
                    </td>
                    <td className="text-xs text-[var(--mu)]" title={dt(p.created_at)}>
                      {ago(p.created_at)}
                    </td>
                    <td>
                      <RowActions p={p} busy={busy === p.id} on={on} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* mobile cards */}
          <ul className="divide-y divide-[var(--ln)] md:hidden">
            {pageRows.map((p: Json) => (
              // Pointer shortcut for the whole card; keyboard users get tabIndex + Enter. role="button" would
              // nest interactive controls, so the list item keeps its native semantics.
              // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
              <li
                key={p.id}
                className="space-y-3 p-4"
                // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
                tabIndex={0}
                onClick={() => setSel(p.id)}
                onKeyDown={(e) => e.target === e.currentTarget && e.key === 'Enter' && setSel(p.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <ProviderChip k={p.provider} />
                  <Badge s={p.status} />
                </div>
                <div className="flex items-end justify-between gap-2">
                  <Amount p={p} big />
                  <span className="text-xs text-[var(--mu)]">{ago(p.created_at)}</span>
                </div>
                <RowActions p={p} busy={busy === p.id} on={on} />
              </li>
            ))}
          </ul>
        </section>
      )}
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE} />

      <BankSmsPanel call={call} toast={toast} payments={all} />
      <GatewaySettings obj={settings} save={saveSetting} />
      <ReceiptOcrSettings api={api} toast={toast} />
      {open && (
        <PaymentDrawer
          p={open}
          busy={busy === open.id}
          on={on}
          call={call}
          toast={toast}
          onClose={() => setSel(null)}
        />
      )}
    </div>
  );
}
