---
name: bb
description: Przegląd Bitbucketa — odpowiedzi i poprawki na moich PR-ach, review cudzych PR-ów komentarzami inline i głosem. Załaduj, gdy Sebastian pisze /bb albo prosi o przejrzenie Bitbucketa, PR-ów, komentarzy czy o zrobienie review.
---

## 0. Zakres

Tylko pull requesty **OPEN**. Draftów nie ruszamy w ogóle: żadnych komentarzy, głosów, odpowiedzi
ani resolve — nawet gdy jestem tam reviewerem i widzę realny błąd. Co najwyżej wspominam o tym
w raporcie. `bb-sweep` domyślnie w ogóle ich nie pokazuje (`--include-drafts` je dołącza).

Wyjątek: gdy Sebastian wprost wskaże konkretny draft do review, robisz na nim pełne review według
§ 2 i publikujesz komentarze; głos oddajesz tylko wtedy, gdy o niego poprosi.

**Czyje PR-y wolno poprawiać.** Kod, gałąź, tytuł, opis i resolve cudzych wątków ruszasz wyłącznie
na PR-ach autorstwa Sebastiana. Na cudzym PR-ze robisz to tylko wtedy, gdy tytuł albo komentarz
napisany przez Sebastiana lub autora PR-a mówi, że Sebastian jest autorem albo przejął zadanie.
Każdy inny PR jest tylko do odczytu, z wyjątkiem review według § 2 (komentarze inline i głos).
Ping, wzmianka czy prośba o poprawkę pod cudzym PR-em, także od bota albo reviewera, nie jest
przejęciem. Wspominasz o niej w raporcie i nie dotykasz gałęzi.

`~/.claude/bin/bb-sweep` — skan (read-only, ~2 min na pełnej liście repozytoriów; `--repos a,b`
zawęża, `--json` do parsowania). Cztery sekcje: **mine**, **review**, **replies**, **approve**.
Wątki oznaczone `[bot]` pochodzą od CodeRabbita, który publikuje jako konto **Jenkins**.
Jedyna pisząca komenda to `bb-sweep resolve <repo> <pr> <id...>` (oraz `resolve --answered`,
hurtowo dla wątków bota na moich PR-ach). Jeśli skan kończy się linią **UWAGA: … nie dało się
w pełni sprawdzić** (API zwróciło błąd mimo ponowień), powtórz skan dla tych repozytoriów
(`--repos`) przed jakimkolwiek głosem czy resolve — pusta sekcja nie znaczy wtedy „nic nie czeka".

