# Bundle CodeMirror 6 (edytor skryptów)

`app/static/vendor/codemirror/codemirror.bundle.js` jest **zbudowanym** plikiem
(402 kB, minified ESM) - aplikacja importuje go bezpośrednio, bez CDN i bez
`node_modules` w paczce dla użytkownika. Tutaj leży przepis, jak go odtworzyć.

## Jak przebudować

Wymagania: Node.js 18+ i npm (tylko do budowania, nie do uruchamiania).

```bash
cd release_tools/codemirror
npm install
npm run build                                    # -> ../../app/static/vendor/codemirror/codemirror.bundle.js
python collect_licenses.py . ../../app/static/vendor/codemirror/LICENSE
```

`collect_licenses.py` zbiera teksty licencji MIT wszystkich pakietów wchodzących
do bundla - **plik LICENSE musi być dostarczany razem z bundlem**.

## Co jest w środku

| Moduł | Do czego |
|---|---|
| `@codemirror/view`, `@codemirror/state` | rdzeń edytora, numery linii, podświetlenie linii |
| `@codemirror/lang-python` + `@lezer/highlight` | kolorowanie składni Pythona (własny motyw) |
| `@codemirror/autocomplete` | podpowiedzi (dane z `GET /api/completions`) |
| `@codemirror/commands` | historia, wcięcia, Tab |

## Wejście

`entry.js` eksportuje `createEditor({parent, doc, onChange, completions})` oraz
metody `getValue`, `setValue`, `markWarningLines`, `setPlaybackLine`,
`setCompletions`. Integrację z aplikacją (ukryta textarea, analiza `ast`,
podpowiedzi) opisuje `app/static/js/editor.js`.

## Licencja

Wszystkie pakiety: MIT (CodeMirror - Marijn Haverbeke i współtwórcy, Lezer).
Pełne teksty: `app/static/vendor/codemirror/LICENSE`.
