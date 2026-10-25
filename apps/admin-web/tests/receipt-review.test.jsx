import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReceiptReviewPanel, { clock } from '../src/ReceiptReviewPanel.jsx';
import ReceiptOcrSettings from '../src/ReceiptOcrSettings.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const BASE = '/api/v1/admin/stores/s-main';
const NOW = new Date('2026-10-25T10:00:00Z');
const iso = (sec) => new Date(NOW.getTime() + sec * 1000).toISOString();
const item = (over = {}) => ({
  payment_id: 'p1',
  user_id: 'u1',
  amount: 150000,
  currency: 'IRT',
  created_at: iso(-60),
  state: 'waiting',
  block: null,
  block_text: null,
  auto_approve_at: iso(240),
  receipt_read: { amount_rial: 1500000, paid_at: iso(-90), source_card_last4: '7931', reference: '286961122762' },
  ...over,
});
const queue = (over = {}) => ({
  config: { enabled: true, minutes: 5, max_amount_rial: 5000000, max_exposure_rial: 20000000, max_open_per_user: 1 },
  now: NOW.toISOString(),
  waiting: [item()],
  provisional: [],
  recent: [],
  exposure_rial: 0,
  ...over,
});

function setup(q = queue()) {
  const calls = [];
  const call = vi.fn(async (path, o = {}) => {
    calls.push([o.method || 'GET', path, o.body]);
    if (o.method === 'PUT') return json(q.config);
    if (o.method === 'POST') return json({ ok: true });
    return json(q);
  });
  const toast = vi.fn();
  render(
    <>
      <ReceiptReviewPanel call={call} toast={toast} base={BASE} receiptPath={(id) => `/r/${id}`} />
      <DialogHost />
    </>,
  );
  return { calls, toast };
}

afterEach(() => vi.useRealTimers());

