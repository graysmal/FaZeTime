import type { Capabilities } from '../api/capabilities';
import { Panel } from './common';

/** Placeholder only. The P4 proposal contract is reserved (CONTRACTS §9.16 item 7) and not frozen yet. */
export function AiPanel({ aiMode, caps }: { aiMode: string | null; caps: Capabilities | null }) {
  return (
    <Panel title="AI candidates (P4)" tag={<span className="tag warn">PLACEHOLDER · NOT ACTIVE</span>} className="ai">
      <p>
        No AI proposals are generated, shown or approved in this build. The proposal and resolution contract will be frozen
        at the start of P4.
      </p>
      <ul className="small">
        <li>
          Current AI mode: <span className="badge">{aiMode ?? 'unknown'}</span>
        </li>
        <li>
          Set-AI-mode route:{' '}
          {caps ? caps.aiModeRoute ? <code>{caps.aiModeRoute}</code> : 'none in this API yet' : 'checking…'}
        </li>
        <li>
          Candidate routes:{' '}
          {caps ? (caps.candidateRoutes.length ? caps.candidateRoutes.join(', ') : 'none in this API yet') : 'checking…'}
        </li>
      </ul>
      <p className="muted small">
        In APPROVAL mode (supervised AI) this panel will list each candidate with its cited evidence, criteria and deadlines,
        plus Approve / Reject with a reason. Uncertain results abstain; nothing here can settle a market automatically.
      </p>
    </Panel>
  );
}
