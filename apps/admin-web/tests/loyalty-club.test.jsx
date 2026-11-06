import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoyaltyClubView from '../src/LoyaltyClubView.jsx';
import { extraRoutes } from '../src/AdminExtra.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const STORES = [
  { id: 'main1', name: 'فروشگاه اصلی', kind: 'main', currency: 'IRT' },
  { id: 'res1', name: 'نمایندگی الف', kind: 'reseller', currency: 'IRR' },
];

function setup({ failWrites = false } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/stores') return json(STORES);
    if (o.method && o.method !== 'GET') return failWrites ? json({ error: { message: 'نامعتبر است.' } }, 400) : json({ ok: true });
    if (path.endsWith('/manage/program'))
      return json({
        store_id: 'x',
        currency: 'IRT',
        program: { enabled: true, earn_unit: 1000, points_per_unit: 1, max_points_per_order: null, first_order_bonus: 0, referral_bonus: 0 },
        tiers: [
          { id: 1, name: 'برنزی', min_points: 0, multiplier_bp: 10000 },
          { id: 2, name: 'نقره‌ای', min_points: 500, multiplier_bp: 11000 },
        ],
        default_tiers: [],
      });
    if (path.endsWith('/manage/rewards')) return json([]);
    if (path.endsWith('/manage/summary'))
      return json({ members: 7, points_outstanding: 1200, points_issued: 3000, value_paid: 15000, tiers: [{ name: 'برنزی', members: 7 }] });
    return json([]);
  });
  const toast = vi.fn();
  render(<LoyaltyClubView api={{ base: 'http://core.test' }} toast={toast} />);
  return { calls, toast };
}

describe('admin per-store loyalty club', () => {
  it('registers the screen in the admin routes', () => {
    expect(Object.keys(extraRoutes)).toContain('باشگاه مشتریان');
  });

  it('opens on the main store and switches to the picked store only', async () => {
    const { calls } = setup();
    await screen.findByTestId('loyalty-program');
    expect(calls.some(([, p]) => p === '/api/v1/stores/main1/loyalty/manage/program')).toBe(true);
    expect(calls.some(([, p]) => p === '/api/v1/stores/main1/loyalty/manage/summary')).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('فروشگاه'), 'res1');
    await waitFor(() => expect(calls.some(([, p]) => p === '/api/v1/stores/res1/loyalty/manage/program')).toBe(true));
  });

  it('saves the earning rule with the store only in the URL', async () => {
    const { calls, toast } = setup();
    const card = await screen.findByTestId('loyalty-program');
    await userEvent.click(within(card).getByRole('button', { name: /ذخیره/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('برنامهٔ باشگاه ذخیره شد'));
    const put = calls.find(([m, p]) => m === 'PUT' && p.endsWith('/program'));
    expect(put[1]).toBe('/api/v1/stores/main1/loyalty/manage/program');
    expect(JSON.parse(put[2])).toEqual({
      enabled: true,
      earn_unit: 1000,
      points_per_unit: 1,
      max_points_per_order: null,
      first_order_bonus: 0,
      referral_bonus: 0,
    });
  });

  it('replaces the whole ladder in one call with multipliers in basis points', async () => {
    const { calls } = setup();
    const card = await screen.findByTestId('loyalty-tiers');
    await userEvent.click(within(card).getByRole('button', { name: /ذخیرهٔ سطح‌ها/ }));
    await waitFor(() => expect(calls.some(([m, p]) => m === 'PUT' && p.endsWith('/tiers'))).toBe(true));
    const put = calls.find(([m, p]) => m === 'PUT' && p.endsWith('/tiers'));
    expect(JSON.parse(put[2]).tiers).toEqual([
      { name: 'برنزی', min_points: 0, multiplier_bp: 10000 },
      { name: 'نقره‌ای', min_points: 500, multiplier_bp: 11000 },
    ]);
  });

  it('creates a reward, and shows Core’s message when it is refused', async () => {
    const { calls, toast } = setup({ failWrites: true });
    const card = await screen.findByTestId('loyalty-rewards-manage');
    await userEvent.type(within(card).getByLabelText('نام پاداش'), 'اعتبار');
    await userEvent.type(within(card).getByLabelText('هزینه (امتیاز)'), '۵۰۰');
    await userEvent.type(within(card).getByLabelText(/اعتبار کیف پول/), '5000');
    await userEvent.click(within(card).getByRole('button', { name: /افزودن پاداش/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('نامعتبر است.'));
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe('/api/v1/stores/main1/loyalty/manage/rewards');
    expect(JSON.parse(post[2])).toMatchObject({ name: 'اعتبار', kind: 'wallet_credit', cost_points: 500, value: 5000 });
  });

  it('will not adjust points without a reason', async () => {
    setup();
    const card = await screen.findByTestId('loyalty-adjust');
    await userEvent.type(within(card).getByLabelText('شناسهٔ مشتری'), 'u1');
    await userEvent.type(within(card).getByLabelText(/تغییر امتیاز/), '100');
    expect(within(card).getByRole('button', { name: 'ثبت' })).toBeDisabled();
    await userEvent.type(within(card).getByLabelText('دلیل'), 'هدیه');
    expect(within(card).getByRole('button', { name: 'ثبت' })).toBeEnabled();
  });
});
