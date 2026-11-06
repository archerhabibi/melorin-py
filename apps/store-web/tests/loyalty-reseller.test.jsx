import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResellerLoyalty from '../src/ResellerLoyalty.jsx';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });

function server(over = {}) {
  const writes = [];
  const state = {
    program: { enabled: true, earn_unit: 1000, points_per_unit: 2, max_points_per_order: null, first_order_bonus: 50, referral_bonus: 0 },
    tiers: [
      { id: 1, name: 'برنزی', min_points: 0, multiplier_bp: 10000 },
      { id: 2, name: 'نقره‌ای', min_points: 500, multiplier_bp: 11000 },
    ],
    rewards: [],
    ...over,
  };
  const coreFetch = vi.fn(async (path, opts = {}) => {
    const m = opts.method || 'GET';
    if (m !== 'GET') {
      writes.push([m, path, JSON.parse(opts.body)]);
      return over.fail ? res({ error: { message: 'نامعتبر است.' } }, 400) : res({ ok: true });
    }
    if (path.endsWith('/manage/program')) return res({ store_id: 's1', currency: 'IRT', program: state.program, tiers: state.tiers, default_tiers: [] });
    if (path.endsWith('/manage/rewards')) return res(state.rewards);
    if (path.endsWith('/manage/summary'))
      return res({ members: 4, points_outstanding: 900, points_issued: 1500, value_paid: 20000, tiers: [{ name: 'برنزی', members: 3 }, { name: 'نقره‌ای', members: 1 }] });
    return res({}, 404);
  });
  return { coreFetch, writes };
}

const mount = (s) => render(<ResellerLoyalty coreFetch={s.coreFetch} storeId="s1" notify={vi.fn()} currency="IRT" />);

describe('reseller loyalty club management (his store only)', () => {
  it('loads program, rewards and summary of the store in the URL', async () => {
    const s = server();
    mount(s);
    expect(await screen.findByTestId('loyalty-program')).toBeInTheDocument();
    const paths = s.coreFetch.mock.calls.map((c) => c[0]).sort();
    expect(paths).toEqual([
      '/api/v1/stores/s1/loyalty/manage/program',
      '/api/v1/stores/s1/loyalty/manage/rewards',
      '/api/v1/stores/s1/loyalty/manage/summary',
    ]);
    expect(screen.getByText('امتیاز در گردش')).toBeInTheDocument();
  });

  it('saves the earning rule as integers and never sends a store id in the body', async () => {
    const s = server();
    mount(s);
    const card = await screen.findByTestId('loyalty-program');
    const unit = within(card).getByLabelText(/به‌ازای هر چند/);
    await userEvent.clear(unit);
    await userEvent.type(unit, '۲۰۰۰');
    await userEvent.click(within(card).getByRole('button', { name: /ذخیره/ }));
    await waitFor(() => expect(s.writes).toHaveLength(1));
    const [method, path, body] = s.writes[0];
    expect([method, path]).toEqual(['PUT', '/api/v1/stores/s1/loyalty/manage/program']);
    expect(body).toMatchObject({ enabled: true, earn_unit: 2000, points_per_unit: 2, max_points_per_order: null, first_order_bonus: 50 });
    expect(body).not.toHaveProperty('store_id');
  });

  it('saves the whole ladder at once with multipliers as basis points', async () => {
    const s = server();
    mount(s);
    const card = await screen.findByTestId('loyalty-tiers');
    await userEvent.click(within(card).getByRole('button', { name: /ذخیرهٔ سطح‌ها/ }));
    await waitFor(() => expect(s.writes).toHaveLength(1));
    expect(s.writes[0][2].tiers).toEqual([
      { name: 'برنزی', min_points: 0, multiplier_bp: 10000 },
      { name: 'نقره‌ای', min_points: 500, multiplier_bp: 11000 },
    ]);
  });

  it('creates a wallet-credit reward only when name, cost and value are valid', async () => {
    const s = server();
    mount(s);
    const card = await screen.findByTestId('loyalty-rewards-manage');
    const add = within(card).getByRole('button', { name: /افزودن پاداش/ });
    expect(add).toBeDisabled();
    await userEvent.type(within(card).getByLabelText('نام پاداش'), 'اعتبار ۵ هزار');
    await userEvent.type(within(card).getByLabelText('هزینه (امتیاز)'), '۵۰۰');
    await userEvent.type(within(card).getByLabelText(/اعتبار کیف پول/), '5000');
    expect(add).toBeEnabled();
    await userEvent.click(add);
    await waitFor(() => expect(s.writes).toHaveLength(1));
    expect(s.writes[0][0]).toBe('POST');
    expect(s.writes[0][2]).toMatchObject({ name: 'اعتبار ۵ هزار', kind: 'wallet_credit', cost_points: 500, value: 5000, stock: null, per_user_limit: null });
  });

  it('requires a reason before adjusting a member’s points', async () => {
    const s = server();
    mount(s);
    const card = await screen.findByTestId('loyalty-adjust');
    const go = within(card).getByRole('button', { name: 'ثبت' });
    await userEvent.type(within(card).getByLabelText('شناسهٔ مشتری'), '0b0e7a52-0000-4000-8000-000000000001');
    await userEvent.type(within(card).getByLabelText(/تغییر امتیاز/), '-50');
    expect(go).toBeDisabled();
    await userEvent.type(within(card).getByLabelText(/دلیل/), 'اصلاح');
    await userEvent.click(go);
    await waitFor(() => expect(s.writes).toHaveLength(1));
    expect(s.writes[0][2]).toMatchObject({ delta: -50, reason: 'اصلاح' });
  });
});
