# Wtyczki (`plugins/`)

Katalog na **wtyczki zewnętrzne**: Twoje własne rozszerzenia aplikacji, które
nie są częścią repozytorium. Każda wtyczka to podkatalog z plikiem
`plugin.json`.

```
plugins/
  example_hello/      <- wzór (jest w repozytorium)
  moja_wtyczka/       <- Twoja wtyczka (ignorowana przez git)
    plugin.json
    src/__init__.py
    src/router.py
    static/panel.js
```

Struktura `example_hello/` jest kompletnym, działającym wzorem: skopiuj ją,
zmień `id` (musi zgadzać się z nazwą katalogu), `name`, `version` i rozbuduj.

`.gitignore` przepuszcza tylko `plugins/README.md` i `plugins/example_hello/` -
reszta wtyczek zostaje lokalnie.

Pełna dokumentacja: [`docs/plugins.md`](../docs/plugins.md).
