# Realt.by commercial rent reconnaissance

Use boring HTTP first for light monitoring. `https://realt.by/rent/offices/` returns SSR HTML with `__NEXT_DATA__`, JSON-LD, `pageProps.objects`, `pageProps.pagination`, and an Apollo state. No JS render is required for list/detail data in the observed pages.

Relevant sections for padel/sports premises:

- `https://realt.by/rent/offices/`
- `https://realt.by/rent/shops/`
- `https://realt.by/rent/storages/`
- `https://realt.by/rent/warehouses/`
- `https://realt.by/rent/production/`
- `https://realt.by/rent/services/`
- `https://realt.by/rent/business/`

Observed list page facts:

- Default list is "Рекомендуемые", not strictly newest.
- Page 1 had `pagination: { page: 1, pageSize: 120, totalCount: 1401 }`.
- Pagination uses page links such as page 2, page 3, etc.; robots allows `*page=2` through `*page=10`.
- `?dateStart=2026-07-02` appeared ignored in one probe, returning the same count/order.
- Embedded object fields included `code`, `uuid`, `title`, `headline`, `address`, `price*`, `priceCurrency`, `pricePerM2`, `areaMin`, `areaMax`, `objectType`, `storey`, `storeys`, `contactName`, `contactPhones`, `agencyName`, `companyName`, `createdAt`, `updatedAt`, `description`, `location`, `images`.

Observed detail page facts:

- Detail URLs look like `https://realt.by/rent-offices/object/{id}/`.
- Detail pages also return SSR HTML with `__NEXT_DATA__` and JSON-LD.
- `pageProps.object` has richer object data.
- Contact phone numbers may be present in embedded state even when the visual page says "Показать контакты"; treat this as sensitive and check legal/terms before storing or exposing.

Protection and compliance notes:

- Small HTTP probes returned 200 and no obvious Cloudflare/captcha/Turnstile markers.
- `robots.txt` disallows `/bff/graphql`, `/api/device-info`, `/_*`, account/user paths, and broad query patterns, while allowing page parameters 2-10.
- Do not use `/bff/graphql` as the production endpoint unless there is explicit permission.
- User agreement states the service is intended for users in Belarus and does not guarantee availability outside Belarus.

Recommended production path:

1. Fetch listing HTML at low frequency with a normal UA.
2. Parse `__NEXT_DATA__` from HTML, not hidden GraphQL endpoints.
3. Store only listing metadata needed for matching/scoring; handle phones conservatively.
4. Poll first 1-2 pages per relevant category once or twice per day, dedup by `source + code`.
5. Use browser-harness only for debugging UI changes or reconnecting selectors/state after HTML shape changes.
