/**
 * GaugeCell — `gauge` column: signed number plus a bar with zero in
 * the centre; negative side to the left (striped), positive to the
 * right (solid) — distinguishable by shape, not by colour alone
 * (Spec 5.5 / Bible 3).
 */

import type { RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

export function GaugeCell({
  value,
  scaleMin,
  scaleMax,
}: {
  value: RegistryCell;
  scaleMin: number | null;
  scaleMax: number | null;
}) {
  const min = scaleMin ?? -100;
  const max = scaleMax ?? 100;
  const num = typeof value === 'number' ? value : null;

  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  const toPct = (v: number) => ((clamp(v) - min) / (max - min)) * 100;
  const zeroPct = toPct(0);
  const valPct = num === null ? zeroPct : toPct(num);
  const left = Math.min(zeroPct, valPct);
  const width = Math.abs(valPct - zeroPct);
  const negative = num !== null && num < 0;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span
        style={{
          width: 36,
          textAlign: 'right',
          flexShrink: 0,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {num === null
          ? REGISTRY_TEXTS.emptyValue
          : num > 0
            ? `+${num}`
            : `${num}`}
      </span>
      <div
        style={{
          position: 'relative',
          flex: 1,
          minWidth: 0,
          height: 8,
          background: 'var(--vkui--color_background_secondary)',
          borderRadius: 4,
        }}
      >
        {/* zero marker */}
        <div
          style={{
            position: 'absolute',
            left: `${zeroPct}%`,
            top: -2,
            bottom: -2,
            width: 1,
            background: 'var(--vkui--color_separator_primary)',
          }}
        />
        {num !== null && num !== 0 && (
          <div
            data-testid="gauge-fill"
            data-negative={negative}
            style={{
              position: 'absolute',
              left: `${left}%`,
              width: `${width}%`,
              top: 0,
              bottom: 0,
              borderRadius: 4,
              // negative = striped fill; positive = solid fill
              background: negative
                ? 'repeating-linear-gradient(45deg, var(--vkui--color_icon_negative) 0 3px, transparent 3px 6px)'
                : 'var(--vkui--color_icon_positive)',
            }}
          />
        )}
      </div>
    </div>
  );
}
