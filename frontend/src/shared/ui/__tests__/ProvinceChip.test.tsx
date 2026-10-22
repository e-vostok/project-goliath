/**
 * ProvinceChip — every chip is the same 24 px inline-flex line, star
 * or no star, short name or long (acceptance 12b: chips stopped
 * "jumping" inside their boxes). The «★» is its own fixed-width
 * element so the glyph cannot raise the line box.
 */

import { render } from '@testing-library/react';

import { ProvinceChip } from '../ProvinceChip';

describe('ProvinceChip', () => {
  it('keeps one box for every chip: height 24, line-height 16, aligned center', () => {
    render(
      <>
        <ProvinceChip name="Вестерос" />
        <ProvinceChip name="Альфа" capital capitalName="Столицево" />
        <ProvinceChip
          name="Нижние Предгорья"
          capital
          capitalName="Старосветская Столица-Прибрежная"
        />
      </>,
    );

    const chips = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[data-testid="province-chip"]',
      ),
    );
    expect(chips).toHaveLength(3);
    for (const chip of chips) {
      expect(chip.style.display).toBe('inline-flex');
      expect(chip.style.alignItems).toBe('center');
      expect(chip.style.height).toBe('24px');
      expect(chip.style.lineHeight).toBe('16px');
      expect(chip.style.boxSizing).toBe('border-box');
    }

    // The capital star lives in its own 14 px inline-flex element —
    // the text keeps «★ Столица (Провинция)» readable as one string.
    const star = chips[1].querySelector('span') as HTMLElement;
    expect(star.style.width).toBe('14px');
    expect(star.style.lineHeight).toBe('16px');
    expect(chips[1].textContent).toBe('★ Столицево (Альфа)');
    expect(chips[0].textContent).toBe('Вестерос');
  });
});
