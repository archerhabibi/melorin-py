import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SubBrandingCard from '../src/SubBrandingCard.tsx';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
const URL = '/api/v1/admin/stores/s1/sub-branding/p1';
const PREVIEW = {
  live: true,
  wanted: { melorin_brand_name: 'Paris VPN' },
  on_panel: {},
  in_sync: false,
  other_keys_kept: ['foo'],
};

function mount(over = {}) {
  const calls = [];
  const call = vi.fn(async (path, init = {}) => {
    calls.push([path, init.method || 'GET', init.body]);
    if (!init.method) return over.preview ?? json(PREVIEW);
    return over.post ?? json({ applied: true });
  });
  const toast = vi.fn();
  render(<SubBrandingCard storeId="s1" panelId="p1" panelName="Panel DE" call={call} toast={toast} />);
  return { calls, toast };
}

describe('admin › sub branding card', () => {
  it('apply stays disabled until the panel name is typed exactly, then posts the typed name', async () => {
    const { calls, toast } = mount();
    const apply = await screen.findByRole('button', { name: /اعمال روی پنل/ });
    expect(apply).toBeDisabled();
    await userEvent.type(screen.getByLabelText('نام پنل برای تأیید'), 'Panel DE');
    expect(apply).toBeEnabled();
    await userEvent.click(apply);
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const post = calls.find((c) => c[1] === 'POST');
    expect(post[0]).toBe(`${URL}/apply`);
    expect(JSON.parse(post[2])).toEqual({ confirm_name: 'Panel DE' });
  });

  it('cannot apply when the panel is unreachable', async () => {
    mount({ preview: json({ live: false, note: 'پنل موقتاً در دسترس نیست.', wanted: {} }) });
    expect(await screen.findByRole('status')).toHaveTextContent('موقتاً');
    await userEvent.type(screen.getByLabelText('نام پنل برای تأیید'), 'Panel DE');
    expect(screen.getByRole('button', { name: /اعمال روی پنل/ })).toBeDisabled();
  });

  it('shows the server reason when apply fails', async () => {
    mount({ post: json({ error: { message: 'Panel did not accept the branding' } }, 502) });
    await userEvent.type(await screen.findByLabelText('نام پنل برای تأیید'), 'Panel DE');
    await userEvent.click(screen.getByRole('button', { name: /اعمال روی پنل/ }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});
