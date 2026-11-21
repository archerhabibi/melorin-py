// Compile-time contract check (run by `npm run typecheck`): proves the generated schema flows through the client types.
import { createApiClient } from './index';

const api = createApiClient({ baseUrl: 'https://example.test' });

export async function usage() {
  const res = await api.get('/api/v1/admin/audit');
  if (res.data) {
    const rows: unknown = res.data;
    return rows;
  }
  const receipt = await api.rawGet('/api/v1/admin/payments/{payment_id}/receipt', {
    params: { path: { payment_id: 'payment-1' } },
  });
  const rawResponse: Response = receipt;
  // @ts-expect-error missing required path parameter must not type-check
  await api.rawGet('/api/v1/admin/payments/{payment_id}/receipt', { params: { path: {} } });
  // routes without path parameters need no init at all
  await api.rawGet('/api/v1/admin/audit');
  // @ts-expect-error a route that declares path parameters cannot be called without them
  await api.rawGet('/api/v1/admin/payments/{payment_id}/receipt');
  // @ts-expect-error unknown path must not type-check
  await api.rawGet('/api/v1/definitely-not-a-route');
  // @ts-expect-error unknown path must not type-check
  await api.get('/api/v1/definitely-not-a-route');
  return rawResponse;
}
