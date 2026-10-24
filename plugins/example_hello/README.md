# Przykładowa wtyczka: Hello

Wtyczka zewnętrzna pokazująca pełny wzór rozszerzenia aplikacji:

* **backend**: `src/router.py` - endpointy `GET /api/example_hello/hello`
  i `GET /api/example_hello/info`,
* **panel UI**: `static/panel.js` - zakładka „Hello” z tekstem i przyciskiem
  pytającym API wtyczki,
* **style**: `static/panel.css` - doładowywane przy starcie aplikacji.

## Jak to działa

1. Aplikacja przy starcie skanuje `plugins/*/` w katalogu projektu.
2. Czyta `plugin.json`, sprawdza pola i zależności (`requires`).
3. Montuje router pod `api_prefix`, statyki pod `/static/features/<id>`
   i pokazuje zakładkę w panelu po prawej.
4. Twój kod wtyczki jest importowany jako `app.plugins_ext.example_hello`.

## Jak wyłączyć

Zakładka **Wtyczki** → przełącznik przy „Przykładowa wtyczka: Hello”.
Stan zapisuje się w `config.json` i działa po restarcie serwera:

```json
{ "features": { "example_hello": { "enabled": false } } }
```

Pełny opis pisania wtyczek: [`docs/plugins.md`](../../docs/plugins.md).
