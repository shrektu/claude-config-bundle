---
name: task
description: Jedno zadanie z Jiry od ID do otwartego PR-a. Załaduj, gdy Sebastian pisze /task z ID zadania (np. /task TICKET-1274) albo prosi o zrobienie konkretnego ticketa z Jiry.
---

Wejście: jedno ID zadania (`TICKET-1274`). Bez ID — zapytaj, nie zgaduj z gałęzi.

Ten skill jest procedurą, nie drugim zbiorem zasad: klasy zadań, delegacja, review i commity
działają dokładnie tak, jak opisuje `~/.claude/CLAUDE.md`. Tutaj jest tylko to, co dochodzi
specyficznie dla zadania z Jiry: skąd wziąć zakres, jak przetestować i jak otworzyć PR-a.

## 1. Ticket jest źródłem zakresu

`getJiraIssue` (Atlassian MCP), cloudId `00000000-0000-0000-0000-000000000000`, site `example.atlassian.net`,
`responseContentFormat: markdown`. Przeczytaj też epik-rodzica i zadania powiązane (`issuelinks`) — one
mówią, na czym to zadanie stoi i co po nim idzie. Opis w Jirze wygrywa z Twoją interpretacją tytułu;
sprzeczność między ticketem a kodem jest pytaniem do Sebastiana, nie miejscem na własną decyzję.

Z ticketu wyciągnij: co ma działać po zmianie, których repozytoriów dotyka, czy rusza UI, czy rusza
dane/protokół/migracje (to podbija klasę do XL wg tabeli w CLAUDE.md).

## 2. Repozytoria i gałąź

Zadania w tym projekcie regularnie dotykają wielu repozytoriów naraz — nie zakładaj jednego. Gdy nie
widać z ticketu, gdzie leży kod, wyślij `Explore`, zanim cokolwiek zaplanujesz.

Gałąź: `feature/<ID>-<krótki-slug>` z `develop` (hotfix z `master`), ta sama nazwa we wszystkich repo
zadania. Gdy zadanie stoi na innym niepozmergowanym zadaniu, bazą jest gałąź tamtego zadania, nie
`develop` — wtedy PR celuje w tamtą gałąź. Jeśli checkout Sebastiana stoi na innej gałęzi albo ma
niezacommitowaną pracę, pracuj w worktree (`__HOME__/projects/cloud/.worktrees/<repo>-<ID>`),
nigdy przez `checkout` w jego katalogu.

## 3. Workflow

Plan i klasa w jednej turze. W planie sekcja `reuse`: zanim cokolwiek zaprojektujesz, grepnij repo i
biblioteki wspólne (albo zapytaj LSP o referencje) i wypisz istniejące helpery, typy, stałe, komponenty i
fixture'y z file:line, na których milestone ma się oprzeć. Potem wszystko jak w CLAUDE.md: implementację robi `implementer` (Sonnet 5.5,
effort medium), każdą rundę sprawdzasz i testujesz sam, poprawki jedną paczką na rundę przez
SendMessage, bez linterów w review; bramki Codexa (`codex-runner`, mode plan przed implementacją L/XL, a dla M równolegle z fazą testów akceptacyjnych implementera — S jej nie ma — i mode code przed każdym commitem) jak w CLAUDE.md. Commity
milestone'owe, wiadomość: jedno zdanie w trybie rozkazującym, max 7 słów, bez trailerów. Nic tu nie jest wyjątkiem od tamtych reguł.
Zadanie L/XL z co najmniej dwoma niezależnymi milestone'ami: graf w planie i równoległe worktree wg skilla `rownolegle`.

## 4. Testy — to jest bramka do PR-a

PR powstaje dopiero, gdy **każdy oczekiwany rezultat z ticketu ma wykonywalny dowód**, a oba poziomy
testów są zielone. Nie „testy przeszły", tylko „funkcjonalność robi to, co ticket obiecał".

### 4a. Macierz pokrycia

