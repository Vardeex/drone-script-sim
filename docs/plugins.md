# Pisanie wtyczek

Wtyczka rozszerza aplikację o własne API, panel w interfejsie, warstwę 3D
albo analizę lotu - **bez zmieniania kodu rdzenia**. Rdzeń nie zna nazw
wtyczek: odkrywa je przy starcie, waliduje i montuje.

## Spis treści

1. [Szybki start](#szybki-start)
2. [Struktura katalogu](#struktura-katalogu)
3. [Manifest `plugin.json`](#manifest-pluginjson)
4. [Ładowanie i zależności](#ładowanie-i-zależności)
5. [Punkty rozszerzeń](#punkty-rozszerzeń)
6. [Debugowanie](#debugowanie)
7. [Wtyczki wbudowane a zewnętrzne](#wtyczki-wbudowane-a-zewnętrzne)

## Szybki start

Skopiuj wzór i zmień identyfikator:

```bat
cd D:\DroneSim
xcopy /E /I plugins\example_hello plugins\moja_wtyczka
```

1. W `plugins/moja_wtyczka/plugin.json` ustaw `"id": "moja_wtyczka"`
   (**musi** być takie samo jak nazwa katalogu), własną `name`, `version`, `description`.
2. Zmień endpointy w `src/router.py` i treść panelu w `static/panel.js`.
3. Zrestartuj serwer (`start.bat`). Zakładka pojawi się w panelu po prawej,
   a wtyczka będzie widoczna w zakładce **Wtyczki**.

Katalog `plugins/` jest w `.gitignore` poza wzorem `example_hello/`, więc
Twoja wtyczka zostaje lokalnie.

## Struktura katalogu

```
plugins/moja_wtyczka/
  plugin.json           # manifest (wymagany)
  src/
    __init__.py         # pakiet Pythona wtyczki (opcjonalny)
    router.py           # APIRouter - endpointy REST (opcjonalny)
    hooks.py            # hooki rdzenia, np. analiza lotu (opcjonalny)
  static/
    panel.js            # panel UI (opcjonalny)
    scene_layer.js      # warstwa 3D (opcjonalna)
    panel.css           # style (opcjonalne)
  README.md             # opis dla człowieka (opcjonalny)
```

Bez `src/` wtyczka może być „sama statyczna” (np. tylko styl). Kod Pythona
jest importowany jako `app.plugins_ext.<id>`.

## Manifest `plugin.json`

| Pole | Wymagane | Znaczenie |
|---|---|---|
| `id` | tak | identyfikator: małe litery, cyfry, `_`, 2-48 znaków; **równy nazwie katalogu** |
| `name` | tak | nazwa widoczna w UI |
| `version` | tak | wersja wtyczki (np. `"1.0.0"`) |
| `description` | tak | jednozdaniowy opis |
| `author` | nie | autor |
| `requires_app` | nie | minimalna wersja aplikacji, np. `">=1.0.0"` (obsługiwane `>=`, `>`, `<=`, `<`, `==`, `!=`, łączone przecinkiem) |
| `requires` | nie | lista id wtyczek, które muszą działać (np. `["obstacles"]`) |
| `extension_points` | nie | z których punktów rozszerzeń korzysta (walidowane) |
| `api_prefix` | nie | prefiks API, domyślnie `/api/<id>` |
| `static` | nie | katalog plików statycznych (serwowany pod `/static/features/<id>`) |
| `ui.panel` | nie | moduł panelu (eksportuje `registerPanel`) |
| `ui.scene_layer` | nie | moduł warstwy 3D (eksportuje `createLayer`) |
| `ui.styles` | nie | lista arkuszy CSS doładowywanych przy starcie |
| `ui.tab` | nie | id sekcji zakładki, domyślnie `tab-<id>` |
| `ui.tab_button` | nie | id przycisku zakładki, domyślnie `tab-btn-<id>` |

Przykład (`plugins/example_hello/plugin.json`):

```json
{
  "id": "example_hello",
  "name": "Przykładowa wtyczka: Hello",
  "version": "1.0.0",
  "description": "Panel z tekstem i endpoint API",
  "author": "Vardeex",
  "requires_app": ">=1.0.0",
  "requires": [],
  "extension_points": ["api", "ui.panel", "ui.styles"],
  "api_prefix": "/api/example_hello",
  "static": "static",
  "ui": {
    "panel": "static/panel.js",
    "styles": ["static/panel.css"],
    "tab": "tab-example_hello",
    "tab_button": "tab-btn-example_hello"
  }
}
```

## Ładowanie i zależności

Przy starcie serwera (`app/server.py` → `registry.load_all`):

1. **Odkrywanie** - skanowane są `app/features/*/` (wbudowane) i
   `plugins/*/` (zewnętrzne). Katalog bez `plugin.json` jest pomijany
   (w `plugins/` zostaje ostrzeżenie w logu).
2. **Walidacja** - sprawdzane są pola manifestu. Błędny manifest → wtyczka
   w stanie **błąd** z komunikatem (np. `pole 'name' jest wymagane`).
3. **Zależności** - wtyczki sortowane tak, by `requires` były wcześniej.
   Brakująca zależność albo cykl → stan **błąd**. Zależność wyłączona
   (ale poprawna) nie blokuje startu zależnej wtyczki - ta sama sprawdza,
   czy działa jej zależność (`registry.resolve_state("<id>")`).
4. **Wersja aplikacji** - `requires_app` porównywane z `app.__version__`.
5. **Montowanie** - statyki pod `/static/features/<id>`, router pod
   `api_prefix`, hooki przez `hooks.register(storage)`.

**Błąd jednej wtyczki nie wywraca aplikacji.** Wyjątek w imporcie, błąd
składni w `router.py`, wyjątek w `register()` - wszystko kończy się stanem
`error` z komunikatem w logu i w zakładce **Wtyczki**. Pozostałe wtyczki
i cała aplikacja działają.

Stan `enabled` w `plugin.json` jest domyślny; **`config.json` ma
pierwszeństwo**:

```json
{
  "features": {
    "obstacles": { "enabled": true },
    "route_planner": { "enabled": false },
    "example_hello": { "enabled": false }
  }
}
```

Przełącznik w zakładce **Wtyczki** zapisuje dokładnie to (endpoint
`POST /api/plugins/<id>/enabled`). **Zmiana działa po restarcie serwera** -
montowanie routerów i statyków wymaga nowego procesu.

API diagnostyczne:

| Endpoint | Zwraca |
|---|---|
| `GET /api/plugins` | wszystkie wtyczki (także wyłączone i z błędem): `id`, `name`, `version`, `author`, `state`, `error`, `requires`, `extension_points`, `source`, `ui` |
| `POST /api/plugins/<id>/enabled` | `{"enabled": true/false}` → zapis w `config.json`, odpowiedź z `restart_required: true` |
| `GET /api/features` | tylko włączone i zamontowane wtyczki (kontrakt UI) |

## Punkty rozszerzeń

Wtyczka deklaruje w manifeście (`extension_points`), z których korzysta.
Nieznana nazwa punktu = błąd manifestu (literówka nie przejdzie niezauważona).

### `api` - własne endpointy REST

Plik `src/router.py` z obiektem `router` (FastAPI `APIRouter`). Ścieżki
piszemy **bez prefiksu** - montuje go rdzeń pod `api_prefix`.

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
def hello(name: str = "pilocie") -> dict:
    return {"message": f"Cześć, {name}!"}
```

Efekt: `GET /api/<id>/hello`. Gdy wtyczka jest wyłączona, endpoint zwraca `404`.

### `ui.panel` - panel w zakładce

Plik `static/panel.js` (moduł ES) eksportujący `registerPanel`:

```js
export function registerPanel({ panels, feature, scene, player, timeline }) {
  panels.register({
    mount(section) {                       // wypełnia treść zakładki
      section.innerHTML = '<p>Mój panel</p>';
    },
    getRunOptions() {                      // opcjonalnie: opcje uruchomienia
      return { moja_wtyczka: { tryb: 'szybki' } };
    },
    onLoad(payload) { /* opcjonalnie: wczytany lot */ },
  });
}
```

Rdzeń **sam tworzy** zakładkę i przycisk (wtyczka zewnętrzna nie musi nic
dopisywać w `index.html`). Przycisk pojawia się tylko wtedy, gdy panel
wczytał się bez błędu.

### `ui.styles` - style

Lista ścieżek w `ui.styles` (np. `["static/panel.css"]`). Serwowane pod
`/static/features/<id>/panel.css` - w CSS piszemy więc **ścieżki absolutne**
(`background: url(/static/features/moja_wtyczka/tlo.png)`).

### `ui.scene_layer` - warstwa 3D

Plik eksportujący `createLayer(context)`:

```js
export function createLayer({ scene }) {
  const group = new THREE.Group();          // three.js jest w scenie
  return {
    setRoute(route) { /* rysowanie trasy */ },
    tick(t) { /* animacja w czasie odtwarzania */ },
    dispose() { /* sprzątanie */ },
  };
}
```

Kontrakt warstwy (jak w `route_planner/scene_layer.js`): `setRoute`,
`setSelection`, `setPreview`, `setPlaceMode`, `setDragMode`, `tick`, `dispose`.
Warstwa jest dodawana przez `scene.addOverlayLayer(instance)`.

### `flight.analyse` - analiza lotu

Plik `src/hooks.py` z funkcją `register(storage)` wołaną przy starcie:

```python
def on_flight_saved(payload, options=None):
    """Dopisz wynik analizy do zapisu lotu (payload['moja_wtyczka'])."""
    payload["moja_wtyczka"] = {"uwagi": "tu wynik analizy"}
    return payload


def register(storage):
    storage.register_post_save_hook(on_flight_saved)
```

Hook dostaje zapis lotu (telemetria, zdarzenia) i opcje uruchomienia.
Wyjątek w hooku **nie psuje zapisu lotu** - opakuj analizę w `try/except`,
tak jak `app/features/obstacles/hooks.py`.

### `run.options` - własne opcje uruchomienia

Panel zwraca `getRunOptions()`; klucz wtyczki trafia do `POST /api/run`
(pole `options`) i dalej do hooków `flight.analyse`:

```js
getRunOptions: () => ({ moja_wtyczka: { tryb: 'szybki' } })
```

```python
def on_flight_saved(payload, options=None):
    opts = (options or {}).get("moja_wtyczka") or {}
```


## Debugowanie

* **Zakładka Wtyczki** w UI: stan (włączona / wyłączona / błąd z komunikatem),
  wersja, autor, zależności, punkty rozszerzeń.
* **Log serwera** (okno `start.bat`): linie `[plugins] ...` - błędy manifestu,
  cykle, wyjątki przy wczytaniu.
* `GET /api/plugins` - pełny stan maszynowo.
* W przeglądarce: `window.__featureErrors` (błędy panelu i warstwy 3D),
  konsola deweloperska (F12).

Typowe problemy:

| Objaw | Przyczyna |
|---|---|
| wtyczki nie ma na liście | katalog poza `plugins/`, brak `plugin.json`, `id` ≠ nazwa katalogu |
| stan „błąd: pole 'id' jest wymagane” | brak pola w manifeście albo pole nie jest tekstem |
| stan „błąd: ModuleNotFoundError” | literówka w imporcie w `src/*.py` |
| stan „błąd: SyntaxError” | błąd składni w `router.py`/`hooks.py` |
| panel się nie pojawia | `ui.panel` nie wskazuje pliku albo brak `registerPanel` |
| 404 na endpoint | wtyczka wyłączona albo `router` nie ma takiej ścieżki |
| zmiana przełącznika nic nie robi | trzeba **zrestartować serwer** (tak działa celowo) |

## Wtyczki wbudowane a zewnętrzne

| | wbudowana (`app/features/<id>/`) | zewnętrzna (`plugins/<id>/`) |
|---|---|---|
| manifest | `plugin.json` w katalogu wtyczki | `plugin.json` |
| kod Pythona | `router.py`, `hooks.py` w katalogu | `src/router.py`, `src/hooks.py` |
| import | `app.features.<id>` | `app.plugins_ext.<id>` |
| `static` | ścieżka **od `app/`** (`static/js/features/<id>`) | ścieżka **wewnątrz wtyczki** (`static`) |
| w repozytorium | tak | tylko `example_hello` |

Wbudowane wtyczki (`obstacles`, `route_planner`) przeszły na nowy format;
ich pliki UI zostają w `app/static/js/features/<id>/`. Pola `requires`
planera (`["obstacles"]`) pokazują, że kontroli kolizji używa tylko wtedy,
gdy przeszkody działają - planer działa też bez nich.

## Testy

* `tests/test_plugins_registry.py` - manifesty, wersje, odkrywanie,
  zależności, cykl, brakująca zależność.
* `tests/test_plugins_app.py` - montowanie API i statyków, przykładowa
  wtyczka, wtyczka z błędem składni nie wywraca aplikacji, aplikacja
  z wszystkimi wtyczkami wyłączonymi, przełącznik zapisujący `config.json`.


