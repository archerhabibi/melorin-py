// «درگاه‌ها» — where the main store receives money: card-to-card details and the Zarinpal merchant. The old screen kept
// this behind an accordion at the bottom of the transactions list; it is its own tab now and owns its own data.
import { useEffect, useState } from 'react';
import type { RequestBody } from '@melorin/api-client';
import type { typedClient } from '../../api/api.ts';
import { errText } from '../../shared/kit.tsx';
import { GatewaySettings } from './PaymentParts.tsx';
import type { Json, Toast } from '../../shared/types.ts';

type Client = ReturnType<typeof typedClient>;
/** A row of GET /api/v1/admin/payment-destinations, as far as this tab reads it. */
interface DestinationRow {
  provider: string;
  merchant_id?: string;
  has_access_token?: boolean;
  public_config?: { sandbox?: boolean } & Record<string, unknown>;
}
type DestinationBody = RequestBody<'/api/v1/admin/payment-destinations/{provider}', 'put'>;

export default function GatewaysTab({ client, toast }: { client: Client; toast: Toast }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    // main store destinations: the same per-store model resellers use (card number / holder / bank, Zarinpal merchant id + sandbox)
    let alive = true;
    client
      .get('/api/v1/admin/payment-destinations')
      .then((r) => (r.data as DestinationRow[] | undefined) ?? [])
      .then((rows) => {
        if (!alive) return;
        const z = rows.find((x) => x.provider === 'zarinpal');
        setSettings({
          manual_card: rows.find((x) => x.provider === 'manual_card')?.public_config,
          zarinpal: z && {
            merchant_id: z.merchant_id || '',
            sandbox: !!z.public_config?.sandbox,
            has_access_token: !!z.has_access_token,
          },
        });
      })
      .catch(() => alive && setSettings({}));
    return () => {
      alive = false;
    };
  }, [client]);

  const saveSetting = async (provider: string, value: Json) => {
    const body =
      provider === 'zarinpal'
        ? {
            is_enabled: true,
            public_config: { sandbox: !!value.sandbox },
            secret: {
              merchant_id: value.merchant_id.trim(),
              ...(value.access_token?.trim() ? { access_token: value.access_token.trim() } : {}),
              ...(value.clear_access_token ? { clear_access_token: true } : {}),
            },
          }
        : { is_enabled: true, public_config: value };
    try {
      const { response: r } = await client.put('/api/v1/admin/payment-destinations/{provider}', {
        params: { path: { provider } },
        // the OpenAPI schema renders free-form objects as Record<string, never>; the server validates the real shape
        body: body as unknown as DestinationBody,
      });
      if (r.ok) {
        toast('تنظیمات ذخیره شد');
        const saved =
          provider === 'zarinpal'
            ? {
                ...value,
                has_access_token: value.clear_access_token
                  ? false
                  : !!value.access_token?.trim() || !!value.has_access_token,
                access_token: '',
                clear_access_token: false,
              }
            : value;
        setSettings((x) => ({ ...x, [provider]: saved }));
      } else toast(await errText(r, 'ذخیره تنظیمات ناموفق بود'));
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    }
  };

  if (!settings) return <div className="card skel h-48" />;
  return <GatewaySettings obj={settings} save={saveSetting} />;
}
