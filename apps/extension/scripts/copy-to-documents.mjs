// Copy the built unpacked extension to ~/Documents/fazetime-extension so Flatpak Chrome can load it.
// Overwrites files in place and never deletes anything.
import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Usage: node scripts/copy-to-documents.mjs [outputDir=chrome-mv3] [documentsFolder=fazetime-extension]
const [variant = 'chrome-mv3', folder = 'fazetime-extension'] = process.argv.slice(2);
if (!/^[a-z0-9_-]+$/i.test(variant) || !/^[a-z0-9_-]+$/i.test(folder)) throw new Error('bad arguments');
const src = join(dirname(fileURLToPath(import.meta.url)), '..', '.output', variant);
const dest = join(homedir(), 'Documents', folder);
if (!existsSync(join(src, 'manifest.json'))) {
  console.error(`No build at ${src}. Run "npx wxt build" first.`);
  process.exit(1);
}
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true, force: true });
console.log(`Copied ${src} -> ${dest}`);
