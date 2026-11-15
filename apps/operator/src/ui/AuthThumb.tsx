import { useEffect, useState, type ReactNode } from 'react';
import type { OperatorClient } from '../api/client';

/**
 * One evidence JPEG, fetched with the bearer header (an <img src> cannot send it, and a token never goes in a
 * URL). Shown through a blob: URL that is revoked on unmount or when the id changes.
 */
export function AuthThumb({
  client,
  evidenceId,
  pruned = false,
  alt,
  caption,
  testId = 'evidence-frame',
}: {
  client: OperatorClient;
  evidenceId: string;
  pruned?: boolean;
  alt: string;
  caption?: ReactNode;
  testId?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (pruned) return undefined;
    const ctrl = new AbortController();
    let url: string | null = null;
    setSrc(null);
    setFailed(false);
    client
      .evidenceImage(evidenceId, ctrl.signal)
      .then((blob) => {
        if (ctrl.signal.aborted) return;
        url = URL.createObjectURL(blob.type === 'image/jpeg' ? blob : new Blob([blob], { type: 'image/jpeg' }));
        setSrc(url);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setFailed(true);
      });
    return () => {
      ctrl.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [client, evidenceId, pruned]);

  return (
    <figure className="thumb" data-testid={testId}>
      {src ? (
        <img src={src} alt={alt} width={160} height={90} />
      ) : (
        <div className="thumb-empty">{pruned ? 'pruned' : failed ? 'unavailable' : 'loading…'}</div>
      )}
      {caption && <figcaption className="small">{caption}</figcaption>}
    </figure>
  );
}
