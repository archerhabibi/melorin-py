# Melorin — فهرست اسناد
نسخه 1.1 | به‌روزرسانی‌شده بر اساس پاسخ‌های مالک محصول در 2026-10-09. این بسته شامل نیازمندی‌ها، طراحی و تصمیم‌های ثبت‌شده است؛ تصمیم‌های باقی‌مانده فقط در سند 10 فهرست شده‌اند.
1. 01-Requirements-SRS.md — سند جامع نیازمندی‌ها
2. 02-Architecture.md — معماری
3. 03-Technical-Design.md — طراحی فنی
4. 04-Domain-Data-Model.md — مدل دامنه و داده
5. 05-API-Contracts.md — API و Webhook
6. 06-Security.md — امنیت و مجوزها
7. 07-Financial-Order-Provisioning.md — مالی، Wallet-first checkout، Coupon، سفارش و Provisioning
8. 08-Operations-DR.md — استقرار و بازیابی
9. 09-Testing.md — تست و کیفیت
10. 10-Roadmap-Open-Decisions.md — نقشه راه و تصمیم‌های باز باقی‌مانده
11. 11-Channel-Specifications.md — مشخصات کانال‌ها

مرجع نیازمندی‌ها: سند 01. قوانین مالی و چرخه سفارش: سند 07. معماری: سند 02. تصمیم‌های قطعی و موارد باز در سند 10 تفکیک شده‌اند. همه خریدها Wallet-first هستند؛ کیف پول، ارز و مقصد پرداخت Store-scoped است. Reseller باید پیش از فعال‌سازی مشتری Main Store باشد. ARQ + Redis، Reseller API و Outgoing Webhook در V1 مصوب‌اند.
