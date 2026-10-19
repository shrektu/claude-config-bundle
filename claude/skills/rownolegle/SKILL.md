---
name: rownolegle
description: Niezależne milestone'y zadania L/XL równolegle — osobny implementer w osobnym worktree, review i commit per milestone, lądowanie rebase + ff w kolejności zależności. Załaduj, gdy plan L/XL ma co najmniej dwa milestone'y bez krawędzi między sobą.
---

Po co: implementer to największy koszt czasu w tym workflow (mediana przebiegu 11 min, p90 33 min), a
kolejno puszczane milestone'y czekają na siebie bez powodu. Niezależne milestone'y idą naraz, każdy na
własnym worktree i własnej lokalnej podgałęzi; zależne nadal po kolei. Zasady grafu i limitów są te
same co w skillu `epik` (§2 krawędzie, §4 zasoby), tylko na poziomie milestone'ów jednego zadania.

## 1. Graf milestone'ów — w planie, przed bramką planu

Każdy milestone wypisuje pliki, które tworzy lub edytuje, testy też. Krawędź (A przed B), gdy:

- **ten sam plik** — B edytuje plik, który edytuje A, inaczej niż dopisując na końcu (niżej);
- **kontrakt** — B używa typu, schematu, endpointu, stałej, komponentu albo fixture'a, który A tworzy
  lub zmienia. Wspólny kontrakt idzie do sekwencyjnego M0, który ląduje, zanim reszta się rozwidli;
- **zasoby i dane** — migracja, lockfile, konfiguracja buildu, wspólny conftest/fixture;
- **kolejność wdrożenia** — producent przed konsumentem, jak w `epik`.

**Pliki wspólne** (moduł stałych, pliki tłumaczeń, rejestr importów): plan deklaruje je wprost jako
wspólne. Milestone'y równoległe mogą do nich tylko **dopisywać** — nowa stała, nowy klucz, nowy import;
każda inna zmiana takiego pliku to krawędź. Niepewna krawędź jest krawędzią. Bramka planu (`codex-runner`
mode plan) dostaje graf razem z planem.

## 2. Rozwidlenie

Milestone startuje, gdy **wszystkie jego poprzedniki wylądowały** na gałęzi zadania (§5) — sam commit
poprzednika na jego podgałęzi to za mało, bo worktree rozwidla się od gałęzi zadania. Naraz najwyżej
**3 implementery**, licząc razem z równoległymi zadaniami epika.

    git -C <checkout gałęzi zadania> worktree add \
      __HOME__/projects/.worktrees/<repo>-<ID>-m<N> -b <gałąź-zadania>-m<N> <gałąź-zadania>

Podgałąź ma prefiks gałęzi zadania (`feature/…-m2`), więc commit i rebase na niej przechodzą przez
git-policy. Jest tylko lokalna — nigdy nie idzie na zdalne. Zapisz SHA rozwidlenia (`git rev-parse
<gałąź-zadania>`) w dzienniku: to `diff_base` bramki kodu i baza review tego milestone'a.

## 3. Delegacja

Jeden `implementer` na worktree, zwykły szablon `delegate`, z dwiema różnicami: ścieżka projektu to
worktree, a `Repos:` pozwala tylko na ten worktree. tdd-guard, verify, review-checkpoint i ai-review-gate
liczą wszystko od korzenia worktree, więc każdy milestone ma własny RED.

W równoległych worktree implementer uruchamia tylko testy celowane i lint swoich plików. To, co
dotyka zasobu współdzielonego — stack docker, baza, stały port, urządzenie, port szeregowy, flashowana
płytka, pełny build firmware albo twister — nie idzie równolegle: należy do kroku integracji (§6) i
uruchamiasz to Ty, po kolei. Napisz to w `extra_context` delegacji.

## 4. Bez bariery

Gdy milestone się melduje, robisz jego rundę dokładnie jak w CLAUDE.md, tylko w jego worktree: status
i diff względem SHA rozwidlenia, testy przez verify, review, w tle bramka kodu z `diff_base` = SHA
rozwidlenia i doradcze `ai-review-gate check --repo <worktree>`, poprawki przez SendMessage do tego
implementera. Czysty milestone commitujesz na jego
podgałęzi (bramka standardów działa jak zawsze) i od razu lądujesz go (§5). Potem przeliczasz, co się
odblokowało, i puszczasz następny — nie czekasz na resztę rówieśników.

## 5. Lądowanie, w kolejności zależności

    git -C <worktree> rebase <gałąź-zadania>
    git -C <checkout gałęzi zadania> merge --ff-only <gałąź-zadania>-m<N>

Historia zostaje liniowa, jeden commit na milestone, jego wiadomość bez zmian. Gdy rebase staje na
konflikcie:

- **Dopisek w pliku wspólnym** (dwie stałe, dwa klucze, dwa importy) — scalasz sam, jak trywialną
  poprawkę z CLAUDE.md.
- **Cokolwiek innego** — brakowało krawędzi. Zapisz ją w dzienniku, zostaw znaczniki konfliktu i wyślij
  implementerowi tego milestone'a (SendMessage; gdy go już nie ma, świeży spawn z listą plików) pliki do
  rozwiązania w jego worktree.

W obu przypadkach rozwiązanie przechodzi przez bramki, zanim wyląduje: uruchom testy milestone'a przez
verify, potem `git -C <worktree> add <pliki>` i `git -C <worktree> commit --no-edit` — to zwykły commit,
więc bramka standardów sprawdza rozwiązany stan — a dopiero potem `git -C <worktree> rebase --continue`.
Gołe `rebase --continue` po konflikcie omija bramkę, więc go nie używasz.

Mechanika, która w próbnym przebiegu kosztowała podejścia:

- Ścieżki w poleceniach gita wpisuj dosłownie. Hooki czytają tekst polecenia i nie rozwijają zmiennych
  powłoki, więc `git -C $W commit` kończy się błędem bramki („could not run”).
- Bramka commitu działa przed całym wywołaniem Basha, a odrzucenie anuluje je w całości. Dlatego
  `git add` i `git commit` idą w osobnych wywołaniach — `add` sklejony z odrzuconym commitem się nie
  wykona.

Po lądowaniu sprzątasz: `git -C <checkout> worktree remove <worktree>` (odmówi przy brudnym drzewie —
wtedy najpierw sprawdzasz `status --short`; usuwasz tylko produkty testów i buildu, np. `__pycache__`,
i nigdy nie używasz `--force`) i `git -C <checkout> branch -d <gałąź-zadania>-m<N>`
(odmówi, gdy podgałąź nie jest scalona).

## 6. Integracja — po ostatnim lądowaniu

Krok 8 z CLAUDE.md na gałęzi zadania: testy modułów zmienionych przez wszystkie milestone'y, lint zmienionych plików (pełny zestaw i build tylko dla XL albo wspólnego kodu), a do tego wszystko, co w §3
odłożyłeś na zasobach współdzielonych — po kolei. Do tego jedna bramka kodu z `diff_base` = gałąź bazowa
na całości: błędy interakcji mieszkają tam, gdzie milestone'y się spotykają. Regresję z tego kroku
poprawia implementer w checkoucie gałęzi zadania (SendMessage z nową ścieżką albo świeży spawn), już
sekwencyjnie, z testem regresyjnym jak każdy finding.

## 7. Dziennik

Jeden dziennik gałęzi zadania, sekcja na milestone: SHA rozwidlenia, ścieżka worktree, rundy, ścieżki
logów RED, findingi, SHA po lądowaniu, krawędzie dopisane po konflikcie i kto je wykrył.
