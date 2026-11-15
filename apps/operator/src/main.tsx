import './polyfills'; // must stay first: crypto.randomUUID fallback for the plain-http tailnet origin
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
import { applyStoredTheme } from './ui/theme';

applyStoredTheme();

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
