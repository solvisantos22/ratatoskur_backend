'use client';

import { useState, type SubmitEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { api } from '@/lib/api';
import type { Assignment } from '@/lib/classroom';

export function AssignmentPolicy({
  assignment,
  onSaved,
}: {
  assignment: Assignment;
  onSaved: () => void;
}) {
  const [allowReveal, setAllowReveal] = useState(assignment.allow_reveal);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const changed = allowReveal !== assignment.allow_reveal;

  async function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !changed) return;
    setBusy(true);
    setError('');
    try {
      await api<Assignment>(`/teacher/assignments/${assignment.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ allow_reveal: allowReveal }),
      });
      onSaved();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface">
      <h2>Aðstoð í verkefnasettinu</h2>
      <p className="quiet">
        {assignment.allow_reveal
          ? 'Núverandi stilling: fullar lausnir eru leyfðar.'
          : 'Núverandi stilling: aðeins vísbendingar og yfirferð.'}
      </p>
      <form onSubmit={save} className="form-stack">
        <div className="policy-choice">
          <Label htmlFor="assignment-allow-reveal">Leyfa fullar lausnir</Label>
          <Switch
            id="assignment-allow-reveal"
            checked={allowReveal}
            onCheckedChange={setAllowReveal}
            disabled={busy}
            aria-describedby="assignment-policy-explanation"
          />
        </div>
        <p id="assignment-policy-explanation" className="quiet">
          Vísbendingar og yfirferð eru áfram í boði. Breytingin gildir fyrir nýjar
          beiðnir; fyrri svör haldast sýnileg.
        </p>
        {error && <p role="alert" className="error-message">{error}</p>}
        <div className="policy-save">
          <Button type="submit" disabled={busy || !changed}>
            {busy ? 'Vista…' : 'Vista stillingu'}
          </Button>
          {changed && <output className="quiet">Óvistaðar breytingar</output>}
        </div>
      </form>
    </section>
  );
}
