import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ReferralProgramsView from '../src/ReferralProgramsView.jsx';
import { extraRoutes } from '../src/AdminExtra.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const STORES = [
  { id: 'main1', name: 'فروشگاه اصلی', kind: 'main', currency: 'IRT' },
  { id: 'res1', name: 'نمایندگی الف', kind: 'reseller', currency: 'IRR' },
];

function setup({ rules = {} } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push([o.method || 'GET', path, o.body]);
    if (path === '/api/v1/admin/stores') return json(STORES);
    if (path.startsWith('/api/v1/admin/referral-rules') && o.method === 'PUT') return json({ id: 'r1' });
    if (path.startsWith('/api/v1/admin/referral-rules'))
      return json(rules[new URL(path, 'http://x').searchParams.get('store_id')] || []);
    if (path.includes('/referrals/summary'))
      return json({ invited: 4, referrers: 2, paid_out: 9000, outstanding_clawback: 0 });
    return json([]);
  });
  const toast = vi.fn();
  render(<ReferralProgramsView api={{ base: 'http://core.test' }} toast={toast} />);
  return { calls, toast };
}

describe('admin per-store referral programmes', () => {
  it('registers the screen in the admin routes', () => {
    expect(Object.keys(extraRoutes)).toContain('برنامه‌های معرفی');
  });

  it('loads the plans and numbers of the picked store only, and switches with the store', async () => {
    const { calls } = setup();
    await screen.findByTestId('plan-signup_reward');
    expect(calls.some(([, p]) => p === '/api/v1/admin/referral-rules?store_id=main1')).toBe(true);
    expect(calls.some(([, p]) => p === '/api/v1/admin/stores/main1/referrals/summary')).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText('فروشگاه'), 'res1');
    await waitFor(() => expect(calls.some(([, p]) => p === '/api/v1/admin/referral-rules?store_id=res1')).toBe(true));
    expect(calls.some(([, p]) => p === '/api/v1/admin/stores/res1/referrals/summary')).toBe(true);
  });

  it('saves a plan for the picked store (store id in the body, same one as the list)', async () => {
    const { calls, toast } = setup();
    const card = await screen.findByTestId('plan-commission');
    await userEvent.type(card.querySelector('input[inputmode="decimal"]'), '۱۰');
    await userEvent.click(card.closest('section').querySelector('button'));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('طرح ذخیره شد'));
    const put = calls.find(([m]) => m === 'PUT');
    expect(put[1]).toBe('/api/v1/admin/referral-rules');
    expect(JSON.parse(put[2])).toEqual({
      product_id: null,
      store_id: 'main1',
      kind: 'commission',
      model: 'percent',
      value: 1000,
      max_amount: null,
      is_active: true,
    });
  });
});
