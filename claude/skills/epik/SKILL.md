---
name: epik
description: Cały epik z Jiry — jego zadania równolegle i weryfikacja epiku na złożonych gałęziach. Załaduj, gdy Sebastian pisze /epik z ID epika (np. /epik TICKET-1273) albo prosi o zrobienie całego epika.
---

Wejście: ID epika (`TICKET-1273`). Ten skill **wykonuje** epik, nie tylko go planuje: po analizie startuje
od razu, bez pytania o zgodę, i dokłada zadania, aż epik się skończy albo zostaną same zablokowane.
Każde pojedyncze zadanie idzie procedurą ze skilla `task` — załaduj go raz, na początku.

## 1. Zbierz epik

`searchJiraIssuesUsingJql` (cloudId `00000000-0000-0000-0000-000000000000`): `parent = <EPIC>` — a gdy
projekt używa starego pola, `"Epic Link" = <EPIC>`. Każde dziecko czytasz przez `getJiraIssue`
(`responseContentFormat: markdown`) razem z `issuelinks` i statusem. Zadania już zrobione albo w toku
wypadają z planu, ale zostają w grafie jako spełnione zależności.

## 2. Zbuduj graf zależności

Jira pokazuje tylko część prawdy. Cztery źródła krawędzi, wszystkie obowiązkowe:

- **Jawne z Jiry** — `blocks` / `is blocked by`, podzadania, zdania w opisie mówiące „po SW-…".
- **Wspólny kod** — dwa zadania ruszające ten sam moduł w tym samym repozytorium konfliktują; jeśli
  jedno zmienia kontrakt, którego drugie używa, to jest krawędź, a nie równoległość.
- **Stos gałęzi** — zadanie, którego PR celuje w gałąź innego zadania, może ruszyć dopiero, gdy tamta
  gałąź istnieje i jest wypchnięta (nie: zmergowana). Baza, która dostaje rundę poprawek, unieważnia
  worktree potomka — wtedy rebase, zanim potomek pojedzie dalej.
- **Kolejność wdrożenia** — producent modelu przed konsumentem (`common`/`liquibase` przed serwisami,
  dane przed ekranem, który je pokazuje). To krawędź nawet wtedy, gdy kod kompiluje się bez niej.

Niepewna krawędź jest krawędzią: fałszywa równoległość kosztuje rundę konfliktów, fałszywa zależność
kosztuje trochę czasu.

## 3. Policz harmonogram

Sortowanie topologiczne, a potem: **ścieżka krytyczna** (najdłuższy łańcuch zależności — to jest dolna
granica czasu epika) i dla każdego zadania klasa S/M/L/XL wg CLAUDE.md jako zgrubny koszt. Zadania na
ścieżce krytycznej startują przed wszystkim innym, co ma tę samą gotowość — opóźnienie na nich opóźnia
cały epik, opóźnienie poza nią nie.

Nie pracuj falami z barierą: zadanie rusza w chwili, gdy jego zależności są spełnione, a nie gdy cała
poprzednia fala skończy. Po każdym ukończonym zadaniu przelicz, co się odblokowało, i dołóż.

## 4. Ograniczenia zasobów — to one, a nie liczba agentów, ustalają sufit

- **Równolegle maksymalnie 3 zadania.** Każde to własny `implementer` (Sonnet 5.5, medium) , a Twój kontekst musi przeżyć cały epik — to Ty recenzujesz
  i testujesz każde z nich.
- **Jedno repozytorium, kilka zadań naraz → osobne worktree** (`__HOME__/projects/cloud/.worktrees/<repo>-<ID>`).
  Nigdy dwa zadania w tym samym checkoucie; nigdy `checkout` w katalogu Sebastiana.
- **Minimalny stack docker jest jeden i wspólny.** Testy integracyjne i zrzuty ekranu przechodzą przez
  niego pojedynczo — dwa zadania wstawiające naraz dane testowe do tej samej bazy dają wynik, którego
  nie da się obronić. Fazę integracyjną serializuj, resztę zadania rób równolegle.
- **Kliknięcie logowania** przy zrzutach zostaje przy Sebastianie. Zbieraj te prośby i wystawiaj jedną,
  gdy kilka zadań czeka na panel, zamiast przerywać mu pracę osobno przy każdym.

