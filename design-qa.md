# Compact ledger implementation QA — 2026-09-28

final result: passed

## Scope and evidence

Author/reviewer: Codex (implementation self-review, not independent QA). User selected the first image in this round. Applied Product Design image-to-code and design-qa skills to the existing functional M1 app, not a newly scaffolded prototype.

- Source visual truth: `design/compact-ledger-selected.png` (1487 × 1058).
- Local implementation: http://127.0.0.1:4180/app/data.
- Screenshot directory: `docs/verification/compact-ledger-20260928/`.
- Matched source comparison: `inventory-initial.png` then `inventory-desktop.png`, both 1487 × 1058 raster and CSS viewport, light theme, inventory first page, no drawer, 10 rows. Source and implementation were opened together in each comparison tool input. No density resampling was required.
- Source account name and last two generated material rows intentionally differ: authenticated test account and current database values take precedence. No database changes made.
- Full-view comparisons were readable at native dimensions; header, first-column alignment, row typography, state markers and pagination were inspected within these images. Separate image crops were not necessary.

## Findings and comparison history

1. Initial comparison — blocked: [P2, spacing] Ant Design middle-table specificity overrode the intended first-column padding (16px rather than 24px). Fixed shared selector specificity, not individual page margins. [P2, typography/density] 14px body and 40px controls were smaller than selected direction. Updated theme to 16px body / 48px controls, title 28px and row metadata 13px; warning pills became dot-plus-text.
2. Second matched comparison — `inventory-desktop.png`: earlier findings resolved. Shared first header/cell and toolbar padding measured 24px; table starts at y=196 vs approximately y=200 in source, accepted minor optical difference. Ten-row density, light sidebar and uninterrupted table surface match chosen direction.
3. Cross-page review — [P2, wrapping] `knowledge-desktop.png` showed dates wrapping. Widened date column to 140px and applied existing numeric/nowrap utility. `knowledge-desktop-fixed.png` and browser computed styles confirm dates stay on one line.
4. Narrow-screen interaction review — [P2, spacing] `new-check-mobile.png` showed textarea counter colliding with form help. Added 24px bottom margin to the shared drawer textarea-count wrapper. `new-check-mobile-fixed.png` confirms separation: textarea bottom 473.09, help starts 497.09 CSS px. Drawer scrolls vertically; no off-screen horizontal controls.

## Required fidelity surfaces

- Typography: existing PingFang SC / Microsoft YaHei / system fallback retained; regular tabular numbers, medium-weight item names, semibold headings. Chinese glyphs render cleanly; no missing-font substitutions. Source generated typography is approximated with real system fonts, not treated as a downloadable font asset. Date wrapping and helper overlap fixed.
- Spacing/layout: 235px desktop sidebar, compact header, 24px unified table/toolbar/pagination edges; mobile uses 16px. Removed separate breadcrumb/status strip and repeated introductory hero. Metadata connection indicators retained in footer. No duplicated per-page table padding rules in live app.
- Colors/tokens: retained readable blue action, pale blue selection, cool-white sidebar, restrained horizontal rules, green complete/amber attention states. Color is supplemented by text, not the only status signal. No decorative gradients introduced.
- Image quality/assets/icons: no photographic or illustrative assets required. Existing Tabler brand-stack and navigation icons reused consistently, with vector crispness; no new raster decorations or CSS artwork. Source project chevron omitted because there is no implemented project-switching workflow.
- Copy/content: title, labels and operations are concise enterprise wording. Counts, timestamps, documents, inventory and saved results remain API-backed. Source invented row 9/10 values were not copied. Calculation caveat and provenance remain accessible; no model-success claims invented.

## Interaction and responsive evidence

- Inventory: page 2 shows later materials; searching 生化清洗液 resets to first page and one result; reset restores 24; quality filter shows 2 anomalous records. Detail drawer shows 120 bottles / 20 per day / 6 days, and Escape closes it.
- Knowledge: catalogue shows 46 active documents; 生化清洗液 search returns 2; original-text search 消耗记录缺日 returns scoped document excerpts. No model call required for lexical retrieval.
- Workbench: history table renders 9 saved records, truthfully distinguishing historical validation, failed and completed AI runs. Existing run 8ec4b6c6 opens with 6 source references and stock facts.
- Agent form: row action preselects material and question, generic new-check supports all scoped materials; empty form disables submit. Tested opening/closing only, no new paid calls.
- Browser-computed padding: inventory, knowledge, history first cells = 24px; toolbar/heading and pagination = 24px. Mobile first cells = 16px.
- Desktop screenshots: inventory, overview and knowledge. Mobile screenshots: inventory, knowledge, overview mid-page, new-check form. Initial mobile inventory screenshot is 390 × 844 CSS/pixels, no page overflow. Later browser zoom was 110%: form screenshot is 354 × 767, CSS width about 354.55, devicePixelRatio 1.1. These narrower captures test resilience only and are not pixel-matched source comparisons.
- Tablet viewport request 1024 × 900 at 110% zoom yielded CSS 931 × 818, scrollWidth 931: no page overflow. Table overflow stays inside table scroll container. Viewport override reset after testing.
- Focus outlines retained, labelled inputs/buttons, semantic native table, accessible selected navigation and Escape close. Reduced-motion styles retained. Not a full screen-reader/WCAG audit or physical-device certification.
- Console warning/error query returned an empty array during UI regression.

## Automated verification

- `pnpm typecheck`: passed.
- `pnpm check:api`: passed (no contract change).
- `pnpm test:ui`: 5 passed; real SSR coverage of shared slots, ten-row pagination, pagination overrides, empty/error/retry/loading states, header zero count and precise timestamp.
- `pnpm test:sites`: 4 passed.
- `pnpm build`: passed, existing main-bundle size warning remains (approximately 1.27 MB minified / 403 KB gzip). This is not a deployment or performance-load benchmark.
- No backend changes, no re-run of provider evaluations; saved real-model evidence and current lexical retrieval were used for regression only.

## Implementation checklist and follow-up

- [x] Shared generic Ant Design table shell adopted in all three live tables.
- [x] Shared compact page header across all three routes.
- [x] Desktop source comparison, responsive and key interaction checks.
- [x] P2 findings fixed and checked again.
- [x] Local build and component checks pass.
- [ ] P3: bundle splitting can reduce initial download weight in a future performance task.

No actionable P0/P1/P2 findings remain in the tested scope. No deployment performed; existing database and configuration preserved.
