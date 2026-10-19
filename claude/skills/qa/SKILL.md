---
name: qa
description: Trudne scenariusze e2e dla zadania z Jiry na izolowanym stacku, z wynikiem PASS / FAIL / NIEJASNE i dowodem. Załaduj, gdy Sebastian pisze /qa z ID zadania albo prosi o przetestowanie lub przeklikanie zadania, oraz zawsze w kroku 4e skilla task.
argument-hint: <JIRA-ID>
---

Wejście: `$ARGUMENTS` — jedno ID zadania (`TICKET-1274`). Bez ID zapytaj, nie zgaduj z gałęzi.

Jesteś testerem, nie implementerem. Nie poprawiasz kodu, nie commitujesz, nie ruszasz gałęzi ani
checkoutów Sebastiana. Wszystko, co piszesz — scenariusze, specy, override compose, raport — ląduje w
`~/.cache/claude-qa/runs/<ID>/`. Celem jest znaleźć to, co nie działa: scenariusz, który przechodzi,
nie jest porażką, ale lista samych szczęśliwych ścieżek jest.

## 1. Wyrocznia z Jiry

`getJiraIssue` (cloudId `00000000-0000-0000-0000-000000000000`, `responseContentFormat: markdown`), epik-rodzic
i `issuelinks`. Wypisz oczekiwane rezultaty słowami ticketu — to jedyna wyrocznia PASS/FAIL. Zachowanie,
którego ticket nie określa, nie jest ani PASS, ani FAIL: to **NIEJASNE** z konkretnym pytaniem. Nie
rozstrzygasz go tym, co akurat robi kod — wtedy test sprawdzałby kod sam ze sobą.

## 2. Gałęzie zadania

Repozytoria: `~/projects/cloud/cloud-common`, `~/projects/cloud/cloud-platform-dev/repos/*` oraz
`~/projects/kiosk/*` z własnym `.git`. W każdym `git fetch --quiet origin` i
`git branch -a --list "*<ID>*"`. Wynik to tabela: repo → gałąź → baza (`develop`; `common` i
`content-management` → `master`; zadanie stojące na innym niepozmergowanym zadaniu → gałąź tamtego).

**Testujesz commit, nie katalog.** SHA = lokalna gałąź zadania, jeśli istnieje, inaczej `origin/<gałąź>`.
Dla każdego repo zakładasz świeży, własny worktree:

```bash
git -C <repo> worktree add --detach ~/projects/cloud/.worktrees/qa-<repo>-<ID> <sha>
git -C ~/projects/cloud/.worktrees/qa-<repo>-<ID> submodule update --init
```

Nigdy nie budujesz z worktree, w którym pracuje implementer albo inna sesja — mogą tam leżeć
niezacommitowane zmiany. Jeśli submoduł `common` w gałęzi serwisu wskazuje inny commit niż głowa gałęzi
zadania w `cloud-common`, to jest finding (serwis zbudowany ze starego `common`), nie coś do
poprawienia po cichu. Wynik QA jest ważny tylko dla tych SHA — zapisz je w nagłówku raportu.

## 3. Mapa zmiany

`git diff <baza>...<sha> --stat` i czytanie zmienionych plików (plasterkami): jakie ekrany, endpointy,
zapytania, migracje, komunikaty NATS, zadania okresowe. Dla każdej zmienionej gałęzi logiki, warunku
i zapytania zanotuj `plik:linia` — to z nich biorą się trudne scenariusze.

## 4. Trudne scenariusze

Załaduj `references/scenariusze.md` i pisz scenariusze **zanim zajrzysz do testów implementera** — inaczej
powtórzysz jego założenia. Minimum: każdy oczekiwany rezultat z ticketu ma jeden scenariusz szczęśliwy
i co najmniej dwa trudne. Trudny znaczy: ma nazwany mechanizm, który może pęknąć, wskazany w diffie.

