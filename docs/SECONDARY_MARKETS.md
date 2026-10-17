# Secondary-market feeds: Republic Europe and Crowdcube

Status: no live feed. Use the CSV import route below.

## What was checked (2026-10-17)

Outbound fetches from the build environment to public feed locations:

| Location | Result |
|---|---|
| republic.com/sitemap.xml | HTTP 403 (blocked to this client) |
| crowdcube.com/sitemap.xml | HTTP 403 (blocked to this client) |
| crowdcube.com/rss | HTTP 403 (blocked to this client) |

No public RSS feed or open API was found for either site. The 403 is a block, so we did not route around it or spoof a browser agent. Scraping is also out of scope.

## CSV import route (use this)

- **Own holdings** (Seedrs/Republic or Crowdcube export of the firm's positions): `POST /holdings/import`, multipart `file`. Parsed by `app/holdings.py`. Read back with `GET /holdings`.
- **Vendor facts** (a Crowdcube or Republic export attached to a document): `POST /documents/{doc_id}/vendor-facts`. Column layouts are in `app/vendorfacts.py` as `PRESETS` (`crowdcube`, aliased to `seedrs` and `republic`). A header that matches nothing yields no facts, so an unknown layout fails closed.

Each imported value keeps the file and row it came from, the same as other CSV imports.

## Re-check

If either site later publishes a feed, add it as a connector under `app/connectors/` with a recorded or SYNTHETIC fixture. Re-run the feed check above first.
