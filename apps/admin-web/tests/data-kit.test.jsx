import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrdersView, { OrderFlow } from '../src/OrdersView.jsx';
import { DataGrid } from '../src/dataKit.jsx';
import { Paginator, SearchBox, Stat } from '../src/kit.jsx';
import { Package } from 'lucide-react';

const json = (body) =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
afterEach(() => vi.restoreAllMocks());

describe('OrderFlow (order lifecycle tracker)', () => {
  const steps = () => within(screen.getByRole('list', { name: 'مراحل سفارش' })).getAllByRole('listitem');

  it('shows four steps, all completed for a finished order', () => {
    render(<OrderFlow status="completed" />);
    expect(steps()).toHaveLength(4);
    expect(steps().every((li) => li.classList.contains('done'))).toBe(true);
    expect(screen.queryByRole('listitem', { current: 'step' })).toBeNull();
  });

  it('marks the blocked step as current and relabels it on failure', () => {
    render(<OrderFlow status="provisioning_failed" />);
    const [reg, pay, build, done] = steps();
    expect(reg).toHaveClass('done');
    expect(pay).toHaveClass('done');
    expect(build).toHaveClass('cur');
    expect(build).toHaveAttribute('aria-current', 'step');
    expect(build).toHaveTextContent('ساخت ناموفق');
    expect(done).toHaveClass('todo');
  });

  it('stops at the payment step for a pending payment and for a cancellation', () => {
    const { unmount } = render(<OrderFlow status="payment_pending" />);
    expect(steps()[1]).toHaveClass('cur');
    unmount();
    render(<OrderFlow status="cancelled" />);
    expect(steps()[1]).toHaveTextContent('لغو شد');
  });

  it('renders nothing for an unknown status', () => {
    const { container } = render(<OrderFlow status="something_new" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('appears in the order drawer', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const p = String(url);
      if (p.includes('/admin/orders'))
        return json([
          {
            id: 'o1',
            number: 'ORD-1',
            user_id: 'u1',
            store_id: 's1',
            status: 'paid',
            total: 1000,
            currency: 'IRT',
            created_at: '2026-03-01T10:00:00Z',
          },
        ]);
      return json([]);
    });
    render(<OrdersView api={{ base: 'http://core.test' }} toast={() => {}} />);
    await userEvent.click(await screen.findByText('ORD-1'));
    const dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByText('مسیر سفارش')).toBeInTheDocument();
    expect(within(dlg).getByRole('list', { name: 'مراحل سفارش' })).toBeInTheDocument();
  });
});

describe('Paginator', () => {
  it('renders nothing when everything fits on one page', () => {
    const { container } = render(<Paginator page={0} setPage={() => {}} total={20} pageSize={20} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the visible range, labelled controls and disables the edges', async () => {
    const setPage = vi.fn();
    render(<Paginator page={1} setPage={setPage} total={45} pageSize={20} />);
    expect(screen.getByText('نمایش ۲۱ تا ۴۰ از ۴۵')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'صفحه بعد' }));
    await userEvent.click(screen.getByRole('button', { name: 'صفحه قبل' }));
    expect(setPage).toHaveBeenCalledTimes(2);
  });

  it('clamps the range on the last page', () => {
    render(<Paginator page={2} setPage={() => {}} total={45} pageSize={20} />);
    expect(screen.getByText('نمایش ۴۱ تا ۴۵ از ۴۵')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'صفحه بعد' })).toBeDisabled();
  });
});

describe('Stat', () => {
  it('shows a loading placeholder instead of a misleading zero while the value is unknown', () => {
    render(<Stat Icon={Package} tone="in" label="همه" value={undefined} />);
    expect(screen.getByRole('status', { name: 'در حال بارگذاری' })).toBeInTheDocument();
    expect(screen.queryByText('۰')).toBeNull();
  });

  it('shows a real zero', () => {
    render(<Stat Icon={Package} tone="in" label="همه" value={0} />);
    expect(screen.getByText('۰')).toBeInTheDocument();
  });
});