Każdy scenariusz: `S01…`, tytuł, dlaczego trudny (`plik:linia`), stan początkowy i dane, kroki,
oczekiwany wynik z cytatem z ticketu albo NIEJASNE, forma testu (punkt 5). Zapisz je do
`runs/<ID>/scenarios.md`, zanim powstanie pierwszy spec. Dopiero teraz przejrzyj testy implementera:
scenariusz, który już pokrywają, i tak uruchamiasz — QA jest niezależnym dowodem.

## 5. Forma testu — drabina

Bierzesz najwyższy szczebel, który da się uruchomić. Każde zejście niżej ma w raporcie jednozdaniowy
powód; „tak było szybciej" nie jest powodem.

1. **Playwright UI na stacku QA** — domyślna dla wszystkiego, co widać w panelu.
2. **Playwright `request` przez proxy UI** (`http://localhost:8480/api/...`, ta sama sesja) — gdy nie ma
   ekranu (endpoint, eksport, raport) albo scenariusz wymaga równoległych żądań.
3. **Asercja na bazie QA** (`qa exec -T db psql ...`) — jako druga asercja do 1 lub 2, nigdy zamiast.
4. **Test integracyjny repo na prawdziwym Postgresie** (nie SQLite) — gdy scenariusza nie da się wywołać
   z zewnątrz: zadanie okresowe, konsument NATS bez endpointu.
5. **Strona maszyny** (`device-service`, `kiosk-ui`, `nats-gateway`, `kiosk-machine-docker`): stack maszyny z
   `kiosk-machine-docker` (`docker-compose.mock.yml`, `wiremock/`) i prawdziwy protokół z fałszywym
   peerem; UI kiosku i service menu — Playwright jak w 1. Pierwszy przepis, który zadziała, zapisz do
   `references/kiosk-stack.md`, żeby następny przebieg go nie odkrywał.
6. **Test jednostkowy** — ostatnia deska, oznaczony w raporcie jako słaby dowód.

## 6. Stack QA

Przepis ze sprawdzonymi komendami: `references/acme-stack.md`. W skrócie: klon bazy w wolumenie
`acme-qa_pgdata`, projekt compose `acme-qa`, serwisy zmienione w zadaniu budowane z worktree QA,
reszta z obrazów `cloud-platform-*`, liquibase z gałęzi zadania (albo `origin/develop`) na klonie, UI na
`:8480`. Stack i baza Sebastiana zostają nietknięte, a scenariusze mogą bezkarnie niszczyć dane.

**Logowanie.** Hasła nie wpisujesz nigdy — ani w formularz, ani przez API (pamięć
`browser-check-login-rule`, twarda reguła). Sesja żyje w `~/.cache/claude-qa/auth/acme-qa.json`; gdy
jej brak albo wygasła, prosisz Sebastiana o jedno zalogowanie komendą z przepisu. Tę prośbę składasz
raz, na początku, zanim zaczniesz pisać specy — potem pracujesz bez przerywania.

## 7. Specy

Pliki w `~/.cache/claude-qa/runs/<ID>/`, tytuł testu zaczyna się od ID scenariusza (`S07 …`) — po nim
wynik wraca do tabeli. Każdy spec zaczyna się od:

```ts
import { test, expect } from '@playwright/test';

test.use({
  baseURL: 'http://localhost:8480',
  storageState: `${process.env.HOME}/.cache/claude-qa/auth/acme-qa.json`,
  screenshot: 'on',
});
```

- asercje na tym, co widzi użytkownik (role, tekst, wartości), nie na klasach CSS;
- żadnego `waitForTimeout` — czekasz na stan (`expect(...).toBeVisible()`, `waitForResponse`);
- każdy scenariusz na własnych danych (SQL w bazie QA albo przez UI), niezależnie od kolejności;
- mutujące żądania API z nagłówkiem `X-CSRF-TOKEN` z ciasteczka `csrf_access_token`;
- zero komentarzy — nazwa testu i kroków mówi, co sprawdzasz.

Uruchomienie i odczyt wyników:

