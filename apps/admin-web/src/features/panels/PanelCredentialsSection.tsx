import { Field, Section, Segmented, Toggle } from '../../shared/kit.tsx';
import { UpstreamSettings } from './UpstreamBotFields.tsx';
import { Chips } from './panelUi.tsx';

export function PanelCredentialsSection({ edit, err, f, groups, isUb, k, set, setUb, show }: Record<string, any>) {
  return (
    <>
      {f.kind !== 'mock' && (
        <Section title={`${edit ? '' : '۴ · '}تنظیمات ${k.title}`}>
          {f.kind === 'sanaei' && (
            <>
              <Field
                label="Inbound IDها"
                error={show('inbounds') || undefined}
                hint="شناسه Inboundهایی که کلاینت در آن‌ها ساخته می‌شود؛ بعد از هر عدد Enter بزنید"
              >
                <Chips values={f.inbounds} onChange={set('inbounds')} placeholder="مثلاً 1" />
              </Field>
              <Field
                label="آدرس ساب‌اسکریپشن"
                error={show('subUrl') || undefined}
                hint="Sub Port + Sub Path از Settings → Subscription پنل"
              >
                <input
                  dir="ltr"
                  spellCheck={false}
                  className="inp"
                  value={f.subUrl}
                  placeholder="https://sub.example.com:2096/sub"
                  onChange={(e) => set('subUrl')(e.target.value)}
                />
              </Field>
              <Field label="سبک API">
                <Segmented
                  label="سبک API"
                  value={f.apiStyle}
                  onChange={set('apiStyle')}
                  options={[
                    ['auto', 'خودکار'],
                    ['v3', 'v3'],
                    ['legacy', 'Legacy'],
                  ]}
                />
              </Field>
            </>
          )}
          {isUb && <UpstreamSettings ub={f.ub} setUb={setUb} err={err} show={show} />}
          {f.kind === 'pasarguard' && (
            <>
              <Segmented
                label="محدوده"
                value={f.scope}
                onChange={set('scope')}
                options={[
                  ['groups', 'Group IDs'],
                  ['template', 'قالب کاربر'],
                ]}
              />
              {f.scope === 'groups' ? (
                <Field label="Group IDها" error={show('scope') || undefined}>
                  <Chips values={f.groups} onChange={set('groups')} placeholder="مثلاً 1" />
                </Field>
              ) : (
                <Field label="شناسه قالب کاربر" error={show('scope') || undefined}>
                  <input
                    dir="ltr"
                    inputMode="numeric"
                    className="inp"
                    value={f.tpl}
                    onChange={(e) => set('tpl')(e.target.value.replace(/\D/g, ''))}
                  />
                </Field>
              )}
            </>
          )}
          {!isUb && (
            <Toggle
              checked={f.verifyTls}
              onChange={set('verifyTls')}
              label="بررسی گواهی TLS"
              hint="در محیط عملیاتی خاموش‌کردن آن مجاز نیست؛ فقط برای تست با گواهی self-signed."
            />
          )}
        </Section>
      )}
    </>
  );
}
