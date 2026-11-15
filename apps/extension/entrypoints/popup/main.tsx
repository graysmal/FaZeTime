// Profile popup (P1-B): display name plus an optional claimed Twitch login, stored in extension
// storage. The login is a label, NOT verified identity. No phone field (D16), no card fields, ever.
import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CLAIMED_TWITCH_LOGIN_PATTERN } from '@fazetime/contracts';
import { wxtKV } from '../../src/storage';
import { PROFILE_KEY, type Profile } from '../../src/ui/hooks';
import './style.css';

export function validateProfile(displayName: string, login: string): string | null {
  const name = displayName.trim();
  if ([...name].length < 1 || [...name].length > 32) return 'Display name must be 1 to 32 characters.';
  if (login.trim() !== '' && !CLAIMED_TWITCH_LOGIN_PATTERN.test(login.trim()))
    return 'Twitch login may only use letters, numbers and underscores (up to 25).';
  return null;
}

function App() {
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    void wxtKV.get<Profile>(PROFILE_KEY).then((p) => {
      if (p) {
        setName(p.display_name);
        setLogin(p.claimed_twitch_login ?? '');
      }
    });
  }, []);
  const error = validateProfile(name, login);
  const save = async () => {
    if (error) return;
    const profile: Profile = { display_name: name.trim(), claimed_twitch_login: login.trim() || null };
    await wxtKV.set(PROFILE_KEY, profile);
    setStatus('Saved on this browser.');
  };
  return (
    <main>
      <header>
        <h1>
          FaZe<b>Time</b>
        </h1>
        <span className="mock">MOCK</span>
      </header>
      <p className="fine">Demo build with local mock data only. No account, no backend, no real money.</p>
      <label>
        Display name
        <input value={name} maxLength={64} onChange={(e) => (setName(e.target.value), setStatus(null))} placeholder="PixelPilot" />
      </label>
      <label>
        Twitch login (optional)
        <input value={login} maxLength={25} onChange={(e) => (setLogin(e.target.value), setStatus(null))} placeholder="your_twitch_name" />
        <span className="fine">Not verified. It is only a label and does not log you in.</span>
      </label>
      {error && name !== '' && <p className="err">{error}</p>}
      <button type="button" disabled={error !== null} onClick={() => void save()}>
        Save profile
      </button>
      {status && <p className="ok">{status}</p>}
    </main>
  );
}

const rootEl = document.getElementById('root');
if (rootEl)
  createRoot(rootEl).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
