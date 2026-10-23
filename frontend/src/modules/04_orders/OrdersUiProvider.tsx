/**
 * OrdersUiProvider — the module's window host (Spec 5.4, B4).
 *
 * The provider owns which order window is open — composer,
 * confirmation or detail — and the draft/`client_request_id` that
 * must survive between them. The five windows are shared `Popup`s
 * (UI Spec 3.3) that the provider renders itself — no ModalRoot, no
 * modal ids; a window closes through its own `onClose`, and a
 * confirmation (S) lies over its form (M), which stays mounted
 * underneath with its input intact.
 *
 * It also registers the Registry cell action `order` once — a click
 * on an order title, and the `#registry/order-N` entry request that
 * lands through the same registry mechanism, open the detail window —
 * and sends the «Приказ №N подан» / «Вердикт … записан» messages to the
 * shared Notice bar.
 * The verdict flow always lands back on the order's detail window —
 * it reloads on re-entry — and bumps `assignedRefreshKey` so the
 * «Ожидают вердикт» list refetches (Spec 5.4).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { registerCellAction } from '../03_registry/lib/cellActions';
import { clearFormDraft } from '../../shared/formDraft';
import { SUCCESS_RU } from '../../shared/texts/success.ru';
import { useNotice } from '../../shared/ui';
import { ConfirmSubmitModal } from './ConfirmSubmitModal';
import { OrderComposer } from './OrderComposer';
import { OrderDetailModal } from './OrderDetailModal';
import { registerOrdersTableFilters } from './registryFilters';
import { ConfirmVerdictModal, VerdictComposer } from './VerdictComposer';

/** formDraft keys — one per form, verdicts additionally per order. */
export const ORDER_DRAFT_KEY = 'order-composer';
export const verdictDraftKey = (orderNumber: number): string =>
  `verdict-composer:${orderNumber}`;

/** The values the composer hands to the confirmation window. */
export interface OrderDraft {
  title: string;
  summary: string;
  articleUrl: string;
}

/** A coded server error bounced from the confirmation back to the form. */
export interface ComposerServerError {
  code: string;
  message: string;
}

export type OrdersWindow =
  | {
      view: 'composer';
      /** UUID created on open, kept until success or close (INV-O9). */
      requestId: string;
      draft: OrderDraft;
      error: ComposerServerError | null;
    }
  | { view: 'confirm'; requestId: string; draft: OrderDraft }
  | { view: 'detail'; number: number }
  | {
      view: 'verdict-composer';
      /** The order the verdict is written for. */
      number: number;
      draft: OrderDraft;
      error: ComposerServerError | null;
    }
  | { view: 'verdict-confirm'; number: number; draft: OrderDraft };

const EMPTY_DRAFT: OrderDraft = { title: '', summary: '', articleUrl: '' };

interface OrdersUiContextValue {
  orderWindow: OrdersWindow | null;
  /** «Подать приказ» — opens the composer with a fresh request id. */
  openComposer: () => void;
  /** Registry action `order:<number>` — opens the detail window. */
  openOrder: (number: number) => void;
  /** Composer → confirmation, carrying the entered values. */
  toConfirm: (draft: OrderDraft) => void;
  /** Confirmation → composer; `error` is shown at a field or as a banner. */
  backToComposer: (error: ComposerServerError | null) => void;
  /** Any dismissal — the draft and the request id are dropped. */
  closeWindow: () => void;
  /** Successful submit — close and show «Приказ №N подан». */
  notifySubmitted: (number: number) => void;
  /**
   * Bumped when the judge's queue may have changed — the «Ожидают
   * вердикт» list refetches on it.
   */
  assignedRefreshKey: number;
  /** «Написать вердикт» (list row or detail window) — opens the verdict composer. */
  openVerdictComposer: (number: number) => void;
  /** Verdict composer → confirmation, carrying the entered values. */
  toVerdictConfirm: (draft: OrderDraft) => void;
  /** Confirmation → verdict composer; `error` is shown at a field. */
  backToVerdictComposer: (error: ComposerServerError | null) => void;
  /**
   * ORDER_VERDICT_EXISTS / ORDER_VERDICT_FORBIDDEN — the `errorText`
   * of the refusal is shown in the shared notice bar, the composer
   * closes and the detail window plus the assigned list reload.
   */
  verdictRejected: (number: number, message: string) => void;
  /** Successful verdict — back to the order's detail, notice, list refresh. */
  notifyVerdictSubmitted: (number: number) => void;
}

const OrdersUiContext = createContext<OrdersUiContextValue | null>(null);

