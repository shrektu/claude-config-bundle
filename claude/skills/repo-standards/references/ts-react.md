# TypeScript / JavaScript / React idioms

| Stack | Current | Legacy — reject |
|---|---|---|
| TypeScript | `unknown` + narrowing | `as` casts to force a shape, `any`, enums where a union literal fits |
| Vite 7/8 | `defineConfig`, ESM config, `import.meta.env` | CJS config, `process.env` in client code, webpack-era plugins |
| Vitest | `vi.fn`/`vi.mock`/`vi.useFakeTimers`, `expect` from `vitest` | `jest.fn`/`jest.mock`, global jest APIs, `@types/jest` |
| Playwright | `page.getByRole`/`getByLabel`/`getByTestId`, web-first assertions, auto-waiting | CSS/XPath selectors, `waitForTimeout`, manual sleeps |

By the tsconfig `lib`, TypeScript and Node floors:

| Floor | Use | Instead of |
|---|---|---|
| lib ES2022 | `a.at(-1)`, `Object.hasOwn(o, k)`, `structuredClone(o)` | `a[a.length - 1]`, `hasOwnProperty`, `JSON.parse(JSON.stringify(o))` |
| lib ES2023 | `toSorted`/`toReversed`/`toSpliced`/`with`, `findLast`/`findLastIndex` | `[...a].sort()`, `slice().reverse()`, `reverse().find()` |
| lib ES2024 (Node 22) | `Object.groupBy`/`Map.groupBy`, `Promise.withResolvers()` | reduce into an object, `new Promise` with captured resolvers |
| lib ES2025 (Node 24 for `Promise.try`/`RegExp.escape`) | Set `union`/`intersection`/`difference`, iterator helpers `.filter().take().toArray()`, `Promise.try`, `RegExp.escape`, `import x from './a.json' with { type: 'json' }` | spread-into-Set, `Array.from(it)` chains, hand-rolled regex escaping, `assert {}` |
| lib esnext + Node 24/26, backend only | `Array.fromAsync`, `Error.isError`, `Uint8Array#toBase64`; `using`/`await using` and Temporal (ES2027, no Safari — never in frontend) | `for await` + push, `instanceof Error`, `Buffer` base64, `try/finally` disposal, `Date` |
| TS 5.0–5.5 | `satisfies`, `<const T>`, `NoInfer<T>`, inferred predicates `xs.filter(x => x !== undefined)` without a cast, `import { type X }` under `verbatimModuleSyntax` | `as` shapes, `as const` at call sites, `(x): x is T =>` + cast |
| TS 5.8 `erasableSyntaxOnly`, or Node type stripping | `const E = { A: 'a' } as const; type E = (typeof E)[keyof typeof E]`; explicit fields | `enum`, runtime `namespace`, constructor parameter properties |
| TS 6.0 / 7.0 | `#/` subpath imports or `paths`; `moduleResolution bundler` for apps, `nodenext` for Node; `types: ["node"]` explicit; under TS 7, type-aware ESLint via the `@typescript/typescript6` alias | `baseUrl`, `node10`, implicit `@types/*`, `target es5`, `asserts` on imports |
| Node 22+ | `import.meta.dirname`, `process.loadEnvFile()` / `--env-file`, global `fetch`, `node:test`, `node app.ts` (type stripping) | `fileURLToPath(import.meta.url)`, dotenv, node-fetch, ts-node |

By the `react` floor:

| Floor | Use | Instead of |
|---|---|---|
| 19.0 | default params; `ref` as a prop; `<Ctx value={v}>`; `use(Ctx)`; `useActionState`/`useOptimistic`/async `startTransition` for async submit state; `<form action={fn}>` + `useFormStatus` for plain forms; `<title>`/`<meta>` rendered in the tree; ref callbacks returning cleanup | `defaultProps`, `forwardRef`, `<Ctx.Provider>`, hand-rolled `isPending`/`error` state, `useFormState`, `document.title` in an effect, react-helmet |
| 19.2 | `useEffectEvent` for event-like logic fired from an effect (never passed as a prop); `<Activity mode>` to keep hidden UI state | callbacks in effect deps, latest-ref hacks, `eslint-disable exhaustive-deps`, `{open && <Page/>}` when state must survive |
| 19.3 | `<ViewTransition>` + `addTransitionType`; `<Fragment ref>` | `document.startViewTransition` + `flushSync`, wrapper `<div ref>` |
| `babel-plugin-react-compiler` 1.0 wired in the vite config | plain components in new code, without `useMemo`/`useCallback`/`memo` for performance; keep the existing ones (removal can change effect timing) | new manual memoization |
| eslint-plugin-react-hooks ≥ 7 | `flat.recommended` (compiler rules: `set-state-in-effect`, `refs`, `purity`, `immutability`, `static-components`…) | the deprecated `eslint-plugin-react-compiler`, 6.x presets |

With react-hook-form keep `handleSubmit` (it has no `<form action>` integration); prefer `useWatch`/`<Controller>` to `watch()`.
