import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  BarChart3,
  CreditCard,
  Fingerprint,
  LayoutDashboard,
  Package,
  Paintbrush,
  PanelTop,
  Percent,
  Server,
  Settings,
  ShieldCheck,
  Ticket,
  Users,
  Boxes,
  ScrollText,
  Store,
  Layers,
  UserRound,
  ListChecks,
  BellRing,
  Megaphone,
  UserPlus,
  Gift,
  Award,
  UsersRound,
  Zap,
} from 'lucide-react';
import { legacyHash } from './infra.tsx';

// Section keys are Persian labels (AdminSections/AdminExtra route on them); slug drives the URL hash.
export const groups: [string, [string, LucideIcon, string][], string?][] = [
  [
    'نمای کلی',
    [
      ['داشبورد', LayoutDashboard, 'home'],
      ['گزارشات و نمودارها', BarChart3, 'reports'],
    ],
  ],
  [
    'عملیات',
    [
      ['سفارش‌ها', Package, 'orders'],
      ['پرداخت‌ها', CreditCard, 'payments'],
      ['اکانت‌های VPN', Server, 'vpn'],
      ['عملیات گروهی روی پنل', Zap, 'bulk-operations'], // acts on VPN accounts, so it sits next to them
      ['تیکت‌ها', Ticket, 'tickets'],
    ],
  ],
  [
    'مشتریان و فروشگاه‌ها',
    [
      ['کاربران', Users, 'users'],
      ['هویت', Fingerprint, 'identity'], // customer identity review / auto-link / trusted devices
      ['فروشگاه‌ها', Store, 'stores'],
      ['درخواست‌های نمایندگی', UserPlus, 'reseller-applications'],
      ['کارهای دستی', ListChecks, 'manual-tasks'],
    ],
  ],
  [
    'کاتالوگ و بازاریابی',
    [
      ['بسته‌های فروش', Layers, 'bundles'],
      ['محصولات VPN', Boxes, 'products'],
      ['کوپن‌ها', Percent, 'coupons'],
      ['برنامه‌های معرفی', Gift, 'referral-programs'],
      ['باشگاه مشتریان', Award, 'loyalty-club'],
    ],
    'مسیر فروش: پنل و سرور ← بسته فروش ← پکیج',
  ],
  [
    'ارتباطات',
    [
      ['پیام همگانی', Megaphone, 'broadcasts'],
      ['مرکز رویداد', BellRing, 'event-center'],
      ['دکمه‌های تلگرام', Paintbrush, 'button-styles'],
    ],
  ],
  [
    'زیرساخت',
    [
      ['پنل‌ها و سرورها', PanelTop, 'panels'],
      ['سلامت زیرساخت', ShieldCheck, 'infra-health'],
      ['عملیات پنل', Activity, 'panel-ops'],
    ],
  ],
  [
    'سیستم',
    [
      ['تنظیمات', Settings, 'settings'],
      ['ممیزی', ScrollText, 'audit'],
      ['تیم مدیریت', UsersRound, 'admin-team'],
      ['حساب من', UserRound, 'my-account'],
    ],
  ],
];
export const flat = groups.flatMap(([, items]) => items);
// The hash may carry deep-link params (#/servers?panel=<id>); only the path picks the section.
// Old bookmarks of the removed #/servers screen are rewritten to #/panels (servers live inside their panel now).
if (typeof window !== 'undefined') {
  const moved = legacyHash(window.location.hash);
  if (moved) window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${moved}`);
}
export const fromHash = () => (flat.find((x) => `#/${x[2]}` === window.location.hash.split('?')[0]) || flat[0])[0];
