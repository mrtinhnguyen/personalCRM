# Synthetic showcase and screenshots

The README images are actual screenshots of this repository's frontend with the
fixture API in `scripts/demo.mjs`. They are not captures of a personal database.

## Privacy boundary

- The demo server does not import API database code or read archives, cookies,
  credentials, `.env`, or production data. It responds with values written in
  the script itself and listens only on loopback.
- People are labeled `联系人 01`, `联系人 02`, and so on. Groups and organizations
  use generic fictional labels. The UUIDs are generated from small integer IDs.
- All counts, dates, graph edges, descriptions, and post text are invented.
- No real portraits, photographs, social handles, messages, or location records
  are used. The timeline intentionally contains text-only demo posts.
- API writes return HTTP 405. Unknown endpoints return HTTP 404; there is no
  fallback to a live API. Demo mode is not included in the production API.
- A visible banner identifies synthetic data. The Next.js output is isolated in
  `.next-demo` so it does not replace a normal production build.
- Map tiles still use OpenStreetMap. They contain public geography, and the demo
  returns no personal map points. This showcase is not an offline application.

## Recreate the images

```sh
npm ci
npm run demo
```

Open `http://127.0.0.1:4310` in a fresh browser session. Capture page content only,
without address bars, desktop notifications, bookmarks, or developer tools.

1. `dashboard.png`: `/dashboard`, desktop viewport, synthetic data banner and
   analytics visible.
2. `contacts.png`: `/profiles`, tag filters and numbered contacts visible.
3. `relationships.png`: `/relationships`, wait for the graph to load, use
   “适合全部节点” and zoom as needed to show communities.
4. `timeline.png`: `/dashboard#timeline`, show the fictional text posts.

The published images use a 1440 × 1080 desktop viewport. Review every visible label and
image before replacing a published screenshot. Do not use a live CRM screenshot
and assume name blurring removes avatars, usernames, locations, or message text.

The demo supports these showcase pages only. Links to profile details and other
application areas require the full application and are outside the fixture API.

For repeatable local capture, with the demo server already running:

```sh
npx playwright install chromium
node scripts/capture-showcase.mjs
```

The capture script accepts only a loopback port (`DEMO_PORT`), blocks external
requests and service workers, checks for the synthetic-data banner, and fails on
page errors. It also verifies that contact-list labels contain only numbered
contacts. Review the resulting pixels before publishing. If using an installed
Chrome instead of the Playwright browser, set `SHOWCASE_BROWSER_CHANNEL=chrome`.