describe('receipt review panel (time-boxed manual review)', () => {
  it('formats the countdown as mm:ss and never goes negative', () => {
    expect(clock(240)).toBe('۰۴:۰۰');
    expect(clock(-5)).toBe('۰۰:۰۰');
  });

  it('shows the waiting receipt with its read facts and a countdown to the provisional credit', async () => {
    setup();
    expect(await screen.findByText(/تا تأیید موقت/)).toBeInTheDocument();
    expect(screen.getByText('…7931')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /زمان باقی‌مانده/ })).toBeInTheDocument();
  });

  it('says why a receipt will NOT be credited provisionally and hides its countdown', async () => {
    setup(queue({ waiting: [item({ block: 'duplicate_image', block_text: 'همین تصویر رسید قبلاً ثبت شده' })] }));
    expect((await screen.findAllByText(/همین تصویر رسید قبلاً ثبت شده/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/تا تأیید موقت/)).not.toBeInTheDocument();
  });

  it('confirms a provisional credit after an explicit dialog and posts the decision', async () => {
    const prov = item({ state: 'open', auto_approve_at: null, credited_at: iso(-120) });
    const { calls } = setup(queue({ waiting: [], provisional: [prov], exposure_rial: 1500000 }));
    await userEvent.click(await screen.findByRole('button', { name: /تأیید نهایی/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'تأیید' }));
    await waitFor(() => expect(calls.some(([m]) => m === 'POST')).toBe(true));
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe(`${BASE}/receipt-review/p1`);
    expect(JSON.parse(post[2])).toEqual({ approve: true });
  });

  it('revoking warns that the wallet can go negative and only then calls the API', async () => {
    const prov = item({ state: 'open', auto_approve_at: null, credited_at: iso(-120) });
    const { calls } = setup(queue({ waiting: [], provisional: [prov] }));
    await userEvent.click(await screen.findByRole('button', { name: /لغو و برگشت اعتبار/ }));
    expect(await screen.findByText(/کیف پول منفی می‌شود/)).toBeInTheDocument();
    expect(calls.some(([m]) => m === 'POST')).toBe(false);
    await userEvent.click(screen.getAllByRole('button', { name: /لغو و برگشت اعتبار/ }).at(-1));
    await waitFor(() => expect(calls.some(([m]) => m === 'POST')).toBe(true));
    expect(JSON.parse(calls.find(([m]) => m === 'POST')[2])).toEqual({ approve: false });
  });

  it('saves the grace settings as integers', async () => {
    const { calls } = setup(queue({ config: { ...queue().config, enabled: false } }));
    await userEvent.click(await screen.findByRole('switch', { name: 'تأیید موقت' }));
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() => expect(calls.some(([m]) => m === 'PUT')).toBe(true));
    const body = JSON.parse(calls.find(([m]) => m === 'PUT')[2]);
    expect(body).toMatchObject({ enabled: true, minutes: 5, max_amount_rial: 5000000, max_open_per_user: 1 });
  });

  it('renders nothing when the server has no such endpoint (older backend)', async () => {
    const call = vi.fn(async () => json({ source: {}, messages: [] }));
    const { container } = render(<ReceiptReviewPanel call={call} toast={vi.fn()} base={BASE} />);
    await waitFor(() => expect(call).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe('receipt OCR settings', () => {
  const cfg = (over = {}) => ({
    engine: 'auto',
    base_url: 'https://api.anthropic.com',
    model: 'claude-haiku-5-5',
    timeout_seconds: 25,
    tesseract_lang: 'fas+eng',
    api_key_set: false,
    source: 'env',
    active_engine: 'tesseract',
    tesseract_available: true,
    ...over,
  });
  function setupOcr(c = cfg()) {
    const calls = [];
    const f = vi.fn(async (url, o = {}) => {
      calls.push([o.method || 'GET', String(url), o.body]);
      if (o.method === 'PUT')
        return json({ ...c, ...JSON.parse(o.body), api_key_set: true, source: 'panel', active_engine: 'vision' });
      if (o.method === 'POST') return json({ ok: true, engine: 'vision', detail: 'اتصال و مدل تأیید شد.' });
      return json({ receipt_ocr: c });
    });
    vi.stubGlobal('fetch', f);
    const toast = vi.fn();
    render(<ReceiptOcrSettings api={{ base: '' }} toast={toast} />);
    return { calls, toast };
  }
  afterEach(() => vi.unstubAllGlobals());

  it('shows the active engine and where the setting comes from', async () => {
    setupOcr();
    expect(await screen.findByText(/فعال: Tesseract/)).toBeInTheDocument();
    expect(screen.getByText(/از متغیر محیطی سرور/)).toBeInTheDocument();
  });

  it('requires an API key for the vision engine, sends it write-only and never shows it back', async () => {
    const { calls } = setupOcr();
    await userEvent.click(await screen.findByRole('radio', { name: /هوش مصنوعی بینایی/ }));
    expect(screen.getByRole('button', { name: 'ذخیره' })).toBeDisabled();
    expect(screen.getByText(/کلید API لازم است/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText('sk-ant-…'), 'sk-test-123');
    await userEvent.click(screen.getByRole('button', { name: 'ذخیره' }));
    await waitFor(() => expect(calls.some(([m]) => m === 'PUT')).toBe(true));
    const body = JSON.parse(calls.find(([m]) => m === 'PUT')[2]);
    expect(body).toMatchObject({ engine: 'vision', api_key: 'sk-test-123', timeout_seconds: 25 });
    expect(await screen.findByText(/فعال: هوش مصنوعی بینایی/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue('sk-test-123')).not.toBeInTheDocument();
  });

  it('rejects a non-https service address before calling the server', async () => {
    setupOcr();
    await userEvent.click(await screen.findByRole('radio', { name: /هوش مصنوعی بینایی/ }));
    await userEvent.click(screen.getByText('تنظیمات پیشرفته'));
    const url = screen.getByDisplayValue('https://api.anthropic.com');
    await userEvent.clear(url);
    await userEvent.type(url, 'http://insecure.example');
    expect(screen.getByText(/باید با https شروع شود/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ذخیره' })).toBeDisabled();
  });

  it('only allows the connection test after unsaved changes are saved', async () => {
    setupOcr(cfg({ engine: 'vision', api_key_set: true, active_engine: 'vision' }));
    const test = await screen.findByRole('button', { name: /آزمایش اتصال/ });
    expect(test).toBeEnabled();
    await userEvent.click(screen.getByRole('radio', { name: /خاموش/ }));
    expect(test).toBeDisabled();
  });
});