## 5. Prowadź

Supervise jak w CLAUDE.md — reagujesz, gdy zadanie się melduje. Zadanie zablokowane **nie zatrzymuje
epika**: odetnij jego potomków w grafie, jedź dalej tym, co zostało, i wypisz to w raporcie. Limity
z CLAUDE.md — 3 rundy poprawek bez postępu na tym samym findingu — obowiązują w każdym zadaniu
osobno. Epikowy przebieg integracyjny też ma testy regresyjne dla każdego buga znalezionego w
zadaniach, na mockach granic zewnętrznych.

Gdy dwa zadania zaczynają walczyć o ten sam plik mimo grafu, to znaczy, że krawędzi brakowało — dołóż
ją, zatrzymaj to, które jest dalej od ukończenia, i zapisz powód w raporcie.

## 6. Weryfikacja całego epika — po otwarciu wszystkich PR-ów

Zielone zadania nie znaczą zielony epik: każde z nich testowało własny kawałek na własnej gałęzi, a
defekty epika mieszkają dokładnie tam, gdzie te kawałki się spotykają. Gdy PR-y wszystkich zadań są
otwarte, robisz **jeden przebieg na całości**.

**Złożenie.** W worktree, per repozytorium dotknięte epikiem, gałąź `test/<EPIC>-integration`, do której
mergujesz wszystkie gałęzie zadań epika w ustalonej kolejności merge'owania. Konflikt na tym etapie to
finding, nie niedogodność — znaczy, że graf albo kolejność były złe; zapisz go i popraw kolejność.
Ta gałąź jest jednorazowa: **nigdy nie jest źródłem PR-a i nie idzie na zdalne**.

**Przebieg.** Stack w górę z tego złożenia, a potem:

- **jednostkowo** — pełne zestawy wszystkich repozytoriów dotkniętych epikiem, nie tylko tych z ostatniego
  zadania;
- **integracyjnie** — scenariusze samego epika: przepływy przechodzące przez kilka zadań naraz, których
  z definicji nie sprawdziło żadne pojedyncze zadanie. To jest właściwy cel tego punktu;
- **UI** — przejście końcowej ścieżki użytkownika, którą epik obiecuje, ze zrzutami.

**Macierz pokrycia epika.** Z opisu i kryteriów akceptacji **epika** w Jirze (nie z sumy opisów zadań)
rozpisujesz oczekiwane rezultaty i każdemu przypisujesz dowód, na tych samych zasadach co w skillu
`task`: dowód wykonywalny, czerwony bez zmian epika. Wiersz, którego nie realizuje żadne zadanie, to
**luka w zakresie epika** — zgłoś ją i nazwij, gdzie powinna trafić (którego zadania brakuje), zamiast
dopisywać ją sobie po cichu do któregoś PR-a.

**Gdy coś pada.** Poprawka idzie na gałąź **tego zadania, które jest właścicielem kodu**, i przez jego
PR — nigdy na gałąź integracyjną, bo tamta zniknie. Po poprawce składasz i przebiegasz całość od nowa:
nowy commit unieważnia poprzedni przebieg, tak samo jak unieważnia review.

Jeśli któreś zadanie zostało zablokowane, epik weryfikujesz na tym, co jest, i w raporcie piszesz
wprost, których wierszy macierzy nie dało się sprawdzić z powodu tej dziury.

## 7. Raport

Tabela: zadanie, klasa, PR-y (linki), status, na czym stało. Do tego: **macierz pokrycia epika z punktu
6** (oczekiwany rezultat epika → dowód → wynik) razem z wynikiem przebiegu na złożeniu, luki w zakresie
i brakujące zadania, ścieżka krytyczna i co realnie wyznaczyło czas epika, kolejność merge'owania PR-ów,
zadania zablokowane z blokerem i potrzebną decyzją, oraz krawędzie zależności, których nie było w Jirze
— te ostatnie warto dopisać do ticketów, żeby następny epik zaczynał z lepszym grafem.

Status **Gotowe do merge** dla epika wymaga zielonego przebiegu na złożeniu wszystkich gałęzi, nie sumy
zielonych zadań.
