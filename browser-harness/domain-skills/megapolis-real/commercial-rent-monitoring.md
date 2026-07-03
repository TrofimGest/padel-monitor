# Megapolis-real.by commercial rent reconnaissance

Use boring HTTP first for light monitoring. Observed category and detail pages return static HTML with useful listing data; JS is not required for list/detail extraction.

Relevant sections for padel/sports premises:

- `https://megapolis-real.by/realt/skladskaya-nedvizhimost/arenda/`
- `https://megapolis-real.by/realt/torgovaya-nedvizhimost/arenda/`
- `https://megapolis-real.by/realt/torgovaya-nedvizhimost/tip/pomeshheniya-pod-uslugi/fitnes/`
- `https://megapolis-real.by/realt/ofisnaya_nedvizhimost/arenda/`

Observed list page facts:

- Default sorting appears newest-first: `sortBy=createdon`, `sortDir=DESC`, visible text like "first new".
- Pagination uses `?page=2`, `?page=3`, etc.; robots explicitly allows `*/realt/*?page=`.
- Avoid query-heavy filters in production because robots disallows many query params such as `s_min`, `s_max`, `sortBy`, `sortDir`, `city`, `street`, and `pom_type`.
- Prefer path-based category filters and local filtering by area, price, and type.
- Useful DOM/listing signals observed: `.rItem_inner.rItem_go`, `data-go-url`, `rInfo_code`, `rInfo_date`, `rInfo_price`, `rInfo_square`, `rInfo_pricetotal`.

Observed detail page facts:

- Detail URLs look like `/realt/<category>/arenda/<slug>.html`.
- Detail pages expose title/meta description, listing code, date, price, area, price per m2, address, description, photos, owner/agency/contact, phone, and email in static HTML.
- No useful Next/Nuxt state was observed. JSON-LD exists on category pages but is not the main listing payload.
- Use a structured HTML parser and scoped selectors; whole-page text contains noisy menus, footer links, and similar listings.

Protection and compliance notes:

- Small HTTP probes returned `200`; no Cloudflare/captcha/rate-limit signal observed.
- VPS risk appears low to medium but was not tested from a data-center IP.
- Do not reveal or bulk-store contact data unless needed; keep frequency low and stop on `403`, `429`, captcha, or empty unexpected pages.

Recommended production path:

1. Fetch selected path categories once or twice per day.
2. Parse list cards from static HTML.
3. Open detail pages only for new or promising listings.
4. Dedup by `source + listing_id/code`, fallback to canonical URL.
5. Use browser-harness only to repair selectors or inspect UI/network after layout changes.
