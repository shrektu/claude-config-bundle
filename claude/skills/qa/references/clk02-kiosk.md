# kiosk-ui kiosk for QA

- Branches before TICKET-1523 (WireMock kiosk, `runs/TICKET-1352/`): ask Sebastian.
- Kiosk against a real controller (`runs/TICKET-1347/kiosk_walk.mjs`, built on WireMock): rebuild it on
  `--mode mock` and verify before use.
- Ports 5000/6008/1234 may belong to other people's stacks (sm-gateway, mock_launcher): never touch them.

## vite `--mode mock` (verified 2026-10-09 on TICKET-1520)

No WireMock, NATS, cloud or login: MSW and a fake NATS run in the browser, vite only serves them. Control:
`docs/MockMode.md` in the worktree (`?mock=…`, `/__mock/*`).

1. QA worktree (SKILL §2) with dependencies (`bun install` or copied node_modules); build only there.
2. Server: a copy of `runs/TICKET-1520/start-dev.sh` in `runs/<ID>/` (worktree path adjusted; port 5176), PID
   to a file, `kill` at the end. Playwright config: `webServer` = that script with
   `reuseExistingServer: true`, `baseURL http://localhost:5176`, viewport 1080x1920, `workers: 1`,
   `timeout` ~75 s, testDir = the run dir (`testMatch *.spec.ts`), `launchOptions` as in SKILL §7.
3. Playwright from `~/.cache/claude-qa` (1.56.1). One page = one mock state (`/__mock/*` acts on the OPEN
   kiosk page): never two runs at once, no exploratory script during specs. A new context = a fresh
   sessionStorage.
4. Start: `page.goto("/?mock=speed:0")`, then
   `page.request.post("/__mock/scenario" | "/__mock/catalogue" | "/__mock/patch-config", {data})`
   (relative URL only with `baseURL`; full URL in a node script). `window.__kioskMockInit` in
   `addInitScript` sets the dataset and overrides before start (e.g. `ui.languages: ["pl"]` for `sorting`,
   which starts in English).
5. The menu loads only on Start (prefetch) and on entering Categories/Products. A catalogue edit
   (`slots.B1.q`, `err`, `inactive`, `p:null`, `products.<id>.promotion`) shows after such a load: cart →
   "Wróć" → `waitForResponse(/product-menu/)` → "Twój koszyk". Slot id = row*row_length+column+1; the edit
   key is the grid position (A1…), not the slot name.
6. `transactions/start`: `page.on("request")` sees the POST despite MSW (`postData()` JSON). Clock:
   `page.clock.install()` before `goto`, then `setSystemTime`/`fastForward` (60 s cart retention, slot
   expiry).
7. Skipping a screen: `history.pushState({}, "", "/card-payment"); dispatchEvent(new PopStateEvent("popstate"))`.
   Reservations: `patch-config {"reservation.enabled": true}` on the `default` dataset (`click-collect`
   has no purchases); `POST /__mock/scan {code}` only after "Zeskanuj kod rezerwacji" shows (else it is
   lost). `claimItems:2` blocks two slots.
8. Pitfalls: the default 5-piece cart limit opens "Limit osiągnięty" at the fifth piece (set
   `ui.shopping_cart_limit`); after a full dispense failure /reject has only "Zakończ" (no "Spróbuj
   ponownie"); a dispense without events (`no_events`) is just a loader; the card screen shows no amount;
   the dispense route is `/dispense`.