export function useOrdersUi(): OrdersUiContextValue {
  const ctx = useContext(OrdersUiContext);
  if (!ctx) {
    throw new Error('useOrdersUi must be used inside OrdersUiProvider');
  }
  return ctx;
}

export function OrdersUiProvider({ children }: { children: ReactNode }) {
  const [orderWindow, setOrderWindow] = useState<OrdersWindow | null>(null);
  const notify = useNotice();
  const [assignedRefreshKey, setAssignedRefreshKey] = useState(0);

  const openComposer = useCallback(() => {
    setOrderWindow({
      view: 'composer',
      requestId: crypto.randomUUID(),
      draft: EMPTY_DRAFT,
      error: null,
    });
  }, []);

  const openOrder = useCallback((number: number) => {
    if (!Number.isInteger(number) || number < 1) {
      return;
    }
    setOrderWindow({ view: 'detail', number });
  }, []);

  // The Registry's `order:<number>` action and the «Назначены мне»
  // table filter — one registration each for the session;
  // re-registering replaces (cellActions / tableFilterExtensions
  // semantics).
  useEffect(() => {
    registerCellAction('order', (arg) => openOrder(Number(arg)));
    registerOrdersTableFilters();
  }, [openOrder]);

  const toConfirm = useCallback((draft: OrderDraft) => {
    setOrderWindow((w) =>
      w?.view === 'composer'
        ? { view: 'confirm', requestId: w.requestId, draft }
        : w,
    );
  }, []);

  const backToComposer = useCallback((error: ComposerServerError | null) => {
    setOrderWindow((w) =>
      w?.view === 'confirm'
        ? {
            view: 'composer',
            requestId: w.requestId,
            draft: w.draft,
            error,
          }
        : w,
    );
  }, []);

  const closeWindow = useCallback(() => {
    setOrderWindow(null);
  }, []);

  const notifySubmitted = useCallback(
    (number: number) => {
      // The send succeeded — the composer's stored draft is spent.
      clearFormDraft(ORDER_DRAFT_KEY);
      setOrderWindow(null);
      notify(SUCCESS_RU.orderSubmitted(number));
    },
    [notify],
  );

  const openVerdictComposer = useCallback((number: number) => {
    if (!Number.isInteger(number) || number < 1) {
      return;
    }
    setOrderWindow({
      view: 'verdict-composer',
      number,
      draft: EMPTY_DRAFT,
      error: null,
    });
  }, []);

  const toVerdictConfirm = useCallback((draft: OrderDraft) => {
    setOrderWindow((w) =>
      w?.view === 'verdict-composer'
        ? { view: 'verdict-confirm', number: w.number, draft }
        : w,
    );
  }, []);

  const backToVerdictComposer = useCallback(
    (error: ComposerServerError | null) => {
      setOrderWindow((w) =>
        w?.view === 'verdict-confirm'
          ? {
              view: 'verdict-composer',
              number: w.number,
              draft: w.draft,
              error,
            }
          : w,
      );
    },
    [],
  );

  // Both verdict endings land back on the order's detail window:
  // leaving the verdict views and re-entering `detail` remounts its
  // loader, and the assigned list refetches via `assignedRefreshKey`.
  const finishVerdict = useCallback(
    (number: number, message: string) => {
      setOrderWindow({ view: 'detail', number });
      setAssignedRefreshKey((k) => k + 1);
      notify(message);
    },
    [notify],
  );

  const verdictRejected = useCallback(
    (number: number, message: string) => finishVerdict(number, message),
    [finishVerdict],
  );

  const notifyVerdictSubmitted = useCallback(
    (number: number) => {
      // The verdict send succeeded — that order's draft is spent.
      clearFormDraft(verdictDraftKey(number));
      finishVerdict(number, SUCCESS_RU.verdictSubmitted(number));
    },
    [finishVerdict],
  );

  return (
    <OrdersUiContext.Provider
      value={{
        orderWindow,
        openComposer,
        openOrder,
        toConfirm,
        backToComposer,
        closeWindow,
        notifySubmitted,
        assignedRefreshKey,
        openVerdictComposer,
        toVerdictConfirm,
        backToVerdictComposer,
        verdictRejected,
        notifyVerdictSubmitted,
      }}
    >
      {children}
      {/* The five windows mount only while a window is open — the
          composer keeps its input under an S confirmation. */}
      {orderWindow !== null && (
        <>
          <OrderComposer />
          <ConfirmSubmitModal />
          <OrderDetailModal />
          <VerdictComposer />
          <ConfirmVerdictModal />
        </>
      )}
    </OrdersUiContext.Provider>
  );
}
