import { lazy } from 'react';
import { authFetch } from './api.ts';
import type { Json, Toast, ViewApi } from './types.ts';
import { ChangeAdminPassword } from './SettingsView.tsx';
const ReportsView = lazy(() => import('./ReportsView.tsx'));
const PanelsView = lazy(() => import('./PanelsView.tsx'));
const InfraHealthView = lazy(() => import('./InfraHealthView.tsx'));
const PanelOpsView = lazy(() => import('./PanelOpsView.tsx'));
const BulkOperationsView = lazy(() => import('./BulkOperationsView.tsx'));
const ProductsView = lazy(() => import('./ProductsView.tsx'));
const BundlesView = lazy(() => import('./BundlesView.tsx'));
const TicketsView = lazy(() => import('./TicketsView.tsx'));
const PaymentsView = lazy(() => import('./PaymentsView.tsx'));
const ResellerApplicationsView = lazy(() => import('./ResellerApplicationsView.tsx'));
const ManualTasksView = lazy(() => import('./ManualTasksView.tsx'));
const BroadcastView = lazy(() => import('./BroadcastView.tsx'));
const ButtonStylesView = lazy(() => import('./ButtonStylesView.tsx'));
const EventCenterView = lazy(() => import('./EventCenterView.tsx'));
const AdminTeamView = lazy(() => import('./AdminTeamView.tsx'));
const MyAccountView = lazy(() => import('./MyAccountView.tsx'));
const IdentityHubView = lazy(() => import('./IdentityHubView.tsx'));
const OrdersView = lazy(() => import('./OrdersView.tsx'));
const VpnAccountsView = lazy(() => import('./VpnAccountsView.tsx'));
const UsersView = lazy(() => import('./UsersView.tsx'));
const StoreHubView = lazy(() => import('./StoreHubView.tsx'));
const AuditView = lazy(() => import('./AuditView.tsx'));
const ReferralProgramsView = lazy(() => import('./ReferralProgramsView.tsx'));
const LoyaltyClubView = lazy(() => import('./LoyaltyClubView.tsx'));
const Coupons = lazy(() => import('./CouponsView.tsx'));
const Settings = lazy(() => import('./SettingsView.tsx'));

function MyAccount({ api, toast }: { api: ViewApi; toast: Toast }) {
  return (
    <MyAccountView me={api.me}>
      <ChangeAdminPassword api={api} toast={toast} />
    </MyAccountView>
  );
}

function Tickets({ api, toast }: { api?: Json; toast: Toast }) {
  const call = (p: Json, o = {}) => authFetch(api.base, p, o);
  return <TicketsView call={call} toast={toast} />;
}

export const extraRoutes = {
  'گزارشات و نمودارها': ReportsView,
  'درخواست‌های نمایندگی': ResellerApplicationsView,
  'کارهای دستی': ManualTasksView,
  'پیام همگانی': BroadcastView,
  'دکمه‌های تلگرام': ButtonStylesView,
  'مرکز رویداد': EventCenterView,
  'سلامت زیرساخت': InfraHealthView,
  'عملیات پنل': PanelOpsView,
  'عملیات گروهی': BulkOperationsView,
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
