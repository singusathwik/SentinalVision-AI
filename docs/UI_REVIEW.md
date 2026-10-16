# Website layout review — 2026-10-16

Updated the shared layout, typography, spacing, form alignment, checkbox rows, navigation, mobile video table, camera/account rows and long record lists. Preserved saved data and API behavior. Pagination is grouped or omitted where irrelevant. Camera controls are on Live monitoring; account settings remain on Settings. Mobile Sign out is now visible. Scrollable record regions retain keyboard focus support.

## Verification

- All nine workspace pages visited at 1440, 768, 390 and 320 pixel viewport widths in desktop Edge: 36 checks, no document/control horizontal overflow and no JavaScript or console errors.
- Login screenshots checked at desktop and mobile widths. Dark Settings checked separately; this is not exhaustive dark-theme coverage.
- Selection/clear, polygon controls and mobile logout exercised by the read-only layout audit.
- Four isolated workflow tests passed, including real upload, inference, annotated playback, evidence clips, deletion, account controls and rule revision. The isolated launcher avoids adding test records to the regular workspace.
- ESLint, TypeScript and Next production build passed.
- Viewport emulation is not physical iOS/Android or cross-browser validation.

Evidence: `results/layout-audit.json` and `screenshots/layout/` contain the final report and full-page desktop/mobile captures for every page. Screenshots show existing demo records and historical failed jobs without altering or concealing their status.

Reproduce the read-only audit with the local stack running:

```powershell
node apps/web/scripts/layout-audit.mjs current
```

It reads ignored local login credentials and writes screenshots/reports under ignored `data/layout-audit/current`. It creates no application records. Screenshot caret masking is disabled to avoid modifying SSR input attributes during hydration. Scroll regions are intentionally constrained; the audit checks horizontal overflow, and workflow tests exercise controls inside those regions.
