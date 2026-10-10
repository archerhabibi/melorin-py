# تکمیل H012: quality gate و test/contract suite

H012 اصلاح و به پروژه اضافه شد. یک entrypoint واحد به نام `scripts/run_quality_gate.sh` و دستور `make quality-gate` ایجاد شد که به‌ترتیب runtime preflight، secret scan، lockfile check، release matrix، compileall، ruff و pytest را اجرا می‌کند. همین gate در GitHub Actions نیز فعال شد و test contract برای پوشش همه مراحل اضافه شد.

این کار پراکندگی گیت‌ها را جمع می‌کند، مسیر اجرای محلی و CI را همسان می‌سازد و failure را fail-fast نگه می‌دارد. در این sandbox اجرای gate کامل به‌دلیل نبود dependencyهای Python، npm، Docker و pytest ممکن نیست؛ source/AST/shell بررسی شدند و اجرای واقعی باید در CI/staging دارای registry و سرویس‌ها انجام شود.