Zanim uruchomisz cokolwiek, rozpisz z opisu i kryteriów akceptacji w Jirze listę oczekiwanych
zachowań — jeden wiersz na zachowanie, słowami z ticketu, nie Twoją parafrazą. Pod nimi osobne
wiersze na scenariusze błędów z planu (puste, granica, współbieżność, uprawnienia, strefa czasowa…) —
każdy z nazwanym testem; scenariusz, którego ticket nie rozstrzyga, idzie od razu do Sebastiana jako
NIEJASNE, nie jako Twoja decyzja. Do każdego wiersza
dopisujesz konkretny dowód: nazwa testu jednostkowego, scenariusz integracyjny albo (dla wierszy
czysto wizualnych) zrzut ekranu — **i ścieżkę logu czerwonego przebiegu**, tego, w którym ten test padał
przed zmianą (`~/.claude/bin/verify --repo <repo> -- '<komenda>'`, wpis `red` w
`~/.cache/claude-verify/ledger.jsonl`). Wiersz bez ścieżki logu RED jest deklaracją, nie dowodem;
przebieg, który się wysypał (błąd importu, błąd zbierania, literówka w komendzie) nie jest czerwony. Wiersz bez dowodu ma dwie możliwe przyczyny i obie mają akcję:
brakuje testu — dopisz go; brakuje implementacji — wraca do pętli poprawek. **Żadnego wiersza nie
zamykasz zdaniem „kod wygląda poprawnie"** ani jednorazową obserwacją, której nie da się powtórzyć.

„Pokryte w 100%" znaczy tu: każdy oczekiwany rezultat ma dowód — nie procent pokrycia linii. Te dwie
rzeczy potrafią się mijać w obie strony i mylenie ich jest właśnie tym, co przepuszcza defekty.

### 4b. Uruchomienie

Obie komendy przez `~/.claude/bin/verify`:

- **jednostkowe** — testy modułów, które ruszyłeś (ich pliki testowe i testy bezpośrednich wywołujących), raz, na końcu; pełny zestaw repo tylko dla XL albo zmian we wspólnym kodzie (CLAUDE.md, Rules „Test runs”);
- **integracyjne** — na postawionym minimalnym stacku: `docker compose -f docker-compose.minimal.yml
  up -d --build <serwis>` w `__HOME__/projects/cloud/cloud-platform-dev`, dane testowe wstawiasz
  SQL-em przez `... exec -T db psql -U exa_db -d exa_db` i **sprzątasz je po sobie**.

### 4c. Dowód musi być dowodem

Każdy test, którym zamykasz wiersz macierzy, **musi być czerwony bez Twojej zmiany** — zmutuj kod
produkcyjny albo cofnij zmianę i zobacz, że test pada. I sprawdź, że mutacja rzeczywiście się przyjęła:
w tym projekcie zdarzyło się dwa razy, że mutacja nie dopasowała się do kodu, a zielony przebieg nie
znaczył nic. Test, który przechodzi, bo mockuje właśnie tę wiązkę, którą zmieniłeś, nie jest dowodem.

Pamięć `reports-epic-progress` wymienia klasy defektów, które w tym projekcie przechodziły przez zielone
testy — kolejność walidacji w marshmallow, inner join po nullowalnym FK, SQLite ukrywający PostgreSQL,
mockowe fixture'y podmieniające właśnie sprawdzaną wiązkę. Przejdź tę listę, zanim uznasz zielone za
koniec.

**Każdy bug znaleziony w review dostaje własny test regresyjny na obu poziomach:**
jednostkowy oraz integracyjny na mockach/fake'ach granic zewnętrznych (sprzęt, magistrala, sieć, inne
serwisy, zegar), nazwany od buga i czerwony bez poprawki. W macierzy pokrycia każdy taki bug ma osobny
wiersz („bug: …”) z nazwami obu testów. Bez drugiego recenzenta to te testy, a nie kolejne rundy
review, są dowodem, że bug nie wróci.

### 4d. Czerwone wraca

Każda czerwona pozycja i każdy niepokryty wiersz wracają do pętli poprawek (limity z CLAUDE.md
obowiązują: 3 rundy poprawek bez postępu na tym samym findingu → eskalacja). Nie ma PR-a z pominiętym testem, z wierszem bez dowodu ani z dowodem, którego
nie przebiegłeś po ostatniej zmianie kodu. Macierz idzie do raportu końcowego w całości.

### 4e. QA — trudne scenariusze e2e