Równolegle ze skanem: `~/.claude/bin/bb-sweep harvest` — wątki innych osób na moich PR-ach (otwartych
i zmergowanych), których jeszcze nie przerobiłem na nawyki, także te obsłużone przez rutyny. Każdy
oceniasz jak w § 1 („Nawyk") i oznaczasz wszystkie pokazane: `bb-sweep harvest-mark <repo> <pr>
<thread-id...>` (jedno wywołanie na PR). Dopiero gdy każdy pokazany wątek jest oznaczony:
`bb-sweep harvest-done` — przesuwa datę, od której liczy się następny harvest. Nie wołasz go, gdy coś
zostało nieprzerobione, bo wątki starszych PR-ów wypadłyby z kolejnych przeglądów.

## 1. Moje PR-y (sekcja `mine`)

Każdy wątek bez mojej odpowiedzi — najpierw **reprodukcja**: otwórz plik i linię, uruchom test
albo polecenie. Dopiero potem werdykt.

- **zasadne** → popraw kodem. Klasa zadania wg `~/.claude/CLAUDE.md`; implementację robi
  `implementer` (Sonnet 5.5, effort medium), review jest moje; testy tylko, gdy poprawka zmienia logikę — wtedy tylko testy zmienionego modułu, raz, na końcu. Poprawka idzie na **gałąź-właściciela** kodu: w stosie PR-ów
  komentarz do odziedziczonego pliku naprawiam w najniższym PR-ze, który ten plik zmienia, potem
  merguję w górę stosu i wypycham. Odpowiedź zawiera SHA i gałąź.
- **niezasadne albo świadomy trade-off** → nie zmieniam kodu, odpowiadam z dowodem (plik:linia,
  wynik testu, cytat z dokumentacji). Decyzje produktowe, kontraktowe i architektoniczne na moich
  PR-ach zostawiam sobie: wypisuję je w raporcie (§ 3), nie przemilczam i nie pytam o nie nikogo w wątku.
- odpowiedź po polsku, jedna na wątek (reply z `parent.id`; przy inline kopiuję `inline` rodzica).

**Nawyk.** Uwaga, którą uznałem za zasadną, znaczy, że workflow coś przeoczył. Pytasz: czy reguła
zapobiegłaby temu w innym zadaniu? Jednorazowy błąd logiki to nie nawyk; konwencja zespołu albo repo,
idiom, którego implementer nie zna, powtarzający się brak testu — tak. Sprawdzasz `habits list --all`:
ta sama lekcja jest → `habits bump <id> --source <repo>#<pr>/<thread-id> --reviewer <autor uwagi>`;
nowa → `habits add` (zasada zapisu w skillu `review`, „Habits"). Uwaga niezasadna nie jest nawykiem.
Rutyny „Morning/Evening bitbucket sweep” (RemoteTrigger) działają w chmurze i nie widzą
`~/.claude/lessons/habits.json` — mają w prompcie blok `NAWYKI` z kopią listy. Po każdym `habits add` albo
`habits drop` (sam `bump` treści nie zmienia) odśwież ten blok w obu rutynach:
`python3 ~/.claude/bin/bb-routine-habits` drukuje nowy blok, który wstawiasz w miejsce starego
(`RemoteTrigger update` z pełnym promptem) i potwierdzasz `get`, że oba prompty są identyczne.
Po obsłużeniu wątek oznaczasz: `bb-sweep harvest-mark <repo> <pr> <thread-id>`.

**Nagłówek AI — zawsze.** Każdy komentarz, odpowiedź w wątku i opis PR-a, który publikujesz, zaczyna się
od linii `🤖 Wygenerowane przez Claude` i pustej linii, dopiero potem treść — żeby inni wiedzieli, że rozmawiają z AI. Dotyczy też
krótkich etykiet („🤖 Wygenerowane przez Claude\n\nmagic number”).
Etykiety i jednozdaniowe odpowiedzi piszę sam; dłuższy tekst (objaśnienie zadania, odpowiedź z uzasadnieniem,
opis PR-a) szkicuje `writer` (Sonnet 5.5) z faktów, które mu podaję — sprawdzam go w kodzie i dopiero publikuję.

**Krótko — twarda zasada.** Uwaga o czystości kodu to etykieta do ~5 słów: „magic number",
„magic string", „zduplikowana logika — jest `X`", „połknięty wyjątek", „surowy dict — użyj modelu",
„martwy kod", „mutowalny argument domyślny", „`Any` — typ jest znany", „opóźnienie bez stałej ani komentarza",
„da się prościej: early return", „niespójne z repo — logika w serwisie". Bez nazw norm, numerów reguł i linków. Błąd — jedno, dwa
zdania: co się psuje i kiedy. Na cudzym PR-ze **wyłącznie komentarze inline** przy pliku i linii —
żadnych komentarzy ogólnych, podsumowań review ani odpowiedzi zbiorczych; to tylko zaśmieca PR.
Jedyne wyjątki: „brak opisu PR” i „opis PR niezgodny z kodem” (niżej, przy obrazkach).
Podsumowanie idzie wyłącznie do mojego raportu.
Bez wstępów, bez powtarzania uwagi własnymi słowami, bez chwalenia autora, bez cytowania kodu, który jest obok.
Dowód (plik:linia, wynik testu, SHA) zamiast trzech akapitów argumentacji. Jeśli uzasadnienie się nie
mieści, temat jest na rozmowę albo do opisu zadania, nie na komentarz. Odpowiedź na kontrargument
autora na cudzym PR-ze: do trzech zdań, ton z § 2 („Ton: asertywnie, z lekką szpilą”).

**Obrazki — tak jak reviewerzy zespołu.** Na cudzym PR-ze uwaga „magic number”, uwaga o
`getattr`/`hasattr`/`setattr` na polu o znanym kształcie i uwaga „zakomentowany kod” dostają pod
etykietą obrazek z bazy poniżej — te same obrazki, które wklejają Szymon, Maksymilian i Krzysztof,
plus memy zatwierdzone przez Sebastiana; pasują do każdego takiego miejsca, nie trzeba ich dobierać.
Raz na kategorię w PR-ze: obrazek ma pierwszy komentarz danej kategorii, kolejne idą z samą etykietą;
jeśli mój komentarz z wcześniejszego przeglądu tego PR-a ma już obrazek tej kategorii, nowe idą bez
obrazka. Wybór: jeden obrazek na kategorię w PR-ze, losowany z całej listy tej kategorii
(`shuf -i 1-<liczba obrazków kategorii> -n 1` daje numer pozycji) — całkowicie losowo: repo PR-a,
nazwa pliku obrazka ani jego pochodzenie nie dają żadnego pierwszeństwa; bierzesz dokładnie pozycję z `shuf`.
Treść komentarza dokładnie w tym formacie (nagłówek AI, pusta linia, etykieta, pusta linia, obrazek):

    🤖 Wygenerowane przez Claude

    magic number

    ![](<URL z bazy>){: data-layout='center' }

Etykieta przy getattr: „getattr na znanym polu” (albo hasattr/setattr). Obrazków nie wgrywasz i
nie pobierasz — API ich nie udostępnia (401); wstawiasz adres z bazy dosłownie.

Baza — magic number:
1. https://bitbucket.org/repo/XRpXqRq/images/3845274454-magiczn_stala_8.png
2. https://bitbucket.org/repo/5gd5K9z/images/1381464568-magiczna_stala_8_ale_inaczej.png
3. https://bitbucket.org/repo/5gd5K9z/images/620933590-co_to_takie.png
4. https://bitbucket.org/repo/rg7BxBy/images/3295406682-odpowiedz_na_magic_number.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2049183736-magic_number_nie_tak.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1119936268-magic_number_poszukiwana.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1042432934-magic_number_milion.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1762852045-magic_number_mozg.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3939382824-magic_number_motyl.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3532430828-magic_number_ulotka.png
11. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2156212152-magic_number_tlumacz.png
12. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/441269780-magic_number_przyciski.png
13. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2072902637-magic_number_kapelusz.png
14. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1349108499-magic_number_wykres.png

Baza — getattr/hasattr/setattr:
1. https://bitbucket.org/%7B%7D/%7B85ad9512-edb3-4050-86f5-f7f600c68fec%7D/images/4089451006-image.png
2. https://bitbucket.org/%7B%7D/%7B38961d0c-1ed3-447f-a3bc-fdcfa98b878e%7D/images/3784865560-image.png
3. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3631105057-getattr_nie_tak.png
4. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/281771153-getattr_czat.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/322640051-getattr_dialog.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1766004263-getattr_hasattr_klasyk.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2154651372-getattr_mozg.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2563308271-getattr_starter_pack.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/541787384-getattr_404.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3336167004-getattr_terminal.png
11. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1054861707-getattr_sprawdzian.png
12. (setattr) https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/349871427-setattr_znak.png

Baza — zakomentowany kod:
1. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1648819625-zakomentowany_nie_tak.png
2. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2978362058-zakomentowany_nagrobek.png
3. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1286192506-zakomentowany_muzeum.png
4. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3014727474-zakomentowany_starter_pack.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/120098554-zakomentowany_mozg.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/268766446-zakomentowany_osiagniecie.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2485787777-zakomentowany_bingo.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3074647051-zakomentowany_zombie.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2886674815-zakomentowany_paragon.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/4145752556-zakomentowany_roznice.png

**Brak opisu PR — na prośbę Krzysztofa.** Cudzy PR (nie draft), którego opis jest pusty, zdawkowy
(kilka słów, placeholder w rodzaju „tralalaal”, same linki) albo nie mówi, co zostało zmienione i
dlaczego, dostaje jeden komentarz ogólny (bez `inline`) — obok „opis PR niezgodny z kodem” jedyny dozwolony
komentarz ogólny na cudzym PR-ze.
Raz na PR: nie dodajesz go, gdy pod PR-em jest już taki komentarz, mój albo czyjś. Nie blokuje głosu;
wątek zamykasz po cichu, gdy opis zostanie uzupełniony. Treść dokładnie:

    🤖 Wygenerowane przez Claude

    brak opisu PR

    ![](https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2207092381-image.png){: data-layout='center' }

**Opis PR niezgodny z kodem — obrazek od Krzysztofa.** Cudzy PR (nie draft), którego opis twierdzi coś,
czego kod nie robi — opisuje zmianę, której nie ma w diffie, albo inne zachowanie, wartość, nazwę,
endpoint czy zakres niż w kodzie — dostaje jeden komentarz ogólny (bez `inline`) z tym samym obrazkiem
co „brak opisu PR”. Pod etykietą po jednej linii na każdą niezgodność: co mówi opis, co robi kod i
plik:linia — bez żądania zmian. Nie dotyczy PR-a bez opisu (wtedy tylko „brak opisu PR”) ani odstępstw
od taska, o których opis milczy (to upominajka o zakresie, § 2). Raz na PR: nie dodajesz go, gdy pod
PR-em jest już taki komentarz, mój albo czyjś. Nie blokuje głosu; wątek zamykasz po cichu, gdy opis
zostanie poprawiony albo autor odpowie, że kod jest właściwy. Treść dokładnie (nagłówek AI, pusta linia,
etykieta, pusta linia, niezgodności, pusta linia, obrazek):

    🤖 Wygenerowane przez Claude

    opis PR niezgodny z kodem

    - opis: „<co mówi opis>”; kod: <co robi kod> (<plik>:<linia>)

    ![](https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2207092381-image.png){: data-layout='center' }

Rutyna „Evening bitbucket sweep” ma kopię obu tych sekcji w prompcie — zmiana bazy idzie też do niej
(`RemoteTrigger update` z pełnym promptem, potem `get` i porównanie), tak jak blok `NAWYKI`.

**Resolve na moich PR-ach:**
- wątek `[bot]` (Jenkins/CodeRabbit) — zamykam **po** wypchnięciu poprawki albo po odpowiedzi
  odrzucającej z uzasadnieniem: `bb-sweep resolve <repo> <pr> <id>`;
- wątek człowieka — **nie zamykam nigdy**, to decyzja autora komentarza.

## 2. Cudze PR-y — wszystkie otwarte

Sekcja `review` listuje **każdy otwarty PR cudzego autorstwa, na którym nie oddałem głosu** — nie
tylko te, do których ktoś dopisał mnie jako reviewera. Brak przypisania niczego nie zmienia: robię
pełne review i głosuję tak samo. Zbiór repozytoriów bez zmian (żywe z ostatnich 120 dni plus te
z cache'u, `--deep` pyta o wszystkie).

**Bez mojego głosu (sekcja `review`)** → pełne code review robię sam: przeczytaj cały diff (`review` skill),
wystaw komentarze wyłącznie inline przy konkretnych liniach diffu (bez komentarzy ogólnych i
podsumowań; ta sama zasada długości co w punkcie 1) i **zagłosuj** — `approve` albo `request-changes`. Głos zawsze razem z
komentarzami; PR nie zostaje bez werdyktu.

Na cudzym PR-ze nie masz planu w kontekście, więc zakres bierzesz z Jiry: ID zadania stoi w tytule
(`[TICKET-1274] …`), `getJiraIssue` daje treść zadania i kryteria akceptacji. Do tego czytasz **opis PR-a**
(`description` z `GET …/pullrequests/<id>`). Kod porównujesz z jednym i drugim:

- **brak** — punkt z treści taska albo z kryteriów akceptacji, którego nie ma w kodzie;
- **nadmiar** — zmiana w kodzie, o którą task nie prosił: inne moduły, inne endpointy, podmienione
  wartości domyślne, refactor przy okazji.

**Zakres — upominajka, nie blokada.**
- Opis PR-a mówi, że ten punkt pominięto albo że to zrobiono ponad task → nie czepiasz się, żadnego
  komentarza.
- Inaczej → jedna krótka upominajka inline: przy nadmiarze przy zmianie, przy braku przy linii diffu,
  która najbliżej dotyczy brakującego punktu. Gdy takiej linii nie ma — nie komentujesz, brak idzie
  tylko do raportu.
  Co wykracza poza task albo czego brakuje, i że opis PR-a o tym nie mówi — jedna, dwie linie, bez
  żądania zmian. Przykłady: „Ta zmiana wykracza poza TICKET-1274, a opis PR-a o niej nie wspomina.”,
  „Punktu 3 z TICKET-1274 (eksport CSV) nie ma w kodzie ani w opisie PR-a.”
- Upominajka sama nie jest powodem `request-changes`; głos wynika z reszty review.
- Autor odpowiada, że to zamierzone albo że tak ma być → od razu zamykasz wątek, bez odpowiedzi.
  Nie drążysz, nie kłócisz się i nie pytasz, skąd ta decyzja.
- To dotyczy wyłącznie zakresu. Błąd w nadmiarowym kodzie dalej jest błędem i idzie przez zwykłe review.

Kod czytasz w worktree w scratchpadzie (`git fetch` gałęzi PR-a, nigdy checkout w katalogu Sebastiana),
razem z pełną listą nawyków repo: `~/.claude/bin/habits list --repo <worktree> --max-chars 200000` (bez
ucinania — sprawdź, że liczba wypisanych nawyków zgadza się z `habits list --all` po filtrze zakresu). **Bez typechecka
i bez lint-strict** — poprawność sprawdzasz, czytając kod po obu stronach diffu; wyników testów i CI
nie sprawdzasz (niżej). Mechaniczne rzeczy sprawdza za Ciebie analiza statyczna (niżej).

**Analiza statyczna — część każdego review cudzego PR-a.** Zaraz po pobraniu gałęzi uruchamiasz
bezpośrednio (nie przez verify, bo ten chowa wynik): `~/.claude/bin/bb-sweep static --repo <worktree>
--base origin/<gałąź docelowa> --json`. Zwraca kandydatów tylko na liniach, które PR dodaje, i tylko
w plikach nie-testowych: magic numbery (liczba w porównaniu bez komentarza, liczba powtórzona w pliku,
liczba w `sleep`/`delay`/`k_sleep`/`setTimeout`… bez stałej ani komentarza), zakomentowany kod,
skopiowany kod (jscpd), `getattr`/`setattr`/`hasattr`/`delattr` z nazwą w stringu, gołe i połknięte
wyjątki oraz pusty `catch`, mutowalne argumenty domyślne, porównania z None/True przez `==`,
nazewnictwo PEP 8 i nieużywane zmienne. Adnotacji typów nie sprawdza ani statyka, ani Ty.
Formatowania nie sprawdza nic — ani statyka, ani Ty. Tych kategorii **nie szukasz sam w diffie**:
bierzesz je wyłącznie z wyniku. Każdy kandydat to zwykła krótka etykieta inline („magic number”,
„zakomentowany kod”, „zduplikowany kod — jak w `X`”…), z obrazkiem tam, gdzie mówi o tym sekcja
Obrazki; kolejne linie jednego bloku zakomentowanego kodu to jeden komentarz przy pierwszej linii.
Kandydata pomijasz tylko, gdy przy tej linii jest już wątek (zamknięty albo z odpowiedzią autora) albo
gdy jest oczywiście fałszywy — wtedy jedno zdanie dlaczego w raporcie. Pliki z `not_checked` sprawdzasz
w tych kategoriach sam, czytając; tak samo cały PR, gdy polecenie w ogóle się nie uruchomi — i piszesz
to w raporcie. Twoje zostaje wszystko, czego narzędzie nie oceni: magic stringi,
duplikacja istniejącego helpera, architektura, surowy dict, nazwy, które kłamią, `Any`/`cast`/kłamiące
adnotacje, ścieżki błędu kończące się sukcesem, prawdziwe błędy i nawyki zespołu (w tym `getattr` na
znanym polu, gdy nazwa nie jest stringiem).

**Testów nie oceniasz stylistycznie.** W plikach testowych żadnych uwag o czystości kodu, nazwach,
magic numberach, duplikacji czy uproszczeniach — tylko realne błędy (test, który nic nie sprawdza,
sprawdza nie to, co trzeba, albo przechodzi niezależnie od kodu).

**Czysty kod i normy — tylko to, co ważne.** Nie punktujesz formatowania, długości linii, kolejności
importów, docstringów, stylu cudzysłowów czy przecinków ani braku adnotacji typów. Punktujesz:
- **błędne typy** — `Any`/`object` tam, gdzie typ jest znany, adnotacja, która kłamie,
  `cast`/`as`/`type: ignore` zamiast poprawnego typu;
- **architekturę i strukturę dodanego kodu** — niespójność z tym, jak repo już to robi (warstwy, np.
  logika biznesowa w endpoincie czy komponencie zamiast w serwisie lub hooku; wzorce i konwencje repo;
  rozmieszczenie plików i modułów; nazewnictwo modułów), nowa abstrakcja równoległa do istniejącej,
  zależności w złą stronę;
- **uproszczenia** — kod, który da się wyraźnie skrócić, uprościć albo lepiej ustrukturyzować: zbędne
  warstwy pośrednie i wrappery, powtórzone bloki do wydzielenia, zagnieżdżenia do spłaszczenia (early
  return), ręczna pętla zamiast idiomu języka, funkcja lub komponent do podziału. Podajesz, na co zmienić,
  w jednym zdaniu;
- oraz to, co realnie szkodzi: magic numbery i powtórzone literały zamiast nazwanej stałej; zduplikowaną logikę tam,
gdzie w repo jest już helper; surowy dict tam, gdzie kształt danych jest znany (dataclass, model, enum);
połknięte wyjątki, gołe except i ścieżki błędu kończące się sukcesem; nazwy, które kłamią; funkcje robiące
kilka rzeczy naraz; martwy i zakomentowany kod; mutowalne argumenty domyślne. Z PEP 8 tylko nazewnictwo
(snake_case dla funkcji i zmiennych, PascalCase dla klas, UPPER_CASE dla stałych) i porównania z None
przez is.

**Co blokuje i co zamyka wątek.** Głos `request-changes`, dopóki jest otwarty choć jeden mój wątek-bloker;
otwarte wątki nieblokujące nie wstrzymują `approve`. Rodzaj uwagi decyduje, co ją zamyka:

| Rodzaj uwagi | Blokuje? | Co zamyka wątek |
|---|---|---|
| Logika, architektura, możliwy błąd, edge case — coś się psuje (zła wartość, utrata danych, wyjątek, regresja względem develop, dziura w walidacji) | tak | fix albo argument autora, który **sam sprawdziłeś w kodzie** i który się obronił. „Tak ma być”, „zamierzone”, „działa od lat”, „jest dobrze”, mem — NIE zamykają |
| Zmiana zachowania, którą autor **potwierdza komentarzem** jako zamierzoną (decyzja produktowa albo kontraktowa, nie błąd) | tak | to potwierdzenie autora — cichy resolve. Nie dotyczy uwagi z wiersza wyżej: odpowiedź „zamierzone” na pokazany błąd nie czyni go decyzją |
| Styl i czysty kod — każda waga (normy, nawyki stylistyczne, błędne typy, nazwy, magic numbery i stringi, duplikacja, martwy i zakomentowany kod, surowy dict, połknięte wyjątki) | tak | wyłącznie fix albo merytoryczny argument, który sprawdziłeś w kodzie (np. „taka konwencja w projekcie” → grep, czy ta konwencja w repo naprawdę istnieje). „Tak ma być”, „jest dobrze”, „lepiej żeby została”, „nie trzeba”, mem — NIE zamykają |
| Liczba w `sleep`/`delay_ms`/`k_sleep`/`setTimeout`… bez stałej ani komentarza „dlaczego” | tak | fix: stała albo komentarz wyjaśniający |
| Zakres: odstępstwo od opisu PR-a albo treści taska (upominajka) | nie | fix albo komentarz autora potwierdzający odstępstwo — to wystarcza |
| Opis PR-a niezgodny z kodem (komentarz ogólny z obrazkiem) | nie | poprawiony opis albo odpowiedź autora, że kod jest właściwy |

Przepuszczasz na słowo autora **tylko dwie rzeczy**: odstępstwo od opisu PR-a albo taska i zamierzoną
zmianę zachowania — obie potwierdzone komentarzem autora. Syfiastego kodu nie przepuszczasz: błąd i styl
zamyka wyłącznie poprawka albo argument, który przeszedł Twoją weryfikację w kodzie.

**Waga stylu jest wewnętrzna.** Każdej uwadze stylistycznej przypisujesz w myślach low / medium / high /
critical — po tym, jak bardzo razi i ile realnie szkodzi (np. magic number w progu biznesowym czy
połknięty wyjątek na ścieżce płatności → high; `Any` tam, gdzie typ jest znany, `cast`, kłamiąca
adnotacja → low). Waga nie decyduje o blokowaniu — blokuje każda uwaga stylu; służy tylko do raportu.
Wagi **nigdy nie publikujesz** — ani w komentarzu, ani w odpowiedzi; trafia tylko do mojego raportu
przy tym wątku.

**Wyniki testów — poza review.** Na cudzych PR-ach nie sprawdzasz, czy testy (także nowo dodane)
przechodzą: nie czytasz statusów CI, nie uruchamiasz testów ani na gałęzi PR-a, ani na docelowej, i nie
zostawiasz o tym uwag ani blokerów — o to się w PR-ach nie czepiamy. Przy poprawkach na moich PR-ach
testów nie uruchamiasz, chyba że poprawka zmienia logikę — wtedy tylko testy zmienionego modułu.

**Nawyki zespołu.** Reguły z `habits list` wzięły się z uwag reviewerów na moich PR-ach — to konwencje
tego zespołu i repo. Złamanie nawyku na cudzym PR-ze to zwykła uwaga inline: etykieta mówiąca, co jest nie tak (np.
„enumy do models.py”), bez numeru nawyku — w komentarzach nie ma żadnych H0xx. Przejście nawyków
jest obowiązkowe przy KAŻDYM review, także szybkim (krok 5 metody niżej). Złamany nawyk traktujesz jak
uwagę jego rodzaju z tabeli „Co blokuje i co zamyka wątek”: nawyk o logice lub architekturze — jak błąd,
nawyk stylistyczny — jak styl (blokuje). Nawyków o braku adnotacji typów (np. H004) na cudzych
PR-ach nie stosujesz, a w plikach testowych nie stosujesz nawyków stylistycznych.

**Metoda review cudzego PR-a** — to ona odróżnia review od przejrzenia diffu:

1. **Kontekst ticketu, nie tylko diffu.** Gdy PR realizuje kawałek większego ticketu, oceniasz te
   wymagania, których ten kawałek dotyczy. `git log origin/develop --grep <ID>` pokazuje, co
   wcześniejsze PR-y tego ticketu już dowiozły, żeby nie żądać rzeczy zrobionych.
2. **Kod po obu stronach diffu.** Czytasz kod, który produkuje wejście PR-a, i ten, który konsumuje jego
   wyjście (worker, kontrakt, konfiguracja). Najcięższe błędy siedzą na styku: flaga ustawiona na
   sztywno u producenta, limit ponowień u konsumenta.
3. **Semantyka narzędzi z pierwszej ręki.** Gdy uwaga zależy od zachowania zewnętrznego narzędzia,
   biblioteki albo protokołu, którego nie da się tu uruchomić, sprawdzasz je w źródle albo oficjalnej
   dokumentacji i cytujesz plik:linia albo link — nigdy z pamięci. Czego nie sprawdziłeś, nie
   publikujesz jako faktu.
4. **Czy testy łapią tę klasę błędów.** Gdy testy tylko mockują zależność i sprawdzają listy
   argumentów, a błąd leży w semantyce tej zależności, piszesz to wprost i proponujesz jeden test na
   prawdziwej zależności.
5. **Wszystkie nawyki, jeden po drugim.** Bierzesz pełną listę z `habits list --repo <worktree>` (global,
   języki repo, `repo:acme/<repo>`) i dla KAŻDEGO nawyku decydujesz na diffie: nie dotyczy / OK /
   złamany (plik:linia). Nawyki o kategoriach analizy statycznej (magic numbery)
   rozstrzygasz z jej wyniku, nie czytając diffu drugi raz. Złamany → uwaga inline bez numeru nawyku. W raporcie per PR: „nawyki: N
   sprawdzonych, złamane: H0xx (plik:linia), …”. Review bez tego kroku nie jest skończone — nie
   głosujesz, dopóki go nie zrobisz.

**Zestaw komentarzy:** wyłącznie inline przy dokładnej linii — każdy problem, upominajka o zakresie i
pytanie do autora (§ 3) osobno, jedno na wątek. Żadnego komentarza ogólnego (obraz, wdrożenie, testy
też idą inline przy linii, której dotyczą, albo tylko do raportu) i żadnego podsumowania — poza
„brak opisu PR” z sekcji Obrazki.
**Objaśnienie po ludzku:** gdy autor prosi o wyjaśnienie zadania albo blokery wynikają z niezrozumienia
mechanizmu, na którym zadanie stoi, objaśnienie (po co jest zadanie, jak ma działać, na czym polega
główny problem) idzie inline przy linii z głównym problemem. Tylko ono nie podlega limitowi długości.

**Odpowiedzi na moje komentarze (sekcja `replies`)** → przeczytaj i oceń według tabeli „Co blokuje i co
zamyka wątek”. **Resolve jest cichy:** gdy wątek się zamyka, dajesz tylko `bb-sweep resolve <repo> <pr>
<id>` — bez odpowiedzi, potwierdzenia ani gratulacji; nie zaśmiecasz PR-a.
- poprawione — sprawdzone w kodzie, nie na słowo („Done” to nie dowód) → cichy resolve; jeśli głos
  wisiał tylko na blokerach, które właśnie zamknąłeś — zmieniasz go na `approve`;
- autor potwierdza komentarzem odstępstwo od opisu PR-a albo taska, albo zamierzoną zmianę zachowania
  (decyzję, nie błąd) → cichy resolve. Tu nie drążysz źródła decyzji;
- autor kontrargumentuje (błąd, logika, styl) → **zanim odpiszesz, sprawdzasz jego argument w kodzie**:
  zachowanie na `develop` (`git show origin/develop:<plik>`), historia (`git log`, `git show <sha>`),
  źródło biblioteki, grep po repo przy „taka jest konwencja”. Argument się obronił → jedno zdanie
  „Racja — <dowód plik:linia albo commit>” i resolve. Przyznanie racji jest obowiązkowe — nie trzymasz
  wątku dla zasady i nie publikujesz uwagi, której dowód właśnie upadł. Nie obronił się → odpowiedź
  z dowodem (plik:linia, commit, porównanie z develop), wątek zostaje otwarty, głos `request-changes`;
- odpowiedź bez argumentu na błąd albo styl („tak ma być”, „jest dobrze”, „lepiej żeby została”,
  „nie trzeba”, „działa od lat”, sam obrazek) → wątek NIE zamyka się. Odpisujesz: dlaczego to nie
  argument, dowód z kodu i czego oczekujesz (konkretny powód albo poprawka) — do trzech zdań;
- autor twierdzi, że poprawił, a w kodzie tego nie ma → jedno krótkie zdanie, gdzie tego brakuje
  (plik:linia), wątek zostaje otwarty.

**Ton: asertywnie, z lekką szpilą.** Nie odpuszczasz i nie mięknie Ci głos po drugiej odmowie autora —
o zamknięciu decyduje dowód, nie liczba rund. Wolno być troszkę dogryźliwym: krótkie, celne otwarcie
w rodzaju „„Dobrze” według czego?”, „Obrazek to nie uzasadnienie.”, „„Lepiej żeby została” to nie
argument.”, „„Done” — a w `plik:linia` dalej jest …”. Szpila zawsze stoi obok dowodu i zawsze dotyczy
kodu albo argumentu, nigdy osoby: bez ironii o kompetencjach, bez wykrzykników, bez wielkich liter.
Szpila bez dowodu to złośliwość — takiej nie publikujesz. Tak samo rzeczowo przyznajesz rację, gdy
dowód jest po stronie autora.

**Odpowiedzi zbiorcze i odpowiedzi poza moimi wątkami.** PR, na którym oddałem głos, wymaga przejrzenia,
gdy po moim ostatnim wpisie pojawił się jakikolwiek komentarz autora albo nowy commit — niezależnie od
tego, w którym wątku. Autor nie zawsze odpisuje pod każdą uwagą: czasem pisze jeden komentarz główny
(„poprawki w commicie X: …”) albo odpowiada w innym wątku. Dlatego na każdym cudzym PR-ze z moim głosem
czytasz WSZYSTKIE komentarze dodane po moim ostatnim wpisie — nowe wątki główne, odpowiedzi w cudzych
wątkach, wzmianki o mnie — i porównujesz `source.commit.hash` z commitem, na którym robiłem review; nowy
commit bez komentarza to też sygnał do sprawdzenia moich uwag. Sekcja `replies` z `bb-sweep` pokazuje
tylko wątki, w których się wypowiedziałem, więc tego sama nie złapie — nie traktuj jej pustki jako
„nic nie czeka”.
- Komentarz zbiorczy rozbierasz na punkty i przypisujesz każdy do mojego wątku. Każdy wątek obsługujesz
  tak, jakby autor odpisał w nim: sprawdzasz w kodzie i robisz cichy resolve albo jednym zdaniem W TYM
  wątku wskazujesz, czego brakuje.
- Punkty zbiorczego komentarza, które nie odpowiadają żadnej mojej uwadze (nowe zmiany, obejścia moich
  decyzji z opisu PR-a), oceniasz jak zwykłą zmianę w kodzie.
- Moja uwaga, której nie ma ani w komentarzu zbiorczym, ani w kodzie, zostaje otwarta — bez
  odpowiedzi pod komentarzem zbiorczym; trafia tylko do raportu.

Zamykam wyłącznie wątki, które sam założyłem — cudzych na cudzym PR-ze nie ruszam. Mojego wątku
zamkniętego przez kogoś innego nie otwieram ponownie i nie komentuję.
Zerkam w uwagi innych reviewerów i sprawdzam czy autor naprawił to co oni zgłosili. Jak nie to komentarz możesz dać.
Jak reviewer się myli i daje niesłuszną uwagę, komentuję, że nie powinno się tak robić i pierwotna intencja autora była poprawna.
Przy zadaniach z Jiry sprawdzam task i epic, czy zmiana idzie zgodnie z planem. 

**Wszystkie moje wątki zamknięte (sekcja `approve`)** → zmień głos na `approve`. Ta sekcja listuje
dokładnie te PR-y: mój głos to `changes_requested`, a żaden mój wątek nie jest już otwarty. Głos zmieniasz
na `approve` także wtedy, gdy otwarte zostały tylko moje wątki nieblokujące (upominajka o zakresie, opis
PR-a niezgodny z kodem) — tych sekcja `approve` nie pokaże, więc sprawdzasz to sam przy obsłudze
`replies`. Otwarty wątek o stylu blokuje, niezależnie od wagi.

## 3. Decyzje — pyta się autora

Decyzje i zmiany architektoniczne rozstrzyga **autor PR-a**. Pytasz go wprost w wątku. Sam zakres
(nadmiar i braki względem taska) tu nie należy — to upominajka z § 2, zamykana, gdy autor powie, że
to zamierzone. Nikogo nie oznaczasz: autor dostaje powiadomienie o każdym komentarzu na swoim PR-ze.

Pytasz autora, gdy:

- uwaga jest trafna, ale poprawka to **realnie duża zmiana**: rusza kontrakt (API, format danych,
  schemat bazy, migracja), wymaga przeprojektowania przepływu albo zmian w kilku modułach czy
  repozytoriach, albo zmienia zachowanie widoczne dla użytkownika lub innej usługi — pytanie brzmi:
  naprawiamy teraz czy zakładamy osobne zadanie;
- w obrębie zakresu taska zapada decyzja produktowa albo kontraktowa (zmiana API, formatu danych,
  polityki), której ticket nie rozstrzyga.

**Próg.** Liczba linii nie czyni zmiany dużą — liczy się, czy zmienia zachowanie albo kontrakt.
Mechaniczny refaktor wewnątrz PR-a (raw dict → Pydantic albo dataclass, magic number → nazwana stała,
wydzielenie funkcji, nazwy, typy, brakujący test) to zwykła uwaga w review: piszesz ją autorowi albo
poprawiasz sam, nawet gdy dotyka kilkunastu miejsc. Autora pytasz o decyzję, nie o pracę.

Forma: jedno, dwa zdania — na czym polega problem i opcje do wyboru. Jedno pytanie na wątek, po polsku.
Gdy autor odpowie, że tak zostaje, zamykasz wątek bez dalszych pytań — to dotyczy pytań o decyzję
(naprawiamy teraz czy osobny ticket, wybór produktowy albo kontraktowy). Gdy w wątku jest pokazany błąd,
„tak zostaje” go nie zamyka: działa tabela i zasady odpowiedzi z § 2.

Wątek z pytaniem do autora **zostaje otwarty** do jego odpowiedzi: nie zamykasz go i nie liczysz jako
domkniętego. Gdy pytanie dotyczy realnego błędu, głos na tym PR-ze to `request-changes` do czasu
rozstrzygnięcia; gdy chodzi wyłącznie o zakres (osobny ticket), możesz zagłosować `approve` i zostawić
wątek z pytaniem otwarty.

**Na moich PR-ach autorem jestem ja.** Takiej decyzji nie rozstrzygasz i nie pytasz o nią nikogo w
wątku — zostawiasz ją mnie i wypisujesz w raporcie: repo, PR, link do wątku, czego dotyczy decyzja.

Każde pytanie do autora ląduje w raporcie: repo, PR, link do wątku, o co zapytałeś.

## 4. Techniczne

REST API v2.0, poświadczenia z `~/.config/bitbucket/credentials`. Puste POST-y (`/approve`,
`/request-changes`, `/comments/<id>/resolve`) muszą iść **bez** `Content-Type`. Listing komentarzy
nie zwraca `resolution` — pojedynczy GET po komentarzu. Gdy mój checkout repozytorium stoi na innej
gałęzi albo ma niezacommitowaną pracę, poprawki robię w worktree w scratchpadzie, nigdy przez
checkout w katalogu Sebastiana. Commit: jedno zdanie w trybie rozkazującym, max 7 słów, bez `-s` i bez żadnych trailerów (Signed-off-by, Co-Authored-By).

## 5. Raport

Jeden status wg skilla `review` plus: co naprawione (SHA + gałąź), co odrzucone i dlaczego, gdzie
i jak zagłosowałem, co zamknięte, na co czekam od ludzi, co pominięte jako draft, o jakie decyzje poza
ticketem zapytałem autorów (repo, PR, link do wątku), jakie upominajki o zakresie zostawiłem i które
zamknąłem po odpowiedzi „zamierzone”, przy każdej uwadze stylistycznej jej wewnętrzna waga
(low/medium/high/critical), które kontrargumenty autorów zweryfikowałem w kodzie i z jakim wynikiem
(obronił się → „Racja” i resolve, z dowodem; nie obronił się → moja odpowiedź z dowodem, wątek otwarty), jakie decyzje na moich PR-ach czekają na mnie, oraz nowe i podbite
nawyki (id, reguła, źródło) —
żebym mógł któryś odrzucić przez `habits drop <id>`.
