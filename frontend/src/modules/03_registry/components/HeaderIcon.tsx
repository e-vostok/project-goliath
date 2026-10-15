/**
 * HeaderIcon — a column's `header_icon` (Spec 1.2): a small inline SVG
 * shown instead of the title text; the `title` stays the tooltip and
 * the accessible label. The three stage icons belong to the orders
 * table («Подача» / «Распределение» / «Вердикт»); an unknown name falls
 * back to the plain title text.
 */

const ICON_STYLE: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  flexShrink: 0,
  color: 'var(--vkui--color_text_secondary)',
};

const SVG_PROPS = {
  width: 16,
  height: 16,
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.4,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const;

const STAGE_ICONS: Record<string, React.ReactElement> = {
  // Submitted: a downward arrow into a tray.
  stage_submitted: (
    <>
      <path d="M8 2.5v5" />
      <path d="M5.4 5.2 8 7.8l2.6-2.6" />
      <path d="M2.6 9.5v2.9a1.7 1.7 0 0 0 1.7 1.7h7.4a1.7 1.7 0 0 0 1.7-1.7V9.5" />
    </>
  ),
  // Distributed: a judge — head circle over shoulders.
  stage_distributed: (
    <>
      <circle cx="8" cy="5.1" r="2.6" />
      <path d="M3 13.7c.7-2.5 2.7-3.8 5-3.8s4.3 1.3 5 3.8" />
    </>
  ),
  // Verdict: a check mark inside a circle.
  stage_verdict: (
    <>
      <circle cx="8" cy="8" r="5.6" />
      <path d="M5.4 8.3 7.2 10l3.4-3.7" />
    </>
  ),
};

export function HeaderIcon({
  name,
  title,
}: {
  name: string;
  title: string;
}) {
  const icon = STAGE_ICONS[name];
  if (!icon) {
    return <>{title}</>;
  }
  return (
    <span
      role="img"
      aria-label={title}
      title={title}
      data-testid={`header-icon-${name}`}
      style={ICON_STYLE}
    >
      <svg {...SVG_PROPS}>{icon}</svg>
    </span>
  );
}