Gdy macierz jest zielona, załaduj skill `qa` z ID zadania. Testuje on końcowe commity gałęzi na
izolowanym stacku i wymyśla scenariusze, których macierz nie ma. To bramka do PR-a na zasadach z punktu
11 tamtego skilla: FAIL wraca do pętli poprawek jako finding, NIEJASNE czeka na Sebastiana, NIE
URUCHOMIONY jest blokerem, a FAIL (zastany) idzie do `## Dodatkowy kontekst`. Każdy commit po
przebiegu QA unieważnia jego wynik — przed PR-em pełny przebieg na końcowych SHA.

## 5. Zrzuty ekranu, gdy zmiana dotyka UI

„Nowe pole, zmieniony stan kontrolki, inna wyświetlana wartość" to też UI. Procedura jest w pamięciach
`pr-screenshots-required` i `browser-check-login-rule`:

1. minimalny stack w górę, panel Browser na `http://localhost/`;
2. wpisz e-mail (`admin@email.com`) i **poproś Sebastiana o jedno kliknięcie zalogowania** — hasła nie
   wpisujesz nigdy, to twarda zasada, nie preferencja. To jedyny moment, w którym ten skill przerywa
   pracę i czeka na człowieka; zbierz wszystkie takie prośby w jedną;
3. dalej sterujesz sam: nawigacja, dane, zrzuty. Before/after zawsze, gdy zmieniasz coś, co już istniało.

Wrzucenie zrzutu do PR-a (Bitbucket nie ma załączników do PR-ów — idzie przez downloads repozytorium):

```bash
curl -s -u "$(cat ~/.config/bitbucket/credentials)" -X POST \
  "https://api.bitbucket.org/2.0/repositories/acme/<repo>/downloads" \
  -F files=@<id-zadania>-<co-widac>.png
```

Nazwa pliku zaczyna się od ID zadania — `downloads` to płaska przestrzeń nazw na całe repozytorium.
W opisie linkujesz `https://bitbucket.org/acme/<repo>/downloads/<plik>.png`. Placeholder tylko wtedy,
gdy stacku naprawdę nie da się postawić, i wtedy jedną linią piszesz dlaczego.

## 6. PR

Push gałęzi, potem dla każdego repozytorium:

```bash
curl -s -u "$(cat ~/.config/bitbucket/credentials)" -X POST \
  "https://api.bitbucket.org/2.0/repositories/acme/<repo>/pullrequests" \
  -H 'Content-Type: application/json' -d '{"title": ..., "source": {"branch": {"name": ...}},
      "destination": {"branch": {"name": ...}}, "description": ...}'
```

PR powstaje **gotowy do review**, nie jako draft — testy przeszły, więc praca jest funkcjonalnie
skończona, a `/bb` i tak omija drafty. Tytuł i opis z `pr-description` (`[ID] Krótki opis`, sekcje po
polsku, `## Screenshots` z linkami z punktu 5). Przy wielu repozytoriach: tytuł `[MULTI][ID] …`, a
wzajemne linki w `## Powiązane PR` dopisujesz **drugim** requestem `PUT`, bo numery PR-ów znasz dopiero
po utworzeniu wszystkich — w `PUT` wysyłasz też `title`, inaczej Bitbucket go gubi.

Kolejność ma znaczenie: PR bazowy stosu przed tym, który na nim stoi; gdy zadanie wymaga kolejności
wdrożenia (np. `common` przed konsumentami), napisz ją w `## Dodatkowy kontekst`.

Statusu w Jirze nie ruszasz i nie komentujesz tam nic — to zostaje przy Sebastianie, chyba że poprosi.

## 7. Raport

Format końcowy ze skilla `review`, plus: **macierz pokrycia z punktu 4a w całości** (oczekiwany rezultat
→ dowód → wynik), **tabela scenariuszy QA z punktu 4e** z testowanymi SHA, link do każdego PR-a,
linie `VERIFY` z obu poziomów testów, co pokazują zrzuty,
ustalona kolejność merge'owania. Jeśli któryś wiersz zamknąłeś dowodem słabszym niż test (zrzut,
obserwacja na stacku), powiedz to wprost przy tym wierszu — to jest informacja dla człowieka, który
będzie to mergował. Bez PR-a status to **Zablokowane** z blokerem i decyzją, której potrzebujesz —
nigdy „gotowe", żeby domknąć pętlę.
