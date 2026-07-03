# Handoff: мониторинг коммерческой аренды

Дата пакета: 2026-07-03

> Обновление 2026-07-04: ответы Трофима получены, итоговая архитектура
> зафиксирована в `docs/final-architecture.md`. Раздел «Вопросы Трофиму»
> ниже закрыт; этот файл остаётся как история.

## Итоговый вердикт

Строить не браузерного кликера, а HTTP-first мониторинг.

`browser-harness` подтвердил, что для `megapolis-real.by`, `realt.by` и `re.kufar.by` базовые данные списков и карточек доступны без обязательного JS-рендера. Браузер нужен для разведки, скриншотов, проверки UI-фильтров и ремонта адаптеров, но не как ежедневный production-runner.

Рекомендуемый MVP:

1. `megapolis-real.by`: `HTTP -> HTML/DOM parser`.
2. `realt.by`: `HTTP -> parse __NEXT_DATA__`.
3. `re.kufar.by`: осторожно и опционально, через feature flag: SSR HTML / `__NEXT_DATA__`; API использовать только после явного принятия robots/terms риска.
4. `Playwright`: fallback, если HTTP перестал отдавать данные или нужна проверка JS UI.
5. `browser-harness`: разведка, диагностика, скриншоты, ремонт adapter'ов.
6. Vision: не нужен для цены, площади, адреса и даты; можно позже использовать только для оценки фотографий как гипотезу.

## Что в архиве

- `docs/real-estate-monitor-architecture.md` - основной архитектурный документ и требования.
- `raw/pasted-text-experiment-summary.txt` - исходный итог после прогонов.
- `workspace/AGENTS.md` - правила workspace, включая browser-first routing.
- `browser-harness/SKILL.md` и `browser-harness/install.md` - инструкции по harness.
- `browser-harness/domain-skills/*/commercial-rent-monitoring.md` - заметки по каждому сайту.
- `browser-harness/screenshots/*` - скриншоты разведки по сайтам.

## Что делать следующему агенту

Не начинать с браузерного кликера и не писать массовый scraper без подтверждения критериев.

Сначала:

1. Прочитать `docs/real-estate-monitor-architecture.md`.
2. Прочитать notes в `browser-harness/domain-skills/`.
3. Использовать скриншоты только как визуальное подтверждение разведки.
4. Выбрать первый adapter: `realt.by` или `megapolis-real.by`.
5. Реализовывать MVP через скучный pipeline: fetch -> parse -> normalize -> SQLite -> dedup -> scoring -> Telegram report.

## Production-решение

Сначала 7-10 дней запускать локально на ПК:

```text
HTTP/DOM first
Megapolis: HTTP + DOM parser
Realt: HTTP + __NEXT_DATA__
Kufar: cautious SSR / feature flag
Playwright: fallback only
browser-harness: exploration/debug
SQLite for storage
Telegram Bot API for reports
```

Потом:

- перенести `Megapolis` и `Realt` на VPS, если нет блокировок;
- оставить проблемный источник локально, если VPS/data-center IP ловит блоки;
- `Kufar` включать отдельно, без deep pagination и без автоматического сбора телефонов;
- Browser Use Cloud рассматривать только точечно, если появится сложный браузерный fallback.

## Вопросы, которые еще надо закрыть с Трофимом

1. Город и районы.
2. Точно падел-корт или шире: спортзал/склад/ангар.
3. Минимальная площадь.
4. Минимальная высота потолка.
5. Максимальный бюджет в месяц и цена за м2.
6. Допустимые типы помещений.
7. Что сразу исключать.
8. Нужны ли парковка, первый этаж, отдельный вход, метро/МКАД.
9. Можно ли помещение под ремонт.
10. Куда слать отчет и как часто.

## Короткий prompt для следующего агента

```text
Ты продолжаешь проект мониторинга коммерческой аренды по пакету handoff.

Сначала прочитай:
- docs/real-estate-monitor-architecture.md
- browser-harness/domain-skills/*/commercial-rent-monitoring.md
- raw/pasted-text-experiment-summary.txt

Не строй браузерного кликера. Архитектурный verdict уже принят: HTTP-first мониторинг, Playwright только fallback, browser-harness только разведка/ремонт. Начни с реализации или детализации MVP adapter'ов для Megapolis/Realt, Kufar держи за feature flag из-за robots/terms риска.

Перед кодом уточни критерии поиска у Трофима, если их нет: город, площадь, высота, бюджет, типы помещений и исключения.
```

