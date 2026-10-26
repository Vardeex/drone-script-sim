// Wspólna reguła: czy zdarzenie klawiatury trafiło do pola, w którym się pisze?
//
// Problem, który to rozwiązuje: globalne skróty (spacja = play/pauza, strzałki =
// przewijanie, klawisze lotu ręcznego) przechwytywały klawisze także wtedy, gdy
// kursor był w edytorze kodu - nie dało się wpisać spacji. `document.activeElement`
// to w CodeMirror 6 element `div[contenteditable]`, a nie textarea, więc samo
// sprawdzanie tagName nie wystarcza.
//
// Zasada: jeśli fokus jest w polu tekstowym/liczbowym, edytorze, `contenteditable`
// albo w otwartym oknie dialogowym - **skrót nie działa i nie wołamy
// `preventDefault`**, żeby klawisz zachował się normalnie w polu.

/** Elementy, w których klawisz należy do pola, a nie do aplikacji. */
const TYPING_SELECTOR = [
  'input', 'textarea', 'select',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '[contenteditable="plaintext-only"]',
  '.cm-editor',                       // edytor CodeMirror (także jego panel szukania)
  '[role="textbox"]',
  '[role="dialog"]',                  // otwarte okno dialogowe (dowolna treść)
  '[role="alertdialog"]',
  'dialog[open]',
].join(', ');

/**
 * Czy klawisz ma trafić do pola edycyjnego (a nie do skrótu aplikacji)?
 * @param {KeyboardEvent} event
 * @returns {boolean}
 */
export function isTypingTarget(event) {
  if (!event) return false;
  const target = event.target instanceof Element
    ? event.target
    : (document.activeElement instanceof Element ? document.activeElement : null);
  if (!target) return false;
  if (target.closest(TYPING_SELECTOR)) return true;
  // contenteditable ustawiony na przodku (dziedziczony) nie zawsze widać w closest()
  return Boolean(target.isContentEditable);
}
