"""Reseller onboarding: what the admin must do by hand, and what the new reseller must do.

* ``ensure_admin_tasks`` writes the admin's manual checklist (Google console, BotFather, DNS) once per application and alerts
  every active super admin through the notification outbox (Telegram when the admin has a numeric Telegram ID).
* ``applicant_steps`` is the list shown to the applicant after registering (site and bot), driven by the application status.

Texts are Persian because both audiences are; the domain is interpolated so the admin can copy-paste.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from melorin.core import events
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import AdminTask, ResellerApplication

REVIEW = "review_application"
GOOGLE = "google_origin"
TELEGRAM = "telegram_login"
DNS = "dns_tls"
DOMAIN_KINDS = (GOOGLE, TELEGRAM, DNS)


def _review_task(a: ResellerApplication) -> tuple[str, str]:
    return (
        f"بررسی درخواست نمایندگی «{a.store_name}»",
        "درخواست جدید در بخش «درخواست‌های نمایندگی» منتظر تصمیم شماست. دلیل متقاضی را بخوانید و تأیید یا رد کنید.",
    )


def _domain_tasks(domain: str) -> list[tuple[str, str, str]]:
    return [
        (
            DNS,
            f"دامنه {domain}: اشاره به سرور و گواهی TLS",
            f"رکورد A دامنهٔ {domain} را به IP سرور Melorin بدهید و مطمئن شوید گواهی HTTPS برای آن صادر می‌شود؛ بدون این، سایت نماینده باز نمی‌شود.",
        ),
        (
            GOOGLE,
            f"گوگل: افزودن https://{domain} به Authorized JavaScript origins",
            "اگر ورود با گوگل فعال است: Google Cloud Console → APIs & Services → Credentials → همان OAuth client → "
            f"Authorized JavaScript origins → آدرس https://{domain} را اضافه و ذخیره کنید (Authorized redirect URIs خالی بماند).",
        ),
        (
            TELEGRAM,
            f"تلگرام: ثبت آدرس‌های {domain} در BotFather",
            "اگر «ورود مستقیم با تلگرام» فعال است: BotFather → ربات اصلی → Bot Settings → Web Login → Allowed URLs → این دو آدرس را اضافه کنید: "
            f"https://{domain} و https://{domain}/api/v1/auth/telegram/oidc/callback",
        ),
    ]


async def _super_admin_ids(session) -> list[uuid.UUID]:
    return list((await session.scalars(select(User.id).where(User.is_super_admin.is_(True), User.is_active.is_(True)))).all())


async def alert_admins(session, *, kind: str, title: str, body: str, key: str) -> None:
    """One notification per active super admin (own dedup key, so an outbox retry never repeats it)."""
    for admin_id in await _super_admin_ids(session):
        await events.emit(
            session,
            events.NOTIFY,
            {"user_id": admin_id, "kind": kind, "title": title, "body": body, "dedup_key": f"{key}:{admin_id}"},
        )


async def _add_task(session, a: ResellerApplication, kind: str, title: str, detail: str) -> AdminTask | None:
    exists = await session.scalar(select(AdminTask.id).where(AdminTask.kind == kind, AdminTask.application_id == a.id))
    if exists:
        return None
    t = AdminTask(kind=kind, application_id=a.id, store_id=a.store_id, title=title, detail=detail)
    session.add(t)
    return t


async def ensure_admin_tasks(session, a: ResellerApplication) -> list[AdminTask]:
    """Create the checklist rows that are known now (review always; domain tasks once the domain is known) and alert admins."""
    created: list[AdminTask] = []
    title, detail = _review_task(a)
    if t := await _add_task(session, a, REVIEW, title, detail):
        created.append(t)
        reason = (a.message or "").strip()
        await alert_admins(
            session,
            kind="admin_reseller_application",
            title="🆕 درخواست نمایندگی جدید",
            body=f"«{a.store_name}»\nدلیل متقاضی: {reason[:300]}\n\nبرای تصمیم‌گیری به پنل ادمین ← کارهای دستی بروید.",
            key=f"admin_task:{a.id}:{REVIEW}",
        )
    if a.domain:
        domain_created = [t for kind, title, detail in _domain_tasks(a.domain) if (t := await _add_task(session, a, kind, title, detail))]
        created += domain_created
        if domain_created:
            lines = "\n".join(f"• {t.title}" for t in domain_created)
            await alert_admins(
                session,
                kind="admin_manual_tasks",
                title="🛠 کار دستی برای نمایندهٔ جدید",
                body=f"نماینده «{a.store_name}» ثبت شد. این کارها باید دستی انجام شود:\n{lines}\n\nجزئیات: پنل ادمین ← کارهای دستی.",
                key=f"admin_task:{a.id}:domain",
            )
    return created


async def complete_review_task(session, a: ResellerApplication, admin_id) -> None:
    """The admin decided on the application: its «review» task is done by that very decision."""
    from melorin.core.db import utcnow

    t = await session.scalar(select(AdminTask).where(AdminTask.kind == REVIEW, AdminTask.application_id == a.id))
    if t and t.status == "open":
        t.status, t.done_by, t.done_at = "done", admin_id, utcnow()


def task_out(t: AdminTask, a: ResellerApplication | None = None) -> dict:
    return {
        "id": t.id,
        "kind": t.kind,
        "title": t.title,
        "detail": t.detail,
        "status": t.status,
        "application_id": t.application_id,
        "store_id": t.store_id,
        "store_name": a.store_name if a else None,
        "domain": a.domain if a else None,
        "created_at": t.created_at,
        "done_at": t.done_at,
    }


# ----------------------------------------------------------------------------------------------- applicant side
def applicant_steps(status: str, *, domain: str | None = None) -> list[dict]:
    """The checklist the new reseller sees. ``done`` is derived from the application status only."""
    approved = status in ("approved",)
    awaiting = status == "awaiting_details"
    return [
        {"title": "منتظر تأیید مدیریت بمانید", "detail": "درخواست شما و دلیلتان را مدیریت بررسی می‌کند؛ نتیجه همین‌جا و در ربات اطلاع داده می‌شود.", "done": awaiting or approved},
        {
            "title": "ساخت ربات تلگرام فروشگاه",
            "detail": "در @BotFather دستور /newbot را بزنید، نام و یوزرنیم ربات را انتخاب کنید و توکن را نگه دارید (آن را به کسی ندهید جز در همین فرم/ربات).",
            "done": approved,
        },
        {
            "title": "آماده‌کردن دامنهٔ فروشگاه",
            "detail": "یک دامنه یا زیردامنه تهیه کنید و رکورد A آن را به IP سرور اشاره دهید (IP را از مدیریت بپرسید).",
            "done": approved,
        },
        {
            "title": "ارسال دامنه و توکن ربات",
            "detail": "پس از تأیید، در ربات دستور /reseller را بزنید (یا از فرم سایت) و دامنه و توکن را بفرستید؛ فروشگاه شما همان لحظه ساخته می‌شود.",
            "done": approved,
        },
        {
            "title": "تنظیم قیمت‌ها و خرید آزمایشی",
            "detail": "از «پنل نماینده ← قیمت‌گذاری» قیمت فروش خود را بگذارید و یک خرید آزمایشی انجام دهید.",
            "done": False,
        },
        {
            "title": "منتظر تنظیمات دستی مدیریت بمانید",
            "detail": (
                f"مدیریت ورود با گوگل/تلگرام را برای دامنهٔ {domain or 'شما'} فعال می‌کند. تا آن زمان ممکن است دکمهٔ ورود روی سایت شما کار نکند."
            ),
            "done": False,
        },
        {"title": "معرفی ربات و سایت به مشتریان", "detail": "لینک ربات و سایت را برای مشتریان بفرستید؛ با «پیام همگانی» هم می‌توانید به آن‌ها خبر بدهید.", "done": False},
    ]


def steps_text(status: str, *, domain: str | None = None) -> str:
    return "\n".join(f"{i}. {s['title']} — {s['detail']}" for i, s in enumerate(applicant_steps(status, domain=domain), 1))
