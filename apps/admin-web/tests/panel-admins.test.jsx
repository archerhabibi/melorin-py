import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelAdminsView from '../src/PanelAdminsView.jsx';
import { extraRoutes } from '../src/AdminExtra.jsx';
import { DialogHost } from '../src/ui.jsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

const base = {
  panel_id: 'p1',
  panel_name: 'پنل اصلی',
  role: 'operator',
  last_error: null,
  synced_at: '2026-11-05T10:00:00Z',
  adopted: true,
  profile_synced: true,
};
const ADMINS = [
  {
    ...base,
    id: 'a1',
    store_id: 's1',
    store_name: 'نمایندگی الف',
    store_kind: 'reseller',
    username: 'rs_alef',
    status: 'active',
    profile: { profile_title: 'الف', telegram_id: 111 },
  },
  {
    ...base,
    id: 'a2',
    store_id: 's0',
    store_name: 'فروشگاه اصلی',
    store_kind: 'main',
    username: 'ml_main',
    status: 'error',
    last_error: 'panel down',
    profile: {},
  },
  {
    ...base,
    id: 'a3',
    store_id: 's2',
    store_name: 'نمایندگی ب',
    store_kind: 'reseller',
    username: 'rs_be',
    status: 'active',
    profile: {},
    profile_synced: false,
  },
];
const REQUESTS = [
  {
    id: 'r1',
    store_id: 's1',
    store_name: 'نمایندگی الف',
    changes: { profile_title: 'جدید', support_url: 'https://t.me/x' },
    message: 'تغییر برند',
    status: 'pending',
    created_at: '2026-11-05T09:00:00Z',
    reviewed_at: null,
    review_note: null,
    current_profile: { profile_title: 'الف' },
  },
  {
    id: 'r0',
    store_id: 's2',
    store_name: 'نمایندگی ب',
    changes: { telegram_id: 5 },
    message: null,
    status: 'applied',
    created_at: '2026-11-01T09:00:00Z',
    reviewed_at: '2026-11-02T09:00:00Z',
    review_note: 'انجام شد',
    current_profile: {},
  },
];

function setup({ patch } = {}) {
  const calls = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, o = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = o.method || 'GET';
    calls.push([method, path, o.body]);
    if (method === 'GET' && path === '/api/v1/admin/panel-admins') return json(ADMINS);
    if (method === 'GET' && path.startsWith('/api/v1/admin/panel-admin-requests')) return json(REQUESTS);
    if (method === 'GET' && path.endsWith('/credentials'))
      return json({ username: 'rs_alef', password: 'Pa55!word', panel_url: 'https://p.example.com', status: 'active' });
    if (method === 'POST' && path.endsWith('/reset-password'))
      return json({ username: 'rs_alef', password: 'N3w!pass' });
    if (method === 'POST' && path.endsWith('/sync')) return json({ planned: 1, synced: 2, failed: 0 });
    if (method === 'PATCH') return patch ? patch() : json({ results: [{ synced: true, error: null }] });
    if (method === 'POST') return json({ ok: true, results: [] });
    return json([]);
  });
  const toast = vi.fn();
  const refresh = vi.fn();
  render(
    <>
      <PanelAdminsView api={{ base: 'http://core.test', refresh }} toast={toast} />
      <DialogHost />
    </>,
  );
  return { calls, toast, refresh };
}

const rowOf = (username) => within(screen.getByText(username).closest('tr'));
const confirmIn = async (title, ok) =>
  userEvent.click(within(await screen.findByRole('dialog', { name: title })).getByRole('button', { name: ok }));
const bodies = (calls, method, tail) =>
  calls.filter(([m, p]) => m === method && p.endsWith(tail)).map(([, , b]) => JSON.parse(b));

