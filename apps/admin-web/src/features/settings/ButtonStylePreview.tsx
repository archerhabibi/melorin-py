import { SAMPLE_INLINE, SAMPLE_REPLY, renderInline, renderReply } from './buttonStyles.ts';
import type { ButtonStyleConfig, RenderedButton } from './buttonStyles.ts';

export function TgButton({ b }: { b: RenderedButton }) {
  return (
    <span className="tg-btn" data-style={b.style ?? 'none'}>
      {b.icon && (
        <span className="tg-btn-icon" title="ایموجی پریمیوم (در تلگرام به‌صورت ایموجی واقعی نمایش داده می‌شود)">
          ✦
        </span>
      )}
      <span className="truncate">{b.text}</span>
    </span>
  );
}

/** A Telegram-like chat with the sample keyboards, rendered from the draft exactly as the bots would build them. */
export function Preview({ cfg }: { cfg: ButtonStyleConfig }) {
  return (
    <div className="tg-phone" aria-label="پیش‌نمایش دکمه‌ها" dir="rtl">
      <div className="tg-bubble">پیش‌نمایش دکمه‌های اینلاین (زیر پیام)</div>
      <div className="tg-kb">
        {SAMPLE_INLINE.rows.map((row, i) => (
          <div key={i} className="tg-row">
            {row.map(([text, key]) => (
              <TgButton key={key + text} b={renderInline(cfg, key, text)} />
            ))}
          </div>
        ))}
      </div>
      <div className="tg-bubble mt-4">پیش‌نمایش کیبورد پایین (منوی اصلی)</div>
      <div className="tg-kb tg-kb-reply">
        {SAMPLE_REPLY.map((row, i) => (
          <div key={i} className="tg-row">
            {row.map((text) => (
              <TgButton key={text} b={renderReply(cfg, text)} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
