# Kufar/re.kufar.by commercial rent reconnaissance

Use HTTP first, but treat Kufar as the highest compliance/operations risk. The real estate site returns SSR HTML with `__NEXT_DATA__` and a working JSON search API, but robots disallows many query-string patterns on `re.kufar.by`.

Relevant sections for padel/sports premises:

- `https://re.kufar.by/l/minsk/snyat/kommercheskaya`
- `https://re.kufar.by/l/belarus/snyat/kommercheskaya`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/sklady`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/promyshlennye`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/magaziny`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/ofisy`

Observed list page facts:

- Listing pages contain `__NEXT_DATA__` with `props.initialState.listing.ads`, `vip`, `filters`, and `searchId`.
- Default/desired sort for freshness is represented by API/backend parameter `sort=lst.d`; list objects include `list_time`.
- HTML list has 30 normal ads plus VIP blocks; dedup by `ad_id`.
- Useful fields in list ads include `ad_id`, `ad_link`, `subject`, `body_short`, `price_byn`, `price_usd`, `currency`, `list_time`, `images`, `ad_parameters`, and `account_parameters`.

Observed API/filter facts:

- A tested API shape was `https://api.kufar.by/search-api/v1/search/rendered-paginated?cat=1050&typ=let&rgn=7&cur=USD&size=30&sort=lst.d`.
- Pagination uses tokens under `pagination.pages[].token` and then `cursor=<token>`.
- Important parameters: `cat=1050` commercial, `typ=let` rent, `rgn=7` Minsk, `prt=1` offices, `prt=2` shops, `prt=3` industrial, `prt=4` warehouses, `prt=10` services, `prt=6` other commercial, `ar` district, `prc` monthly price, `psm` price per m2, `fl` floor, `oph=1` photos.
- Area parameter `st` exists, but one probe suggested it may be exact or non-obvious; filter area locally from `ad_parameters[p=size]`.

Observed detail page facts:

- Detail URLs look like `https://re.kufar.by/vi/minsk/snyat/kommercheskaya/<type>/<adId>`.
- Detail SSR HTML contains `props.initialState.adView.data`.
- Useful detail fields include `adId`, `adViewLink`, `title`, `body`, `address`, `price`, `priceUsd`, `currency`, `parameters`, `date`, `userName`, `companyName`, `isCompanyAd`, `accountId`, `category`, and image URL groups.
- Phone/contact reveal was not extracted in HTTP probes and should not be targeted for MVP.

Protection and compliance notes:

- Small HTTP/API probes returned `200`; no actual captcha/challenge observed, though captcha strings exist in scripts/config.
- `re.kufar.by/robots.txt` disallows `*?*`, `sort`, `cursor`, `cur`, `rank`, `searchId`, and other query patterns. This makes API/query pagination a compliance risk even if technically easy.
- VPS/data-center IP risk is medium; foreign/data-center behavior was not tested.

Recommended production path:

1. For a conservative MVP, start with SSR HTML first page(s) only, not deep cursor pagination.
2. Optionally use the JSON API only after explicit risk acceptance.
3. Open detail SSR pages only for new or high-scoring ads.
4. Do not call phone reveal, login, favorites, or account endpoints.
5. Stop the adapter on `403`, `429`, captcha/challenge markers, or unexpected empty results.

Browser-harness isolated Chrome check on 2026-07-03:

- Separate clean Chrome profile on CDP port `9342` loaded `https://re.kufar.by/l/minsk/snyat/kommercheskaya/sklady` without captcha, Cloudflare, or login wall.
- A cookie modal appears on first visit and can obscure screenshots; DOM and `__NEXT_DATA__` remain readable underneath.
- The warehouse listing rendered `30` regular ads plus `3` VIP ads in `props.initialState.listing`, with `total` around `343`, `searchId`, and cursor pagination tokens.
- Detail pages under `/vi/.../<adId>?block_name=main&page=1&rank=...&searchId=...` contain `props.initialState.adView.data.initial`; useful fields include `ad_id`, `subject`, `body`, `price_byn`, `price_usd`, `currency`, `list_time`, `images`, `ad_parameters`, and `account_parameters`.
- Browser resource timing showed public API calls such as `search-api/v2/search/count`, `seotools/v1/links`, `seotools/v1/metadata`, `credit-calculator/v1/calculators/<adId>`, and map-over search requests. No deep cursor pagination was triggered in the browser check.
- Normalize detail URLs by path/ad id; do not preserve `searchId`, `rank`, or recommendation query parameters as canonical identifiers.