describe('admin: PasarGuard admins of every store', () => {
  it('registers the section in the admin routes', () => {
    expect(Object.keys(extraRoutes)).toContain('ادمین‌های پنل');
  });

  it('lists every store admin and counts what needs care (error + profile not on the panel)', async () => {
    setup();
    expect(await screen.findByText('rs_alef')).toBeInTheDocument();
    expect(screen.getByText('ml_main')).toBeInTheDocument();
    expect(screen.getByText('rs_be')).toBeInTheDocument();
    const care = screen.getByRole('button', { name: /نیازمند توجه/ });
    expect(care).toHaveTextContent('۲');
    expect(screen.getByRole('button', { name: /درخواست در انتظار/ })).toHaveTextContent('۱');
    expect(rowOf('rs_be').getByText('منتظر پنل')).toBeInTheDocument();
  });

  it('filters by status and searches by store, admin or panel', async () => {
    setup();
    await screen.findByText('rs_alef');
    await userEvent.click(screen.getByRole('button', { name: /^خطا/ }));
    expect(screen.getByText('ml_main')).toBeInTheDocument();
    expect(screen.queryByText('rs_alef')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^همه/ }));
    await userEvent.type(screen.getByRole('textbox', { name: 'جستجو در ادمین‌ها' }), 'rs_be');
    expect(screen.getByText('rs_be')).toBeInTheDocument();
    expect(screen.queryByText('rs_alef')).not.toBeInTheDocument();
  });

  it('"sync now" posts and reports what was planned, synced and failed', async () => {
    const { calls, toast, refresh } = setup();
    await screen.findByText('rs_alef');
    await userEvent.click(screen.getByRole('button', { name: /همگام‌سازی اکنون/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('۱ ادمین برنامه‌ریزی شد · ۲ همگام · ۰ ناموفق'));
    expect(calls.some(([m, p]) => m === 'POST' && p === '/api/v1/admin/panel-admins/sync')).toBe(true);
    expect(refresh).toHaveBeenCalled();
  });

  it('sends only the changed profile fields and never an emptied Telegram ID', async () => {
    const { calls, toast } = setup();
    await screen.findByText('rs_alef');
    await userEvent.click(rowOf('rs_alef').getByRole('button', { name: 'مدیریت' }));
    const save = await screen.findByRole('button', { name: /ذخیرهٔ پروفایل/ });
    expect(save).toBeDisabled(); // nothing changed yet
    const title = screen.getByLabelText(/^عنوان پروفایل/);
    await userEvent.clear(title);
    await userEvent.type(title, 'عنوان تازه');
    await userEvent.clear(screen.getByLabelText(/^آیدی عددی تلگرام/));
    await userEvent.click(save);
    await waitFor(() => expect(toast).toHaveBeenCalledWith('پروفایل ذخیره و روی پنل اعمال شد'));
    expect(bodies(calls, 'PATCH', '/panel-admins/profile')).toEqual([
      { store_id: 's1', panel_id: 'p1', profile: { profile_title: 'عنوان تازه' } },
    ]);
  });

  it('says so when the panel has not accepted the profile yet (the worker retries)', async () => {
    const { toast } = setup({ patch: () => json({ results: [{ synced: false, error: 'panel down' }] }) });
    await screen.findByText('rs_alef');
    await userEvent.click(rowOf('rs_alef').getByRole('button', { name: 'مدیریت' }));
    await userEvent.type(await screen.findByLabelText(/^لینک پشتیبانی/), 'https://t.me/shop');
    await userEvent.click(screen.getByRole('button', { name: /ذخیرهٔ پروفایل/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining('هنوز روی پنل اعمال نشده')));
  });

  it('shows the password only after a confirmation, and a reset replaces it', async () => {
    const { calls } = setup();
    await screen.findByText('rs_alef');
    await userEvent.click(rowOf('rs_alef').getByRole('button', { name: 'مدیریت' }));
    await userEvent.click(await screen.findByRole('button', { name: /نمایش رمز/ }));
    expect(calls.some(([, p]) => p.endsWith('/credentials'))).toBe(false); // nothing is fetched before the confirmation
    await confirmIn('نمایش اطلاعات ورود', 'نمایش');
    expect(await screen.findByTestId('admin-password')).toHaveTextContent('Pa55!word');
    await userEvent.click(screen.getByRole('button', { name: /ساخت رمز جدید/ }));
    await confirmIn('ساخت رمز جدید', 'ساخت رمز جدید');
    await waitFor(() => expect(screen.getByTestId('admin-password')).toHaveTextContent('N3w!pass'));
    expect(screen.queryByText('Pa55!word')).not.toBeInTheDocument();
  });

  it('cannot reset the password of an admin that is not active on the panel', async () => {
    setup();
    await screen.findByText('ml_main');
    await userEvent.click(rowOf('ml_main').getByRole('button', { name: 'مدیریت' }));
    expect(await screen.findByRole('button', { name: /ساخت رمز جدید/ })).toBeDisabled();
    expect(screen.getByText('panel down')).toBeInTheDocument(); // the reason is visible
  });
});

describe('admin: reseller change requests', () => {
  const openRequests = async () => {
    await screen.findByText('rs_alef');
    await userEvent.click(screen.getByRole('radio', { name: /درخواست‌ها/ }));
  };

  it('applies a request after the admin edits one value and drops another', async () => {
    const { calls, toast } = setup();
    await openRequests();
    expect(await screen.findByText('تغییر برند')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'بررسی' }));
    expect(await screen.findByText('الف', { selector: 'span' })).toBeInTheDocument(); // the current value is shown beside the wish
    const [, supportBox] = screen.getAllByRole('checkbox');
    await userEvent.click(supportBox); // do not apply the support link
    const title = screen.getByLabelText('مقدار جدید عنوان پروفایل');
    await userEvent.clear(title);
    await userEvent.type(title, 'ویرایش‌شده');
    await userEvent.type(screen.getByLabelText(/^توضیح برای نماینده/), 'باشه');
    await userEvent.click(screen.getByRole('button', { name: /اعمال تغییرات/ }));
    await confirmIn('اعمال تغییرات', 'اعمال');
    await waitFor(() => expect(toast).toHaveBeenCalledWith('تغییرات اعمال شد'));
    expect(bodies(calls, 'POST', '/panel-admin-requests/r1/apply')).toEqual([
      { changes: { profile_title: 'ویرایش‌شده' }, note: 'باشه' },
    ]);
  });

  it('rejecting needs a reason and posts it', async () => {
    const { calls } = setup();
    await openRequests();
    await userEvent.click(await screen.findByRole('button', { name: 'بررسی' }));
    const reject = await screen.findByRole('button', { name: /^رد درخواست/ });
    expect(reject).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^توضیح برای نماینده/), 'آدرس رسمی بفرستید');
    await userEvent.click(reject);
    await confirmIn('رد درخواست', 'رد درخواست');
    await waitFor(() =>
      expect(bodies(calls, 'POST', '/panel-admin-requests/r1/reject')).toEqual([{ note: 'آدرس رسمی بفرستید' }]),
    );
  });

  it('a decided request is read-only and shows the review note', async () => {
    setup();
    await openRequests();
    await userEvent.click(await screen.findByRole('button', { name: /^اعمال‌شده/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'جزئیات' }));
    expect(await screen.findByText('انجام شد')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /اعمال تغییرات/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
