import { lazy } from 'react';
import { useCall } from '../api/api.ts';
import type { Json, Toast, ViewApi } from '../shared/types.ts';
import { ChangeAdminPassword } from '../features/settings/ChangeAdminPassword.tsx';
const ReportsView = lazy(() => import('../features/reports/ReportsView.tsx'));
const PanelsView = lazy(() => import('../features/panels/PanelsView.tsx'));
const InfraHealthView = lazy(() => import('../features/panel-operations/InfraHealthView.tsx'));
const InfraOpsHubView = lazy(() => import('../features/panel-operations/InfraOpsHubView.tsx'));
const ProductsView = lazy(() => import('../features/catalog/ProductsView.tsx'));
const BundlesView = lazy(() => import('../features/catalog/BundlesView.tsx'));
const TicketsView = lazy(() => import('../features/tickets/TicketsView.tsx'));
const PaymentsView = lazy(() => import('../features/payments/PaymentsView.tsx'));
const ResellerOnboardingView = lazy(() => import('../features/stores/ResellerOnboardingView.tsx'));
const BroadcastView = lazy(() => import('../features/broadcast/BroadcastView.tsx'));
const ButtonStylesView = lazy(() => import('../features/settings/ButtonStylesView.tsx'));
const EventCenterView = lazy(() => import('../features/event-center/EventCenterView.tsx'));
const AdminTeamView = lazy(() => import('../features/settings/AdminTeamView.tsx'));
const MyAccountView = lazy(() => import('../features/settings/MyAccountView.tsx'));
const IdentityHubView = lazy(() => import('../features/identity/IdentityHubView.tsx'));
const OrdersView = lazy(() => import('../features/orders/OrdersView.tsx'));
const VpnAccountsView = lazy(() => import('../features/vpn-accounts/VpnAccountsView.tsx'));
const UsersView = lazy(() => import('../features/customers/UsersView.tsx'));
const StoreHubView = lazy(() => import('../features/stores/StoreHubView.tsx'));
const AuditView = lazy(() => import('../features/settings/AuditView.tsx'));
const ReferralProgramsView = lazy(() => import('../features/referrals/ReferralProgramsView.tsx'));
const LoyaltyClubView = lazy(() => import('../features/loyalty/LoyaltyClubView.tsx'));
const Coupons = lazy(() => import('../features/coupons/CouponsView.tsx'));
const Settings = lazy(() => import('../features/settings/SettingsView.tsx'));

function MyAccount({ api, toast }: { api: ViewApi; toast: Toast }) {
  return (
    <MyAccountView me={api.me}>
      <ChangeAdminPassword api={api} toast={toast} />
    </MyAccountView>
  );
}

function Tickets({ api, toast }: { api?: Json; toast: Toast }) {
  const call = useCall(api);
  return <TicketsView call={call} toast={toast} />;
}

export const extraRoutes = {
  'گزارشات و نمودارها': ReportsView,
  'درخواست‌های نمایندگی': ResellerOnboardingView, // + tab «اقدامات تکمیلی» (the old «کارهای دستی» screen)
  'پیام همگانی': BroadcastView,
  'دکمه‌های تلگرام': ButtonStylesView,
  'مرکز رویداد': EventCenterView,
  'پایش و سلامت': InfraHealthView,
  'عملیات مدیریتی': InfraOpsHubView,
  سفارش‌ها: OrdersView,
  'اکانت‌های VPN': VpnAccountsView,
  کاربران: UsersView,
  فروشگاه‌ها: StoreHubView,
  پرداخت‌ها: PaymentsView,
  تیکت‌ها: Tickets,
  'محصولات VPN': ProductsView,
  'پنل‌ها و سرورها': PanelsView,
  'بسته‌های فروش': BundlesView,
  کوپن‌ها: Coupons,
  'برنامه‌های معرفی': ReferralProgramsView,
  'باشگاه مشتریان': LoyaltyClubView,
  تنظیمات: Settings,
  ممیزی: AuditView,
  هویت: IdentityHubView,
  'تیم مدیریت': AdminTeamView,
  'حساب من': MyAccount,
};
