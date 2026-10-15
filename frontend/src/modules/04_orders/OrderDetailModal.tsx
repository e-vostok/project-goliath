/**
 * OrderDetailModal — the «Приказ №N» window (Spec 5.4).
 *
 * Nation colour mark and name next to the number; blocks: title,
 * «Краткая суть приказа», link «Статья приказа»; the verdict block
 * when a verdict exists; «Срок вердикта вышел» when overdue; the
 * «Написать вердикт» button only when `can_write_verdict` (wired in
 * Issue 8 — a no-op for now). The judge is never shown (INV-O5).
 * A 404 renders «Приказ не найден».
 */

import {
  Button,
  Div,
  FormStatus,
  Link,
  ModalPage,
  ModalPageHeader,
  Spinner,
  Text,
  type NavIdProps,
} from '@vkontakte/vkui';

import { useOrderDetail } from './hooks/useOrderDetail';
import { ORDERS_TEXTS } from './texts';
import type { OrderDetailDTO } from './types';
import { useOrdersUi } from './OrdersUiProvider';

/** Fits inside the 910 px window budget like every other window. */
const MODAL_SIZE = 'min(880px, calc(100vw - 64px))';

/** The author-nation snapshot: colour dot + name (INV-O6). */
function NationMark({ name, color }: { name: string; color: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 10,
          height: 10,
          borderRadius: '50%',
          flexShrink: 0,
          background: color,
        }}
      />
      <span>{name}</span>
    </span>
  );
}

export function OrderDetailModal({ id, ...navIdProps }: NavIdProps) {
  const { orderWindow, closeWindow } = useOrdersUi();
  const number = orderWindow?.view === 'detail' ? orderWindow.number : null;
  const detail = useOrderDetail(number);
  const order = detail.status === 'ready' ? detail.order : null;

  return (
    <ModalPage
      id={id}
      {...navIdProps}
      onClose={closeWindow}
      size={MODAL_SIZE}
      header={
        <ModalPageHeader>
          <span
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            {number !== null ? ORDERS_TEXTS.detailTitle(number) : ''}
            {order !== null && (
              <NationMark
                name={order.nation.name}
                color={order.nation.color}
              />
            )}
          </span>
        </ModalPageHeader>
      }
    >
      {number === null ? null : detail.status === 'loading' ? (
        <Div
          style={{
            display: 'flex',
            justifyContent: 'center',
            padding: '48px 0',
          }}
        >
          <Spinner size="l" />
        </Div>
      ) : detail.status === 'error' ? (
        <Div>
          <FormStatus
            mode="error"
            title={
              detail.notFound
                ? ORDERS_TEXTS.notFound
                : ORDERS_TEXTS.detailLoadError
            }
          >
            {detail.notFound ? undefined : detail.error.message}
          </FormStatus>
          {!detail.notFound && (
            <Button size="s" onClick={detail.reload}>
              {ORDERS_TEXTS.retry}
            </Button>
          )}
        </Div>
      ) : (
        order !== null && <OrderDetailBody order={order} />
      )}
    </ModalPage>
  );
}

function ArticleLink({ url, label }: { url: string; label: string }) {
  // Same defense in depth as the nation history link: a stored value
  // that is not https:// renders as plain text, never as a link.
  if (!url.startsWith('https://')) {
    return <Text>{url}</Text>;
  }
  return (
    <Link href={url} target="_blank" rel="noopener noreferrer">
      {label}
    </Link>
  );
}

function OrderDetailBody({ order }: { order: OrderDetailDTO }) {
  return (
    <Div>
      {order.overdue && (
        <Text
          weight="2"
          data-testid="order-overdue-mark"
          style={{
            display: 'block',
            color: 'var(--vkui--color_text_negative)',
            marginBottom: 8,
          }}
        >
          {ORDERS_TEXTS.overdueMark}
        </Text>
      )}

      <Text weight="2">{order.title}</Text>

      <Text weight="2" style={{ display: 'block', marginTop: 16 }}>
        {ORDERS_TEXTS.summaryBlockTitle}
      </Text>
      <Text style={{ whiteSpace: 'pre-wrap', overflowWrap: 'break-word' }}>
        {order.summary}
      </Text>

      <div style={{ marginTop: 8 }}>
        <ArticleLink url={order.article_url} label={ORDERS_TEXTS.articleLink} />
      </div>

      {order.verdict !== null && (
        <>
          <Text weight="2" style={{ display: 'block', marginTop: 24 }}>
            {ORDERS_TEXTS.verdictBlockTitle}
          </Text>
          <Text weight="2">{order.verdict.title}</Text>
          <Text
            weight="2"
            style={{ display: 'block', marginTop: 8 }}
          >
            {ORDERS_TEXTS.verdictSummaryTitle}
          </Text>
          <Text
            style={{ whiteSpace: 'pre-wrap', overflowWrap: 'break-word' }}
          >
            {order.verdict.summary}
          </Text>
          <div style={{ marginTop: 8 }}>
            <ArticleLink
              url={order.verdict.article_url}
              label={ORDERS_TEXTS.verdictArticleLink}
            />
          </div>
        </>
      )}

      {order.can_write_verdict && (
        <div style={{ marginTop: 24 }}>
          {/* Wired to the verdict composer in Issue 8 — a no-op for now. */}
          <Button size="l" stretched mode="primary" onClick={() => {}}>
            {ORDERS_TEXTS.writeVerdict}
          </Button>
        </div>
      )}
    </Div>
  );
}
