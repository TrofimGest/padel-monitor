# re.kufar.by — site spec

Статус: включён, режим «осторожный SSR». Повышенный robots/terms риск.
Адаптер: `padel_monitor/adapters/kufar.py`.

## Рабочий способ добычи

HTTP GET категорийного URL БЕЗ query-параметров → `__NEXT_DATA__` →
`props.initialState.listing.ads` (30 объявлений + VIP). Дефолтная выдача
отсортирована по `list_time` — новое видно на первой странице.

- URL: `https://re.kufar.by/l/minsk/snyat/kommercheskaya`
  (+ `/sklady`, `/promyshlennye`).
- Detail: `https://re.kufar.by/vi/{ad_id}` (канонизировать по ad_id, отбрасывать
  `searchId`/`rank`).

## Ключевые поля

`ad_id`, `ad_link`, `subject`, `body_short`, `price_byn`/`price_usd`
(**в копейках** — делить на 100), `list_time`, `images[].path`
(CDN: `https://rms.kufar.by/v1/gallery/` + path), `ad_parameters`:
`size` (м²), `square_meter` (цена/м²), `property_type`, `area` (район),
`metro`, `re_number_floors`, `commercial_improvements` (список, есть
«Отопление», «Парковка»), `coordinates`.

## Ограничения (жёсткие)

- robots.txt запрещает `*?*`, `sort`, `cursor` и пр. — НИКАКИХ query-параметров
  и cursor-пагинации. Только первая страница категорий.
- API `api.kufar.by/search-api/...` не использовать без явного решения владельца.
- Телефоны/контакты не собирать, phone reveal не дергать.
- Deep pagination не делать.

## Стоп-сигналы

403/429, капча-маркеры, пустой `ads`. При стопе адаптер замолкает до ручной
проверки — не ретраить агрессивно.

## Если сломалось

Скилл `collector-repair`; разведнотесы:
`pi/browser-harness/domain-skills/kufar/`. Итог — bounded JSON-контракт.
