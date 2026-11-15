import { useState } from 'react';
import type { OperatorClient } from '../api/client';
import type { InviteReceipt } from '../api/types';
import { MutationStatus, Panel } from './common';
import { formatUtcDayTime, shortId } from './format';
import { useMutation } from './hooks';

interface ShownCode {
  inviteId: string;
  code: string;
  expiresAtUtc: string;
}

/**
 * Viewer invite codes are returned by the server exactly once. They live only in this component's memory
 * (never storage, never logs) until the operator hides them or leaves the page.
 */
export function InvitePanel({ client }: { client: OperatorClient }) {
  const [codes, setCodes] = useState<ShownCode[]>([]);
  const [copied, setCopied] = useState<string | null>(null);
  const [replayNote, setReplayNote] = useState(false);
  const create = useMutation<InviteReceipt>((r) => {
    const code = r.receipt.invite_code;
    if (code) {
      setReplayNote(false);
      setCodes((list) => [{ inviteId: r.receipt.invite.invite_id, code, expiresAtUtc: r.receipt.invite.expires_at_utc }, ...list]);
    } else {
      setReplayNote(true);
    }
  });

  async function copy(item: ShownCode) {
    try {
      await navigator.clipboard.writeText(item.code);
      setCopied(item.inviteId);
    } catch {
      setCopied(null);
      window.getSelection()?.selectAllChildren(document.getElementById(`code-${item.inviteId}`) ?? document.body);
    }
  }

  return (
    <Panel title="Viewer invites">
      <p className="muted small">
        One code per teammate. They enter it in the extension to enroll a VIEWER account (seeded with demo funds).
      </p>
      <button type="button" className="btn primary" disabled={create.state.status === 'busy'} onClick={() => void create.run(() => client.createViewerInvite())}>
        Create viewer invite
      </button>
      <MutationStatus
        state={create.state}
        client={client}
        run={create.run}
        describe={(r) => (
          <div>
            Invite <code>{shortId(r.receipt.invite.invite_id)}</code> ({r.receipt.invite.role}) issued
            {r.receipt.invite_code ? '; code shown below' : '; code not returned (replay)'}.
          </div>
        )}
      />
      {replayNote && (
        <div className="notice unknown">
          The server replayed an earlier invite operation. Its code was shown only once and cannot be shown again. Create a
          new invite instead.
        </div>
      )}
      <ul className="codes">
        {codes.map((item) => (
          <li key={item.inviteId} className="code-card" data-testid="invite-code">
            <span className="invite" id={`code-${item.inviteId}`}>
              {item.code}
            </span>
            <div className="actions">
              <button type="button" className="btn small" onClick={() => void copy(item)}>
                {copied === item.inviteId ? 'Copied' : 'Copy'}
              </button>
              <button type="button" className="btn small" onClick={() => setCodes((l) => l.filter((c) => c.inviteId !== item.inviteId))}>
                Hide
              </button>
            </div>
            <div className="muted small">
              Single use · valid 24 h (expires {formatUtcDayTime(item.expiresAtUtc)}) · shown once, not stored by the server or
              this page · {shortId(item.inviteId)}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
