/**
 * OrdersUiProvider — the module's window host (Spec 5.4, B4).
 *
 * The provider owns which order window is open — composer,
 * confirmation or detail — and the draft/`client_request_id` that
 * must survive between them. The three windows are children of the
 * app's single `ModalRoot` in `AppShell` (the existing modal
 * mechanism, like `ModalConfirmDeleteNation`); the provider drives
 * AppShell's `activeModal` in both directions: opening a window sets
 * the matching modal id, and any external close (Esc, overlay, the
 * delete-nation card taking over) drops the window state.
 *
 * It also registers the Registry cell action `order` once — a click
 * on an order title, and the `#registry/order-N` entry request that
 * lands through the same registry mechanism, open the detail window —
 * and hosts the «Приказ №N подан» snackbar after a successful submit.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { Snackbar } from '@vkontakte/vkui';

import { registerCellAction } from '../03_registry/lib/cellActions';
import { ORDERS_TEXTS } from './texts';

export const MODAL_ORDER_COMPOSER = 'order-composer';
export const MODAL_ORDER_CONFIRM = 'order-confirm';
export const MODAL_ORDER_DETAIL = 'order-detail';

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
  | { view: 'detail'; number: number };

const WINDOW_MODAL_ID = {
  composer: MODAL_ORDER_COMPOSER,
  confirm: MODAL_ORDER_CONFIRM,
  detail: MODAL_ORDER_DETAIL,
} as const;

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
}

const OrdersUiContext = createContext<OrdersUiContextValue | null>(null);

export function useOrdersUi(): OrdersUiContextValue {
  const ctx = useContext(OrdersUiContext);
  if (!ctx) {
    throw new Error('useOrdersUi must be used inside OrdersUiProvider');
  }
  return ctx;
}

export interface OrdersUiProviderProps {
  /** `activeModal` of the single ModalRoot in AppShell. */
  activeModal: string | null;
  /** `setActiveModal` of the single ModalRoot in AppShell. */
  onActiveModal: (id: string | null) => void;
  children: ReactNode;
}

export function OrdersUiProvider({
  activeModal,
  onActiveModal,
  children,
}: OrdersUiProviderProps) {
  const [orderWindow, setOrderWindow] = useState<OrdersWindow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // External close: ModalRoot.onClose (Esc/overlay) or another modal
  // taking over drops `activeModal` — the window state goes with it.
  useEffect(() => {
    if (
      orderWindow !== null &&
      activeModal !== WINDOW_MODAL_ID[orderWindow.view]
    ) {
      setOrderWindow(null);
    }
  }, [activeModal, orderWindow]);

  const openComposer = useCallback(() => {
    setOrderWindow({
      view: 'composer',
      requestId: crypto.randomUUID(),
      draft: EMPTY_DRAFT,
      error: null,
    });
    onActiveModal(MODAL_ORDER_COMPOSER);
  }, [onActiveModal]);

  const openOrder = useCallback(
    (number: number) => {
      if (!Number.isInteger(number) || number < 1) {
        return;
      }
      setOrderWindow({ view: 'detail', number });
      onActiveModal(MODAL_ORDER_DETAIL);
    },
    [onActiveModal],
  );

  // The Registry's `order:<number>` action — one registration for the
  // session; re-registering replaces (cellActions semantics).
  useEffect(() => {
    registerCellAction('order', (arg) => openOrder(Number(arg)));
  }, [openOrder]);

  const toConfirm = useCallback(
    (draft: OrderDraft) => {
      setOrderWindow((w) =>
        w?.view === 'composer'
          ? { view: 'confirm', requestId: w.requestId, draft }
          : w,
      );
      onActiveModal(MODAL_ORDER_CONFIRM);
    },
    [onActiveModal],
  );

  const backToComposer = useCallback(
    (error: ComposerServerError | null) => {
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
      onActiveModal(MODAL_ORDER_COMPOSER);
    },
    [onActiveModal],
  );

  const closeWindow = useCallback(() => {
    setOrderWindow(null);
    onActiveModal(null);
  }, [onActiveModal]);

  const notifySubmitted = useCallback(
    (number: number) => {
      setOrderWindow(null);
      onActiveModal(null);
      setNotice(ORDERS_TEXTS.submittedNotice(number));
    },
    [onActiveModal],
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
      }}
    >
      {children}
      {notice !== null && (
        <Snackbar onClose={() => setNotice(null)}>{notice}</Snackbar>
      )}
    </OrdersUiContext.Provider>
  );
}
