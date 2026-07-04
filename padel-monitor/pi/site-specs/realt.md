# realt.by — site spec

Статус: основной источник, работает. Адаптер: `padel_monitor/adapters/realt.py`.

## Рабочий способ добычи

HTTP GET списка → `<script id="__NEXT_DATA__">` → `props.pageProps.objects`
(30 объектов/страница) + `pagination`. JS-рендер не нужен.

- Категории: `https://realt.by/rent/{warehouses,storages,production,services,shops}/`
- Сортировка по новизне: `?sortType=createdAt` (проверено 2026-07-04).
- Пагинация `&page=N`; robots допускает page 2–10. Берём 1–2 страницы на категорию.
- Detail URL: `https://realt.by/rent-{category}/object/{code}/`.

## Ключевые поля объекта

`code` (id), `title`, `headline`, `description`, `price`/`priceMin`/`priceMax`,
`priceCurrency` (933=BYN, 840=USD), `pricePerM2`, `areaMin`/`areaMax`
(areaMin < areaMax = можно арендовать часть), `storey`/`storeys`, `heating`
(truthy = отапливаемое), `address`, `townName`, `stateDistrictName`,
`metroStationName`, `createdAt`/`updatedAt`, `images[]`.

## Грабли

- Дефолтная выдача — «Рекомендуемые», не новизна: без `sortType=createdAt`
  новые объявления тонут.
- `price` бывает 0 при заполненном `pricePerM2` — считаем price = ppm2 × area.
- `?dateStart=` игнорируется сервером.
- `/bff/graphql` не использовать (robots запрещает).
- Телефоны есть в embedded state — НЕ извлекать и не хранить.

## Стоп-сигналы

403/429, маркеры капчи, отсутствие `__NEXT_DATA__`, пустой `objects` при
непустой странице. Адаптер бросает `AdapterStop` — источник останавливается,
остальные продолжают.

## Если сломалось

Скилл `collector-repair`: сначала `data/raw/<дата>/realt_*.html`, затем
browser-harness (заметки: `pi/browser-harness/domain-skills/realt/`).
Итог ремонта — данные снова идут через bounded JSON-контракт
(`uv run padel-collect` / `padel-candidates`), не через браузер.
