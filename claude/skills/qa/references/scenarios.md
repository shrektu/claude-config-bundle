# Hard scenario catalogue

Questions, not a checklist: take those that hit a changed condition, query, validator, mapping or screen
from the change map.

## Known defect classes: check first

- **marshmallow validation order**: a field cast, rounded or quantized *before* the validator; a value
  inside the limit after rounding but not before (and vice versa);
- **marshmallow drops undeclared fields**: a field added only in the builder never reaches the API; send
  it, check the DB;
- **inner join on a nullable FK loses rows**: an object without the relation (location, operator,
  product) must appear in the list, the total and the export;
- **SQLite hides PostgreSQL**: case-sensitive comparison, NULL sorting, date and zone types,
  `DISTINCT ON`, integer division; test on the QA stack's Postgres;
- **slot expiry is a flag, not a filter**: expired objects are marked, filtered out only where the ticket
  says;
- **an empty scope is not a refusal**: an empty organisation or location list passed to the permission
  helper must refuse everyone, system admins included;
- **effect deps on identities**: a function or array prop in a `useEffect` dep list resets state on every
  parent render (pagination jumps back to page one).

## Time and time zones: the most frequent breakage

- location zone ≠ browser zone ≠ UTC: Playwright `timezoneId` different from the location's zone;
- events at 23:30 and 00:30 local time: which report day;
- DST change days (last Sunday of March and October): 23- and 25-hour days, a missing or doubled hour;
- month end, year end, 29 February; a one-day range, start = end, start > end;
- promotions and schedules: start exactly "now", end in the past, a range across midnight.

## Value boundaries

- 0, 1, max, max + 1, negative, fractions; comma vs dot in numeric fields;
- amounts: grosze, rounding of totals vs total of roundings, very large, currency;
- text: empty, spaces only, very long, Polish characters, emoji, HTML (`<b>`), a quote mark;
- lists: empty, one element, exactly one page, a page + 1, the last page.

## Object state

- archived, expired, soft-deleted, disabled, just created, without relations;
- related to many others: join duplicates, double counting in totals;
- an aggregate without data (0, no row, `null`) and what the UI shows for each;
- migration: existing rows with `NULL` in the new column, data from before a format change.

## Permissions and scope

- another role, operator vs admin, a user without assignments;
- another location's or operator's object: swap the ID in the URL and the body (IDOR);
- a button hidden in the UI, its endpoint called directly through `request`.

## Order, concurrency, navigation

- a double click on "Save", two parallel identical writes (`Promise.all` on `request`);
- two tabs editing one object: who wins, does the second see a conflict;
- a refresh midway, "back" after a save, a deep URL entered directly;
- a retry after a network error: is the operation idempotent;
- a filter change on page two: does pagination return to page one.

## Errors and validation

- a missing required field, a wrong type, a field outside the schema;
- an API call answering 500 or hanging (`page.route` → `route.fulfill({ status: 500 })`, or never
  fulfil): the UI shows an error and the form keeps the typed data; a backend dependency down
  (`qa stop <service>`);
- the user-visible error is in Polish, not a stack trace.

## UI

- filter + sort + pagination together; sorting equal values (stability);
- the empty state, the loading state, very long values in a table;
- a missing translation shown as a raw key; switching the language;
- the displayed value vs the stored one (rounding, zone, date format).

## Machine side

- an old NATS message format from older firmware (backward compatibility);
- a machine offline, a duplicated message, messages in reverse order;
- no response within the timeout, and the retry.
