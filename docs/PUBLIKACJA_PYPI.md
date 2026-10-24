# Publikacja biblioteki `dronemoves` na PyPI

Instrukcja dla wydającego wersję. **Nic nie jest publikowane automatycznie** -
wszystkie kroki z `twine upload` wykonujesz sam.

## 0. Zanim zaczniesz

* Konto na [pypi.org](https://pypi.org/account/register/) i osobne na
  [test.pypi.org](https://test.pypi.org/account/register/) (to dwa różne konta).
* Włączone **2FA** na PyPI (wymagane od 2024).
* Token API zamiast hasła: PyPI → *Account settings* → *API tokens* →
  *Add API token*. Dla pierwszej publikacji zakres **„Entire account”**
  (potem zawęź do projektu po pierwszym uploadzie).

## 1. Podnieś wersję

W `lib/dronemoves/pyproject.toml`:

```toml
version = "0.2.3"
```

oraz `lib/dronemoves/dronemoves/__init__.py`:

```python
__version__ = "0.2.3"
```

Dopisz sekcję do `lib/dronemoves/CHANGELOG.md` (data, *Naprawione* / *Dodane*).
PyPI **nie pozwala** nadpisać wersji - numer musi być nowy.

## 2. Testy i budowa

```bat
cd lib\dronemoves
D:\DroneSim\.venv\Scripts\python.exe -m pytest -q
D:\DroneSim\.venv\Scripts\python.exe -m build
D:\DroneSim\.venv\Scripts\python.exe -m twine check --strict dist\dronemoves-0.2.3*
```

`build` tworzy `dist/dronemoves-0.2.3.tar.gz` (źródła) i `...-py3-none-any.whl`
(paczka uniwersalna). Katalog `dist/` jest w `.gitignore` - **nie commituj**
paczki.

## 3. Najpierw TestPyPI

```bat
D:\DroneSim\.venv\Scripts\python.exe -m twine upload --repository testpypi dist\dronemoves-0.2.3*
```

* username: `__token__`
* password: token **z TestPyPI**

Sprawdź instalację z TestPyPI w osobnym środowisku:

```bat
python -m venv %TEMP%\venv_testpypi
%TEMP%\venv_testpypi\Scripts\python.exe -m pip install --index-url https://test.pypi.org/simple/ ^
    --extra-index-url https://pypi.org/simple/ dronemoves[tello]
%TEMP%\venv_testpypi\Scripts\python.exe -c "import dronemoves; print(dronemoves.__version__)"
```

`--extra-index-url` jest konieczne, bo TestPyPI nie ma zależności
(`djitellopy`, `pytest`). Otwórz też stronę projektu:
`https://test.pypi.org/project/dronemoves/` i sprawdź, czy README renderuje
się poprawnie.

## 4. Publikacja na PyPI

```bat
D:\DroneSim\.venv\Scripts\python.exe -m twine upload dist\dronemoves-0.2.3*
```

* username: `__token__`
* password: token **z PyPI**

Po uploadzie: `https://pypi.org/project/dronemoves/`. Instalacja u użytkownika:

```bat
pip install dronemoves          # samo API + symulator (bez djitellopy)
pip install "dronemoves[tello]" # z backendem dla prawdziwego Tello
```

## 5. Kolejna wersja

1. Zmień `version` w `pyproject.toml` i `__init__.py`, dopisz CHANGELOG.
2. `pytest` → `build` → `twine check --strict`.
3. Opcjonalnie TestPyPI, potem `twine upload`.
4. Zaktualizuj tag w repozytorium (`git tag v0.2.3`), jeśli wydajesz z taga.

**Nie da się usunąć wersji** z PyPI - można tylko ją *yank* (ukryć z instalacji
domyślnej, `pip install dronemoves==0.2.3` nadal działa). Dlatego zawsze
sprawdzaj paczkę na TestPyPI.

## Checklist przed publikacją

- [ ] `pytest` w `lib/dronemoves` zielono
- [ ] wersja w `pyproject.toml` = wersja w `__init__.py`
- [ ] CHANGELOG ma sekcję dla tej wersji
- [ ] `twine check --strict` PASSED
- [ ] README bez linków względnych (wszystkie `https://github.com/Vardeex/drone-script-sim/...`)
- [ ] paczka nie zawiera `dist/`, `.venv/`, `__pycache__`
- [ ] token ma odpowiedni zakres (TestPyPI vs PyPI - **różne** tokeny)

## Znane pułapki

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| `HTTPError: 403 Invalid or non-existent authentication information` | hasło zamiast tokenu albo token z TestPyPI wysłany na PyPI |
| `HTTPError: 400 File already exists` | ta wersja już jest - podnieś numer |
| `InvalidDistribution: ... License classifiers` | przy ``license = "MIT"`` (SPDX) nie dodawaj klasyfikatora ``License ::`` |
| TestPyPI: brak `djitellopy` przy instalacji | dodaj `--extra-index-url https://pypi.org/simple/` |
| README na PyPI bez obrazków | obrazy muszą mieć bezwzględne URL-e |
