# How to come up with hard scenarios

A hard scenario is not "weird data" but a named mechanism that can break. You start from the change map:
every changed condition, query, validator, mapping and screen is a place where you look for a boundary
value. The catalogue below is a list of questions, not a checklist — you take those that hit the diff,
and for each you write down the `file:line` you aim at.

## Known defect classes of this project — check first

From the memory `reports-epic-progress` (read it, the list grows):

- **validation order in marshmallow** — a field is cast, rounded or quantized *before* the validator: a
  value that fits the limit after rounding but not before (and the other way round);
- **marshmallow drops undeclared fields** — a new field added only in the builder does not reach the API:
  send it and check that it was saved in the database;
- **an inner join on a nullable FK loses rows** — an object without the relation (no location, operator,
  product) must appear in the list, in the total and in the export;
- **SQLite hides PostgreSQL** — case-sensitive comparisons, sorting with NULL, date and time-zone types,
  `DISTINCT ON`, integer division: a scenario on a real Postgres in the QA stack;
- **a fixture replaces the harness under test** — which is why QA goes through the real stack, not
  through mocks;
- **slot expiry is a flag, not a filter** (`storage-expiry-flag-not-filter`) — expired objects must be
  marked, and filtered out only where the ticket says so.

## Time and time zones

The time-zone epic (`timezone-epic-*`) showed that this is where it breaks most often:

- location zone ≠ browser zone ≠ UTC — set a different zone in Playwright (`timezoneId`) than the
  location's zone in the data;
- an event at 23:30 and 00:30 local time — on which report day does it land;
- the daylight-saving change day (the last Sunday of March and October): a 23- and a 25-hour day, an hour
  that does not exist or occurs twice;
- end of month, end of year, 29 February; a one-day range, start = end, start > end;
- promotions and schedules: a start exactly "now", an end in the past, a range across midnight.

## Value boundaries

- 0, 1, the maximum, the maximum + 1, negative values, fractions; comma vs dot in a numeric field;
- amounts: grosze, rounding of totals vs the total of roundings, very large amounts, currency;
- text: empty, only spaces, very long, Polish characters, emoji, HTML characters (`<b>`), a quote mark;
- lists: empty, one element, exactly one page, a page + 1, the last page.

## Object state

- archived, expired, soft-deleted, disabled, just created, without relations;
- an object related to many others — duplicates in joins, double counting in totals;
- an aggregate without data: 0, no row or `null` — and what the UI shows in each of these cases;
- migration: existing rows with `NULL` in the new column, data from before the format change.

## Permissions and scope

- a user with a different role, operator vs admin, a user without assignments;
- an object of another location or operator — swap the ID in the URL and in the request body (IDOR);
- a button hidden in the UI, but the endpoint called directly through `request`.

## Order, concurrency, navigation

- a double click on "Save", two parallel requests of the same write (`Promise.all` on `request`);
- two tabs editing the same object — who wins and whether the second sees a conflict;
- a page refresh midway, "back" after a save, entering a deep URL directly;
- repeating a request after a network error — whether the operation is idempotent;
- changing a filter on the second page of results — whether pagination returns to the first.

## Errors and validation

- a missing required field, a wrong type, a field outside the schema;
- a 500 response or a timeout from a dependent service (`page.route` with
  `route.fulfill({ status: 500 })`) — whether the UI shows an error and whether the form keeps the typed
  data;
- the error message visible to the user is in Polish, not a raw i18n key or a stack trace.

## UI

- filter + sorting + pagination at once; sorting with equal values (stability);
- the empty state, the loading state, very long values in a table;
- a missing translation visible as a raw key; switching the language;
- the displayed value vs the one stored in the database (rounding, zone, date format).

## Machine side

- an old NATS message format from a machine with older firmware — backward compatibility;
- a machine offline, a duplicated message, messages in reverse order;
- no response within the timeout, and a retry.
