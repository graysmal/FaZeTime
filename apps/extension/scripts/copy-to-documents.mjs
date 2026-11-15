// Copy the built unpacked extension to ~/Documents/fazetime-extension so Flatpak Chrome can load it.
// Overwrites files in place and never deletes anything.
import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const src = join(dirname(fileURLToPath(import.meta.url)), '..', '.output', 'chrome-mv3');
const dest = join(homedir(), 'Documents', 'fazetime-extension');
if (!existsSync(join(src, 'manifest.json'))) {
  console.error(`No build at ${src}. Run "npx wxt build" first.`);
  process.exit(1);
}
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true, force: true });
console.log(`Copied ${src} -> ${dest}`);
