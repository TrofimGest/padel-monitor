# megapolis-real.by — site spec

Статус: **выключен** (`sources.megapolis.enabled: false`), адаптер написан по
разведке 2026-07-03 и НЕ проверен вживую: сайт не отвечает не с белорусских IP
(таймаут соединения). Включать и проверять с BY-IP (VPS/домашний ПК).
Адаптер: `padel_monitor/adapters/megapolis.py`.

## Ожидаемый способ добычи (по разведке)

HTTP GET → HTML → DOM-parser (selectolax). Полезного listing API нет.

- Списки: `https://megapolis-real.by/realt/skladskaya-nedvizhimost/arenda/`,
  `https://megapolis-real.by/realt/torgovaya-nedvizhimost/arenda/`
- Сортировка: `?sortBy=createdon&sortDir=DESC`; пагинация `?page=2`.
- Карточки: элементы с атрибутом `data-go-url` (~30 на страницу).

## Грабли

- HTML шумный: парсить DOM-parser'ом по карточкам, не regex по всему документу.
- Цена/площадь из текста карточки регэкспами — валидировать диапазоны.
- Гео-доступность: не-BY IP не подключается вовсе — это не бан адаптера.

## План включения

1. С BY-IP: `config.yaml` → `megapolis.enabled: true`, `uv run padel-collect`.
2. Сверить селекторы по `data/raw/<дата>/megapolis_*.html`.
3. Если карточки не находятся — скилл `collector-repair` + browser-harness
   (заметки: `pi/browser-harness/domain-skills/megapolis-real/`).
4. Итог всегда через bounded JSON-контракт.
