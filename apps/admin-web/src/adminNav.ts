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
  BellRing,
  Megaphone,
  UserPlus,
  Gift,
  Award,
  UsersRound,
  Zap,
} from 'lucide-react';

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
    'فروش و عملیات',
    [
      ['سفارش‌ها', Package, 'orders'],
      ['پرداخت‌ها', CreditCard, 'payments'],
      ['اکانت‌های VPN', Server, 'vpn'],
      ['تیکت‌ها', Ticket, 'tickets'],
    ],
  ],
  [
    'مشتریان',
    [
      ['کاربران', Users, 'users'],
      ['هویت', Fingerprint, 'identity'], // customer identity review / auto-link / trusted devices
    ],
  ],
  [
    'فروشگاه‌ها و نمایندگان',
    [
      ['فروشگاه‌ها', Store, 'stores'], // the store hub: profile, panel access, volume, prices, API, notices, bots
      ['درخواست‌های نمایندگی', UserPlus, 'reseller-applications'], // + tab «اقدامات تکمیلی» (former «کارهای دستی»)
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
    'زیرساخت و عملیات پنل',
    [
      ['پنل‌ها و سرورها', PanelTop, 'panels'],
      ['سلامت زیرساخت', ShieldCheck, 'infra-health'],
      ['عملیات پنل', Activity, 'panel-ops'],
      ['عملیات گروهی روی پنل', Zap, 'bulk-operations'], // infrastructure permission, previews + resumable runs on a panel
    ],
  ],
  [
    'ارتباطات',
    [
      ['پیام همگانی', Megaphone, 'broadcasts'],
      ['مرکز رویداد', BellRing, 'event-center'],
    ],
  ],
  [
    'سیستم و امنیت',
    [
      ['تنظیمات', Settings, 'settings'],
      ['دکمه‌های تلگرام', Paintbrush, 'button-styles'], // «system» permission (owner), so it lives with the owner-only settings
      ['ممیزی', ScrollText, 'audit'],
      ['تیم مدیریت', UsersRound, 'admin-team'],
      ['حساب من', UserRound, 'my-account'],
    ],
  ],
];
export const flat = groups.flatMap(([, items]) => items);
// The hash may carry deep-link params (#/panels?id=<id>); only the path picks the section. No legacy aliases: Melorin has never been released.
export const fromHash = () => (flat.find((x) => `#/${x[2]}` === window.location.hash.split('?')[0]) || flat[0])[0];
