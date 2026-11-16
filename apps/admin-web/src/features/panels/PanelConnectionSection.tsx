import { Field, Section, Secret, Segmented } from '../../shared/kit.tsx';
import { ShieldCheck } from 'lucide-react';
import { UpstreamCredentials } from './UpstreamBotFields.tsx';

export function PanelConnectionSection({
  changeCred,
  edit,
  err,
  f,
  isUb,
  panel,
  set,
  setChangeCred,
  setF,
  setUb,
  show,
}: Record<string, any>) {
  return (
    <>
      {f.kind !== 'mock' && (
        <Section title={`${edit ? '' : '۳ · '}احراز هویت (رمزنگاری‌شده ذخیره می‌شود)`}>
          {edit && panel.has_credentials && !changeCred ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--sf2)] px-3 py-2.5">
              <span className="flex items-center gap-2 text-xs">
                <ShieldCheck size={15} className="text-[var(--ok)]" />
                اعتبارنامه ذخیره شده است و نمایش داده نمی‌شود.
              </span>
              <button type="button" className="btn btn-g" onClick={() => setChangeCred(true)}>
                تغییر اعتبارنامه
              </button>
            </div>
          ) : (
            <>
              {isUb ? (
                <UpstreamCredentials ub={f.ub} setUb={setUb} show={show} edit={edit} />
              ) : (
                <>
                  <Segmented
                    label="روش ورود"
                    value={f.auth}
                    onChange={set('auth')}
                    options={[
                      ['token', f.kind === 'sanaei' ? 'API Token' : 'API Key'],
                      ['login', 'نام کاربری و رمز'],
                    ]}
                  />
                  {f.auth === 'token' ? (
                    <Field label={f.kind === 'sanaei' ? 'API Token' : 'API Key'} error={show('auth') || undefined}>
                      <Secret value={f.token} onChange={set('token')} placeholder="••••••••" />
                    </Field>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="نام کاربری">
                        <input
                          dir="ltr"
                          autoComplete="off"
                          className="inp"
                          value={f.user}
                          onChange={(e) => set('user')(e.target.value)}
                        />
                      </Field>
                      <Field label="رمز عبور">
                        <Secret value={f.pass} onChange={set('pass')} />
                      </Field>
                      {show('auth') && <p className="text-[11px] text-[var(--bd)] sm:col-span-2">{err.auth}</p>}
                    </div>
                  )}
                  {f.kind === 'sanaei' && f.auth === 'login' && (
                    <p className="text-[11px] leading-5 text-[var(--mu)]">
                      اگر 2FA روی پنل فعال است، ورود با نام کاربری کار نمی‌کند؛ از API Token استفاده کنید.
                    </p>
                  )}
                </>
              )}
              {edit && panel.has_credentials && (
                <button
                  type="button"
                  className="text-xs font-bold text-[var(--mu)] underline"
                  onClick={() => {
                    setChangeCred(false);
                    setF((x: { ub: Record<string, unknown> } & Record<string, unknown>) => ({
                      ...x,
                      token: '',
                      user: '',
                      pass: '',
                      ub: { ...x.ub, apiId: '', apiHash: '', session: '' },
                    }));
                  }}
                >
                  انصراف از تغییر اعتبارنامه
                </button>
              )}
            </>
          )}
        </Section>
      )}
    </>
  );
}
