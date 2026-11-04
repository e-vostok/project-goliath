/**
 * NationsSection — «Государства» (0.11.0 units 8b/8c): the view
 * switcher over three screens — the list (screen 03,
 * NationsList.tsx), the create page (screen 03c, NationCreate.tsx)
 * and the edit page (screen 03b, NationEdit.tsx) — plus the
 * screen-03d deletion popup (NationDeletePopup.tsx) that floats over
 * the list. Shared building blocks live in shared.tsx, the edit
 * form's pure diff model in nationEdit.ts. Bumping reloadKey after a
 * successful create, edit or delete refreshes the list.
 *
 * 0.13.0 unit 9b: the list view holds the «Государства | Анкеты»
 * switch (local state — never a hash); «Анкеты» is the review queue
 * of mockups 22/22b in ApplicationsList.tsx, its badge the
 * `applications_pending` item of GET /admin/attention.
 */

import { useState } from 'react';

import type { AdminNationDTO } from '../../../shared/types';
import { useNotice } from '../../../shared/ui/Notice';
import { useAdminSession } from '../../PanelFrame';
import { ApplicationsList } from './ApplicationsList';
import { NationCreate } from './NationCreate';
import { NationDeletePopup } from './NationDeletePopup';
import { NationEdit } from './NationEdit';
import { NationsList } from './NationsList';
import { NationsAppsSwitch } from './shared';

type View = 'list' | 'create' | { edit: AdminNationDTO };
type SectionTab = 'nations' | 'applications';

export function NationsSection() {
  const notify = useNotice();
  const { applicationsPending } = useAdminSession();
  const [view, setView] = useState<View>('list');
  const [tab, setTab] = useState<SectionTab>('nations');
  const [reloadKey, setReloadKey] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<AdminNationDTO | null>(null);

  const backToList = (changed: boolean) => {
    if (changed) {
      setReloadKey((key) => key + 1);
    }
    setView('list');
  };

  const deleted = (shortName: string) => {
    setDeleteTarget(null);
    setReloadKey((key) => key + 1);
    notify(`Государство «${shortName}» удалено.`);
  };

  if (view === 'create') {
    return <NationCreate onDone={backToList} />;
  }
  if (view !== 'list') {
    return <NationEdit nation={view.edit} onDone={backToList} />;
  }
  if (tab === 'applications') {
    return <ApplicationsList onBack={() => setTab('nations')} />;
  }
  return (
    <>
      <NationsList
        key={reloadKey}
        switcher={
          <NationsAppsSwitch
            active="nations"
            pendingCount={applicationsPending}
            onSelect={setTab}
          />
        }
        onCreate={() => setView('create')}
        onEdit={(nation) => setView({ edit: nation })}
        onDelete={setDeleteTarget}
      />
      {deleteTarget !== null && (
        <NationDeletePopup
          target={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={deleted}
        />
      )}
    </>
  );
}
