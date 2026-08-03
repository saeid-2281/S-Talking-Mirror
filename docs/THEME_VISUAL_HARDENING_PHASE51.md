# Phase 51 — Theme, Selection, Icon & Layout Hardening

## هدف

این فاز مشکلات بصری گزارش‌شده در تم روشن و تاریک را رفع می‌کند و یک تم سوم با ظاهر خاکستری تیره و حرفه‌ای اضافه می‌کند.

## تغییرات اصلی

- تم جدید `Graphite` با سطوح خاکستری خنثی، کنتراست بالا و Accent آبی کنترل‌شده.
- تعریف مستقل `selected_text` برای همه تم‌ها تا متن سطر انتخاب‌شده در حالت Active و Inactive خوانا بماند.
- اصلاح `QPalette.HighlightedText` و قواعد Selection برای TableView، TableWidget، ListView و TreeView.
- بازسازی آیکون‌های ثبت‌شده پس از تغییر Theme تا آیکون‌های ساخته‌شده پیش از Apply Theme در تم روشن سفید و نامرئی نمانند.
- جایگزینی فلش Native بخش‌های Collapsible با Chevronهای SVG هم‌تراز و وسط‌چین.
- یکسان‌سازی ارتفاع و تراز Start Generation، Preflight، Pause و Stop.
- بهبود Hover، Header، Border، Surface و Control geometry در Voice Browser و Workspace اصلی.
- حفظ Theme tokenهای تثبیت‌شده و تمام Handleهای عمومی.

## Release Candidate Hotfix

نام Package نهایی همیشه به‌شکل زیر Canonical می‌شود، حتی اگر Readiness Service یک فایل موقت با نام دیگری برگرداند:

`S-Talking-<version>-portable.zip`

## Schema

Database Schema بدون تغییر و همچنان 22 است.


## Hotfix 3 — Deterministic Layout and Test Runtime

- حذف محدودیت ارتفاع QSS از `generationActionBar`؛ ارتفاع واقعی اکنون فقط توسط Widget کنترل می‌شود و قرارداد 44px حفظ می‌شود.
- جداکردن Compact شدن Queue از Icon-only شدن Toolbar؛ در پنجره عریض، باریک‌شدن ناحیه مرکزی دیگر برچسب‌های Toolbar را حذف نمی‌کند.
- محدودکردن Icon refresh به درخت زنده `MainWindow` و Cache کردن SVGهای رندرشده.
- جلوگیری از Apply مجدد Stylesheet سراسری وقتی Theme تغییر نکرده است.
- پاک‌سازی Top-level Widgetها و Deferred Deleteها بین تست‌های Qt برای جلوگیری از رشد تجمعی Widgetها، Timerها و Style repolish.
- آزادسازی Source بومی `QMediaPlayer` هنگام بسته‌شدن برنامه تا فایل WAV در Windows قفل نماند.

علت افزایش زمان Full Suite از حدود چهار دقیقه به بیش از یک ساعت، ترکیب Apply مجدد Stylesheet روی کل `QApplication` و Scan/Rerender سراسری آیکون‌ها برای هر `MainWindow` بود. با ماندن Widgetهای بسته‌شده در QApplication، هزینه هر تست به‌صورت تجمعی افزایش می‌یافت.
