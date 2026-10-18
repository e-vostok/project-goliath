/**
 * Player-facing Russian labels for the fixed code sets of nation data
 * (Spec 1.3: `gender` and `succession_type` value sets are fixed in
 * code, not in the balance config). `GET /nations/rules` still decides
 * the order and the presence of each code — the maps below only name
 * them. Issue 16 reuses the same dictionaries on the nation card and
 * in the edit form.
 */

/** Gender code → button label (iterated over `rules.genders`). */
export const GENDER_LABELS: Record<string, string> = {
  male: 'Мужской',
  female: 'Женский',
};

export interface SuccessionLabel {
  title: string;
  description: string;
}

/** Succession code → card texts (iterated over `rules.succession_types`). */
export const SUCCESSION_LABELS: Record<string, SuccessionLabel> = {
  elections: {
    title: 'Демократические выборы',
    description: 'Лидера выбирают граждане',
  },
  appointment: {
    title: 'Назначение игроком',
    description: 'Преемника назначаете вы',
  },
  criteria: {
    title: 'Назначение по критериям',
    description: 'Лидер определяется по заданным условиям',
  },
  inheritance: {
    title: 'Наследование',
    description: 'Власть переходит по наследству',
  },
};
