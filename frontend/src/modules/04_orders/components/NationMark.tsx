/**
 * NationMark — the author-nation snapshot: colour dot + name (INV-O6).
 * Shared by the order detail window and the «Мне на отсуд» rows.
 */
export function NationMark({ name, color }: { name: string; color: string }) {
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
