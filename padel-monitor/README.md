# Падел-монитор

Мониторинг аренды помещений под падел-корт (Минск и округа): ежедневный сбор
с realt.by / re.kufar.by (+ megapolis-real.by за флагом), фильтр по
падел-профилю, скоринг, еженедельный отчёт в Telegram.

Архитектура: `../docs/final-architecture.md`.

## Запуск

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # или отредактировать .env: токен бота, ключи
./.venv/bin/python -m padel_monitor.crawl    # ежедневный сбор
./.venv/bin/python -m padel_monitor.weekly   # недельный отчёт в Telegram
```

`.env`:

- `TELEGRAM_BOT_TOKEN` — токен бота (обязателен для отчёта);
- `ANTHROPIC_API_KEY` — опционально: включает LLM-скоринг и vision-анализ фото
  top-N (без ключа работает эвристический score, отчёт это помечает);
- `HEALTHCHECKS_URL` — опционально: dead-man switch (ping после успешного сбора).

Критерии поиска и флаги источников — `config.yaml` (`profile`, `sources`).

## Деплой на VPS

```bash
rsync -a --exclude .venv --exclude data padel-monitor/ vps:/opt/padel-monitor/
ssh vps 'cd /opt/padel-monitor && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt'
# перенести .env, затем crontab -e по deploy/crontab.example
```

После деплоя:

1. Прогнать `crawl` вручную, убедиться что оба источника ok.
2. Включить megapolis (`enabled: true`) и проверить: адаптер написан по
   разведке, но сайт не отвечает не с BY-IP — селекторы могут требовать правки
   по `data/raw/<дата>/megapolis_*.html`.
3. Завести чек на https://healthchecks.io (расписание «ежедневно»), URL в `.env`.
4. Перевыпустить токен бота у @BotFather (`/revoke`) — текущий засветился
   в переписке — и обновить `.env`.

## Как это устроено

```
crawl (cron, ежедневно)
  adapters/realt.py      HTTP + __NEXT_DATA__, sortType=createdAt, 2 стр/категорию
  adapters/kufar.py      осторожный SSR: 1-я страница категорий, без query, без телефонов
  adapters/megapolis.py  HTTP + DOM (не проверен, за флагом)
  → normalize (высота/колонны/парковка из текста) → SQLite data/monitor.db
  → dedup по (source, id) + события price_change/gone/returned
  → rules.py: регион, площадь ≥180, высота (<5 отказ, нет — флаг), исключения
  → эвристический score + опционально LLM
weekly (cron, вс 18:00)
  top-N новых за неделю + vision по фото (опц.) + изменения цен + исчезнувшие
  + футер здоровья → Telegram; отправляется даже пустой
```

Стоп-сигналы (403/429/капча/нет `__NEXT_DATA__`) останавливают только свой
адаптер; ошибка одного источника не роняет прогон. Сырые страницы сохраняются
в `data/raw/<дата>/` для разбора ошибок парсера.
