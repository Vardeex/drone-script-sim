// Loader dla Node: mapuje "three" na plik z app/static/vendor (jak importmap w UI).
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';

const VENDOR = pathToFileURL(
  new URL('../app/static/vendor/three.module.js', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'),
).href;

export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'three') {
    return { url: VENDOR, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}

if (process.env.OBSTACLES_REGISTER_HOOKS === '1') {
  register(import.meta.url);
}