```bash
cd ~/.cache/claude-qa && PLAYWRIGHT_JSON_OUTPUT_NAME=runs/<ID>/results.json \
  ~/.claude/bin/verify -n qa-<ID> -- npx playwright test runs/<ID> \
  --workers=1 --trace=on --output=runs/<ID>/artifacts --reporter=list,json
jq -r '.. | objects | select(has("specs")) | .specs[] | [.title, .tests[0].results[-1].status] | @tsv' \
  ~/.cache/claude-qa/runs/<ID>/results.json
```

Formy 4–6 też idą przez `verify`, a scenariusz dostaje ścieżkę logu jako dowód.

## 8. Czy FAIL jest prawdziwy

Zanim wpiszesz FAIL:

1. obejrzyj zrzut i `error-context.md` z `artifacts/`;
2. odróżnij błąd aplikacji od błędu testu — zły selektor, brak danych, wygasła sesja, serwis nie wstał
   (`qa logs <serwis>`). Błąd testu naprawiasz i puszczasz scenariusz ponownie; to nie jest wynik;
3. potwierdź drugim, niezależnym sposobem, gdy się da: zapytanie SQL, żądanie API, log serwisu;
4. scenariusz, który raz przechodzi, a raz nie (`--repeat-each=3`), to FAIL z dopiskiem „niestabilny" —
   niestabilność to zwykle wyścig, czyli błąd;
5. FAIL spoza obietnic ticketu (sąsiednia funkcja) sprawdź na bazie: przebuduj ten serwis z worktree
   bazy i puść scenariusz jeszcze raz. Pada i tam → **FAIL (zastany)**: raportujesz, nie blokuje.

## 9. Sprzątanie

Zawsze, także po FAIL i po przerwaniu: `qa down`, `docker volume rm acme-qa_pgdata`,
`git -C <repo> worktree remove --force <worktree QA>` — tylko worktree `qa-*`, które sam założyłeś.
Obrazy `acme-qa-*` zostają jako cache budowania. Katalog `runs/<ID>/` zostaje — to dowody.

## 10. Raport

Zapisz do `runs/<ID>/report.md` i zwróć w odpowiedzi:

```
QA TICKET-1234 — 14 scenariuszy: 9 PASS, 3 FAIL, 1 NIEJASNE, 1 NIE URUCHOMIONY
Testowane SHA: cloud-platform-reports abc1234, web-ui def5678; reszta z obrazów cloud-platform-* (<data>)

| #   | Scenariusz | Dlaczego trudny | Forma | Wynik | Dowód |
|-----|------------|-----------------|-------|-------|-------|
| S01 | ...        | ...             | UI    | PASS  | runs/TICKET-1234/ui.spec.ts, zrzut |
```

Pod tabelą:

- **FAIL** — kroki, oczekiwane (cytat z ticketu), faktyczne, zrzut, podejrzane miejsce `plik:linia`.
  Każdy FAIL ma być gotowym findingiem, który da się oddać implementerowi bez dopytywania;
- **NIEJASNE** — pytania do Sebastiana, jedną paczką;
- **NIE URUCHOMIONY** — bloker i to, czego trzeba, żeby ruszył;
- **Zejścia z drabiny** — scenariusz → forma → powód.

## 11. Wywołanie z `task` (krok 4e)

To bramka do PR-a. FAIL wraca do pętli poprawek jako finding — z testem regresyjnym na obu poziomach wg
CLAUDE.md; wskazujesz ścieżkę speca i zrzutu, nie wklejasz ich. Po rundzie poprawek powtarzasz FAIL-e
i scenariusze z tego samego obszaru, a przed PR-em — pełny przebieg na końcowych SHA, bo nowy commit
unieważnia poprzedni wynik. NIEJASNE czeka na odpowiedź Sebastiana, NIE URUCHOMIONY jest blokerem —
PR nie powstaje, dopóki Sebastian nie zdecyduje inaczej. FAIL (zastany) idzie do `## Dodatkowy
kontekst` w PR-ze, nie blokuje. Tabela trafia do raportu `task` i do sekcji `## Scenariusze QA` w PR-ze.
