---
name: collector-repair
description: Диагностика и ремонт сломавшегося коллектора (realt/kufar/megapolis) через browser-harness - разведка DOM/network, скриншоты, проверка селекторов, обновление site specs и адаптера. Запускать когда padel-collect падает или парсит мусор.
---

# Ремонт коллектора

browser-harness — разведчик и ремонтник, НЕ production-crawler. Итог ремонта —
починенный Python-адаптер, который снова возвращает данные в bounded
JSON-контракт (`uv run padel-collect`). Данные из браузера напрямую в базу
не попадают никогда.

## Диагностика без браузера (сначала)

1. Что сломалось: `uv run padel-collect` — смотри JSON-сводку и stderr.
2. Сырьё: `data/raw/<дата>/<источник>_*.html` — сохраняется при каждом прогоне.
   Часто ремонт — это правка селектора/пути в JSON по свежему снапшоту,
   браузер не нужен.
3. Справочники: `pi/site-specs/<источник>.md` (контракт и известные грабли) и
   `pi/browser-harness/domain-skills/<источник>/commercial-rent-monitoring.md`
   (результаты прошлой разведки).

## Разведка через browser-harness (если сырья мало)

Нужен изолированный Chrome с CDP на localhost (запуск — см. README, раздел
«browser-harness»). Затем:

```bash
export BU_NAME=padel-monitor
export BU_CDP_URL=http://127.0.0.1:9333
uv run browser-harness
```

Допустимые применения:
- разведка DOM/network: где лежат данные (`__NEXT_DATA__`, listing API, DOM);
- скриншоты для фиксации состояния страницы;
- проверка UI-фильтров и сортировок (какие query-параметры они дают);
- ремонт site specs: обновить URL, селекторы, пути в JSON;
- обновление domain skills заметок.

Запрещено: массовый обход страниц, сбор телефонов, обход капчи, логины.

## Завершение ремонта

1. Поправь адаптер (`padel_monitor/adapters/<источник>.py`) и/или URL в
   `config.yaml`.
2. Обнови `pi/site-specs/<источник>.md` и заметку в
   `pi/browser-harness/domain-skills/` — что изменилось на сайте и что теперь
   считается рабочим способом.
3. Проверь: `uv run padel-collect` возвращает `ok: true` по источнику и
   разумные `found/new`, `uv run padel-candidates` отдаёт валидный JSON.
4. Если сайт стал требовать JS-рендер — зафиксируй это в site spec и предложи
   пользователю решение (Playwright-fallback или отключение источника),
   не встраивая браузер в ежедневный сбор молча.
