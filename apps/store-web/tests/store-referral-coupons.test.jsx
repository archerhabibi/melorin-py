import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Referral from '../src/Referral.jsx';
import ResellerReferral from '../src/ResellerReferral.jsx';
import ResellerCoupons from '../src/ResellerCoupons.jsx';
import { describePlan, percentToBp, toInt } from '../src/storeProgram.js';

const res = (body, status = 200) => new Response(JSON.stringify(body), { status });

describe('storeProgram helpers', () => {
  it('formats a percent plan from basis points and a fixed plan in the store currency', () => {
    expect(describePlan({ model: 'percent', value: 1250 }, 'IRT')).toBe('۱۲٫۵٪');
    expect(describePlan({ model: 'fixed', value: 5000, max_amount: 8000 }, 'IRT')).toContain('تومان');
  });
  it('reads Persian digits and refuses nonsense', () => {
    expect(toInt('۵۰۰۰')).toBe(5000);
    expect(toInt('12a')).toBeNull();
    expect(percentToBp('۱۲٫۵')).toBe(1250);
    expect(percentToBp('1.234')).toBeNull();
  });
});

describe('customer referral card (this store only)', () => {
  it('asks Core for the programme of the store it is in and shows that store’s links and numbers', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path) => {
      calls.push(path);
      return res({
        store_id: 's1',
        referral_code: 'ABC123',
        links: { web: 'https://shop.example/?ref=ABC123', telegram: 'https://t.me/shop_bot?start=ref_ABC123' },
        program: {
          enabled: true,
          signup_reward: { model: 'fixed', value: 5000, max_amount: null },
          commission: { model: 'percent', value: 1000, max_amount: null },
        },
        invited: 3,
        earned: 12000,
        currency: 'IRT',
        commissions: [],
      });
    });
    render(<Referral coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
    expect(await screen.findByText('ABC123')).toBeInTheDocument();
    expect(calls).toEqual(['/api/v1/stores/s1/referral']);
    expect(screen.getByText('https://shop.example/?ref=ABC123')).toBeInTheDocument();
    expect(screen.getByText('https://t.me/shop_bot?start=ref_ABC123')).toBeInTheDocument();
    expect(screen.getByText(/پاداش اولین خرید دوست شما/)).toBeInTheDocument();
  });

  it('says so plainly when the store runs no programme', async () => {
    const coreFetch = vi.fn(async () =>
      res({
        referral_code: 'X',
        links: {},
        program: { enabled: false },
        invited: 0,
        earned: 0,
        currency: 'IRT',
        commissions: [],
      }),
    );
    render(<Referral coreFetch={coreFetch} storeId="s1" notify={vi.fn()} />);
    expect(await screen.findByText(/فعلاً پاداش دعوت ندارد/)).toBeInTheDocument();
  });
});

describe('reseller referral plans', () => {
  it('saves a plan for his own store only: the store comes from the URL, never from the body', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path, o = {}) => {
      calls.push([o.method || 'GET', path, o.body]);
      if (o.method === 'PUT') return res({ id: 'r1' });
      if (path.endsWith('/summary')) return res({ invited: 2, referrers: 1, paid_out: 7000, outstanding_clawback: 0 });
      return res([]);
    });
    const notify = vi.fn();
    render(<ResellerReferral coreFetch={coreFetch} storeId="s1" notify={notify} currency="IRT" />);
    const card = await screen.findByTestId('plan-signup_reward');
    await userEvent.selectOptions(card.querySelector('select'), 'fixed');
    await userEvent.type(card.querySelector('input[inputmode="decimal"]'), '5000');
    await userEvent.click(card.querySelector('button'));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('طرح ذخیره شد'));
    const put = calls.find(([m]) => m === 'PUT');
    expect(put[1]).toBe('/api/v1/stores/s1/referral-rules');
    expect(JSON.parse(put[2])).toEqual({
      product_id: null,
      kind: 'signup_reward',
      model: 'fixed',
      value: 5000,
      max_amount: null,
      is_active: true,
    });
    expect(put[2]).not.toContain('store_id');
  });
});

describe('reseller discount codes', () => {
  it('lists and creates codes of his own store through the store-scoped routes', async () => {
    const calls = [];
    const coreFetch = vi.fn(async (path, o = {}) => {
      calls.push([o.method || 'GET', path, o.body]);
      if (o.method === 'POST') return res({ id: 'c1' }, 201);
      return res([
        {
          id: 'c0',
          code: 'OLD10',
          percent_bp: 1000,
          fixed: 0,
          currency: 'IRT',
          redemptions: 1,
          max_redemptions: 5,
          status: 'active',
        },
      ]);
    });
    const notify = vi.fn();
    render(<ResellerCoupons coreFetch={coreFetch} storeId="s1" notify={notify} currency="IRT" />);
    expect(await screen.findByText('OLD10')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('کد'), 'NEW20');
    await userEvent.type(screen.getByLabelText('درصد تخفیف'), '20');
    await userEvent.click(screen.getByRole('button', { name: /ساخت کد/ }));
    await waitFor(() => expect(notify).toHaveBeenCalledWith('کد تخفیف ساخته شد'));
    const post = calls.find(([m]) => m === 'POST');
    expect(post[1]).toBe('/api/v1/stores/s1/coupons');
    expect(JSON.parse(post[2])).toMatchObject({ code: 'NEW20', percent_bp: 2000, fixed: 0, per_customer_limit: 1 });
    expect(post[2]).not.toContain('store_id');
  });

  it('does not submit a code with no discount', async () => {
    const coreFetch = vi.fn(async () => res([]));
    render(<ResellerCoupons coreFetch={coreFetch} storeId="s1" notify={vi.fn()} currency="IRT" />);
    await userEvent.type(await screen.findByLabelText('کد'), 'EMPTY');
    expect(screen.getByRole('button', { name: /ساخت کد/ })).toBeDisabled();
  });
});
