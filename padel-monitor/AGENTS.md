# padel-monitor

Мониторинг аренды помещений под падел-клуб (Минск, 1–2 корта). Проект построен
на базе Pi (pi-mono): Pi-агент — рантайм для LLM-скоринга, vision-анализа фото,
судейства и оркестрации; Python (через uv) — только детерминированные
коллекторы с bounded JSON-контрактами.

## Разделение ответственности

- **Python (uv)** — сбор HTTP → парсинг → нормализация → SQLite → жёсткие
  правила падел-профиля → эвристический pre-score. Никаких LLM-вызовов в Python.
- **Pi-агент (ты)** — недельный отчёт: скоринг кандидатов, анализ фотографий,
  сравнение с прошлыми лидерами, композиция отчёта, отправка в Telegram
  через CLI-контракт. Скилл: `padel-weekly-report`.
- **browser-harness (uv dev-dependency)** — ТОЛЬКО разведка/ремонт: DOM/network,
  скриншоты, проверка UI-фильтров, починка site specs, обновление domain skills.
  НЕ production-crawler. Скилл: `collector-repair`.

## Команды (всегда через uv, не pip)

```bash
uv sync --all-groups          # окружение (dev-группа включает browser-harness)
uv run padel-collect          # сбор источников -> SQLite; JSON-сводка в stdout
uv run padel-candidates       # кандидаты недели + контекст судьи (JSON)
uv run padel-save-verdicts --file verdicts.json
uv run padel-telegram --file report.html
uv run padel-rescore          # пересчёт правил после их изменения
uv run browser-harness        # разведка (нужен Chrome с CDP, см. README)
```

Python-зависимости добавлять только через `uv add` (dev: `uv add --group dev`).

## Контракты данных

`padel-candidates` выдаёт bounded JSON: `profile` (критерии), `candidates`
(≤20, description ≤1500 символов, ≤4 фото-URL), `previous_leaders`,
`price_changes`, `gone`, `runs`. Вердикты возвращай строго в формате
`padel-save-verdicts` (см. `.pi/skills/padel-weekly-report/SKILL.md`).
Любая добыча данных — в том числе после ремонта через browser-harness —
должна возвращаться в эти контракты, а не в свободной форме.

## Правила проекта

- Падел-физика: корт 20×10 м (~231 м² с конструкцией), высота ≥6 м без
  препятствий, над кортом нет колонн, помещение отапливается.
- Источники щадим: 1–2 прогона в день, без deep pagination, телефоны не
  собираем, фото не выкачиваем пачками (только ≤4 URL на кандидата для vision).
- Kufar — повышенный robots/terms риск: только SSR первой страницы.
- Секреты: Telegram-токен в `.env`; LLM-аутентификация — подписка через
  `pi /login`, токены в `~/.pi/agent/auth.json`. Ничего из этого не коммитить.
- Справочники: `pi/site-specs/*.md` (по источникам),
  `pi/browser-harness/domain-skills/*` (разведнотесы),
  `docs/final-architecture.md` (архитектура).