describe('SearchBox "/" hotkey', () => {
  const press = (init = {}) => fireEvent.keyDown(window, { key: '/', code: 'Slash', ...init });

  it('focuses the field and shows the key hint', () => {
    render(<SearchBox value="" onChange={() => {}} label="جستجو" hotkey />);
    press();
    expect(screen.getByLabelText('جستجو')).toHaveFocus();
    expect(screen.getByText('/')).toBeInTheDocument();
  });

  it('also works on the Persian layout where the key is not "/"', () => {
    render(<SearchBox value="" onChange={() => {}} label="جستجو" hotkey />);
    fireEvent.keyDown(window, { key: '.', code: 'Slash' });
    expect(screen.getByLabelText('جستجو')).toHaveFocus();
  });

  it('does nothing while typing in another field, with a modifier, or when a dialog is open', () => {
    render(
      <>
        <input aria-label="other" />
        <SearchBox value="" onChange={() => {}} label="جستجو" hotkey />
      </>,
    );
    screen.getByLabelText('other').focus();
    press();
    expect(screen.getByLabelText('other')).toHaveFocus();
    document.activeElement.blur();
    press({ ctrlKey: true });
    expect(screen.getByLabelText('جستجو')).not.toHaveFocus();
    const dlg = document.createElement('div');
    dlg.setAttribute('role', 'dialog');
    document.body.append(dlg);
    press();
    expect(screen.getByLabelText('جستجو')).not.toHaveFocus();
    dlg.remove();
  });

  it('is off by default and hides the hint once there is a value', () => {
    const { rerender } = render(<SearchBox value="" onChange={() => {}} label="جستجو" />);
    press();
    expect(screen.getByLabelText('جستجو')).not.toHaveFocus();
    expect(screen.queryByText('/')).toBeNull();
    rerender(<SearchBox value="abc" onChange={() => {}} label="جستجو" hotkey />);
    expect(screen.queryByText('/')).toBeNull();
  });
});

describe('DataGrid card layout hints', () => {
  const columns = [
    { key: 'a', label: 'شماره', render: (r) => r.a },
    { key: 'b', label: 'وضعیت', m: 'head', render: (r) => r.b },
    { key: 'c', label: 'ترافیک', m: 'full', render: (r) => r.c },
    { key: 'd', label: 'آی‌پی', m: 'hide', render: (r) => r.d },
  ];
  const rows = [{ id: 1, a: 'A1', b: 'B1', c: 'C1', d: 'D1' }];

  it('tags cells for the phone card layout and keeps table semantics', () => {
    render(<DataGrid columns={columns} rows={rows} caption="فهرست" onRowClick={() => {}} />);
    expect(screen.getByRole('table', { name: 'فهرست' })).toBeInTheDocument();
    const row = screen.getByText('A1').closest('tr');
    expect(row).toHaveClass('has-head');
    expect(screen.getByText('A1').closest('td')).toHaveClass('m-title');
    expect(screen.getByText('B1').closest('td')).toHaveClass('m-head');
    expect(screen.getByText('C1').closest('td')).toHaveClass('m-full');
    expect(screen.getByText('D1').closest('td')).toHaveClass('m-hide');
    expect(screen.getByText('C1').closest('td')).toHaveAttribute('data-label', 'ترافیک');
  });

  it('lets a later column be the card title', () => {
    render(
      <DataGrid
        columns={[
          { key: 'at', label: 'زمان', render: (r) => r.at },
          { key: 'act', label: 'عملیات', m: 'title', render: (r) => r.act },
        ]}
        rows={[{ id: 1, at: 'T', act: 'ACT' }]}
      />,
    );
    expect(screen.getByText('ACT').closest('td')).toHaveClass('m-title');
    expect(screen.getByText('T').closest('td')).not.toHaveClass('m-title');
  });

  it('renders the empty node without the cell padding class and the loading skeleton as flat rows', () => {
    const { rerender } = render(<DataGrid columns={columns} rows={[]} emptyNode={<p>هیچ</p>} />);
    expect(screen.getByText('هیچ').closest('td')).toHaveClass('tbl-empty');
    rerender(<DataGrid columns={columns} rows={[]} loading />);
    expect(document.querySelectorAll('tr.tbl-flat').length).toBe(6);
  });
});
