export const SMS_STATUS_LABEL: Record<string, string>;
export function toInt(s: unknown): number | null;

/** The part of the stored source (GET .../bank-sms `source`) the form needs. */
export interface BankSmsSourceLike {
  auto_verify?: boolean;
  configured?: boolean;
  is_enabled?: boolean;
  senders?: string[];
  settings: {
    window_minutes: number;
    time_tolerance_minutes: number;
    require_claimed_time: boolean;
    max_auto_amount_rial?: number | null;
    account_number?: string | null;
  };
}

/** Form state: every text input is a string (Persian digits are accepted), switches are booleans. */
export interface BankSmsForm {
  auto_verify: boolean;
  is_enabled: boolean;
  senders: string;
  window_minutes: string;
  time_tolerance_minutes: string;
  require_claimed_time: boolean;
  max_auto_amount_rial: string;
  account_number: string;
}

/** The PUT .../bank-sms/source body. */
export interface BankSmsSourceBody {
  is_enabled: boolean;
  auto_verify: boolean;
  senders: string[];
  settings: {
    window_minutes: number | null;
    time_tolerance_minutes: number | null;
    require_claimed_time: boolean;
    max_auto_amount_rial: number | null;
    account_number: string | null;
  };
}

export function formFromSource(source: BankSmsSourceLike): BankSmsForm;
export function sourceBody(form: BankSmsForm): BankSmsSourceBody;
