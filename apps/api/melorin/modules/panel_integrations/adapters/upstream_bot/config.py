"""Default configuration of the upstream-bot adapter.

Every button text is configurable because the parent bot may rename its menus. Pure data: no behaviour lives here.
"""

DEFAULTS = {
    "menu_buy": "خرید اکانت",
    "service_button": "سرویس اقتصادی",
    "confirm_button": "تایید خرید",
    "cancel_button": "انصراف",
    "start_command": "/start",
    "menu_purchases": "خریدهای من",
    "search_button": "جستجوی اکانت",
    "refund_button": "مرجوعی اکانت",
    "refund_confirm_button": "تایید میکنم",
    "link_button": "لینک",
    "status_ttl": 60,  # seconds a live read of the account screen is reused
    "max_price": 0,  # toman; 0 = refuse to buy (forces the admin to set a safety cap)
    "step_timeout": 25,
    "delivery_timeout": 60,
    "poll_interval": 1.2,
    "lock_ttl": 180,
    "plans": [],  # optional explicit [{"traffic_gb": 10, "months": 1, "label": "10 گیگ یک ماهه"}]
    # Renewal (verified on the real screens, 24 Oct 2026). Set {"enabled": false} to turn automatic renewals off.
    "renew": {
        "enabled": True,
        "renew_button": "تمدید اکانت",
        "confirm_button": "تایید تمدید",
        "cancel_button": "برگشت",
        "success_words": ["با موفقیت تمدید"],
        "settle_window": 600,  # seconds a confirmed-but-unanswered renewal blocks a second payment (retry reads the account instead)
    },
}
