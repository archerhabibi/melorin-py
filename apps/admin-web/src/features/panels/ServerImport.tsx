import { useMemo, useState } from 'react';
import { RefreshCw, Upload } from 'lucide-react';
import { typedClient } from '../../api/api.ts';
import { Drawer, Section, errText, num, tint } from '../../shared/kit.tsx';
import type { Json, Toast } from '../../shared/types.ts';

/* ---------- bulk import of servers for ONE panel ---------- */
export const parseLine = (line: Json) => {
  const [name = '', location = '', capacity = ''] = line.split(',').map((s: Json) => s.trim());
  const cap = capacity === '' ? 500 : parseInt(capacity, 10);
  return {
    name,
    location,
    capacity: cap,
    bad: !name ? 'نام خالی' : !(cap >= 1 && cap <= 100000) ? 'ظرفیت نامعتبر' : '',
  };
};

export function ServerImport({
  api,
  panel,
  toast,
  onClose,
  onDone,
}: {
  api?: Json;
  panel?: Json;
  toast: Toast;
  onClose?: Json;
  onDone?: Json;
}) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const rows = useMemo(
    () =>
      text
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l && !l.startsWith('#'))
        .map(parseLine),
    [text],
  );
  const good = rows.filter((r) => !r.bad);
  const run = async () => {
    setBusy(true);
    let ok = 0,
      fail: string[] = [];
    for (const r of good) {
      try {
        const { response: res, error } = await typedClient(api.base).post('/api/v1/admin/servers', {
          body: {
            name: r.name,
            location: r.location || null,
            capacity: r.capacity,
            panel_id: panel.id,
            allow_test: true, // the server default; the generated type marks it required
          },
        });
        if (res.ok) ok++;
        else fail.push(`${r.name}: ${await errText({ json: async () => error }, 'ناموفق')}`);
      } catch {
        fail.push(`${r.name}: ارتباط برقرار نشد`);
      }
    }
    setBusy(false);
    toast(fail.length ? `${num(ok)} از ${num(good.length)} سرور ساخته شد — ${fail[0]}` : `${num(ok)} سرور ساخته شد`);
    if (ok) await onDone();
    if (!fail.length) onClose();
  };
  return (
    <Drawer
      title="ورود دسته‌جمعی مقصد"
      subtitle={`روی پنل «${panel.name}»`}
      icon={
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint('in')}>
          <Upload size={20} />
        </span>
      }
      dirty={!!text.trim()}
      busy={busy}
      onClose={onClose}
      footer={
        <button className="btn" disabled={busy || !good.length} onClick={run}>
          {busy ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}ساخت {num(good.length)} سرور
        </button>
      }
    >
      <Section
        title="داده CSV"
        hint="هر خط یک سرور: نام, موقعیت, ظرفیت (فقط نام لازم است؛ ظرفیت خالی = ۵۰۰). خط‌های شروع‌شده با # نادیده گرفته می‌شوند."
      >
        <textarea
          dir="ltr"
          rows={7}
          className="inp font-mono text-xs"
          placeholder={'de-1, Frankfurt, 100\nde-2, Frankfurt, 250'}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </Section>
      {rows.length > 0 && (
        <div className="overflow-auto rounded-xl border border-[var(--ln)]">
          <table className="tbl">
            <thead>
              <tr>
                <th>نام</th>
                <th>موقعیت</th>
                <th>ظرفیت</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={r.bad ? '!bg-[var(--bdb)]' : ''}>
                  <td>
                    {r.name || '—'}
                    {r.bad && <span className="mr-2 text-[11px] font-bold text-[var(--bd)]">{r.bad}</span>}
                  </td>
                  <td>{r.location || '—'}</td>
                  <td>{Number.isFinite(r.capacity) ? num(r.capacity) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Drawer>
  );
}
