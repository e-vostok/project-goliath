/**
 * DTO types for module 04_orders (Spec 5.2).
 * Mirrors backend/src/modules/_04_orders/dto.py — no field ever
 * identifies the judge (INV-O5); `can_write_verdict` is computed
 * server-side per viewer.
 */

export interface OrderCreateRequest {
  title: string;
  summary: string;
  article_url: string;
  /** UUID — the submission idempotency key (INV-O9). */
  client_request_id: string;
}

export interface VerdictCreateRequest {
  title: string;
  summary: string;
  article_url: string;
}

export interface OrderRulesDTO {
  title_min_length: number;
  title_max_length: number;
  summary_min_length: number;
  summary_max_length: number;
  url_max_length: number;
  /** author.max_unresolved_orders — the author's pending-order limit. */
  max_unresolved_orders: number;
  /** The caller's orders without a verdict right now. */
  unresolved_orders: number;
}

export interface NationMarkDTO {
  name: string;
  color: string;
  /** Submission-time short-name snapshot (INV-O6). */
  short_name: string;
  /** Flag URL; null when the nation has no uploaded flag. */
  flag_url: string | null;
}

export interface VerdictDTO {
  title: string;
  summary: string;
  article_url: string;
}

export interface OrderDetailDTO {
  number: number;
  nation: NationMarkDTO;
  title: string;
  summary: string;
  article_url: string;
  /** The "Распределение" stage happened (a judge exists). */
  distributed: boolean;
  verdict: VerdictDTO | null;
  /** Verdict deadline passed and no verdict yet. */
  overdue: boolean;
  /** The viewer is the assigned judge and no verdict yet. */
  can_write_verdict: boolean;
}

export interface AssignedOrderDTO {
  number: number;
  nation: NationMarkDTO;
  title: string;
  summary: string;
  article_url: string;
  /** «15.10.2026 21:21» in tick_timezone — shown to the judge as-is. */
  deadline_text: string;
  overdue: boolean;
}

/** The caller's orders awaiting their verdict, soonest deadline first. */
export interface AssignedOrdersDTO {
  items: AssignedOrderDTO[];
}

/** Error codes this module maps to fields/banners (Spec 5.3). */
export const OrderErrorCodes = {
  ORDER_NATION_REQUIRED: 'ORDER_NATION_REQUIRED',
  ORDER_AUTHOR_LIMIT_REACHED: 'ORDER_AUTHOR_LIMIT_REACHED',
  ORDER_TITLE_INVALID: 'ORDER_TITLE_INVALID',
  ORDER_SUMMARY_INVALID: 'ORDER_SUMMARY_INVALID',
  ORDER_URL_INVALID: 'ORDER_URL_INVALID',
  ORDER_NOT_FOUND: 'ORDER_NOT_FOUND',
  ORDER_VERDICT_FORBIDDEN: 'ORDER_VERDICT_FORBIDDEN',
  ORDER_VERDICT_EXISTS: 'ORDER_VERDICT_EXISTS',
} as const;
