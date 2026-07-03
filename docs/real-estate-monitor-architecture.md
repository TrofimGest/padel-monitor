# Мониторинг коммерческой аренды: архитектура и требования

Статус: черновик для обсуждения, обновлен результатами первых прогонов  
Дата: 2026-07-03  
Сайты первой очереди:

- https://megapolis-real.by/
- https://kufar.by/
- https://realt.by/

## 1. Цель

Собрать легкую систему, которая 1-2 раза в день проверяет сайты с коммерческой недвижимостью, находит новые или изменившиеся объявления об аренде, оценивает пригодность помещения под заданный сценарий и присылает короткий отчет.

Первичный сценарий: поиск помещения под падел-корт или близкий спортивный формат. Точные критерии должен подтвердить Трофим.

Система не должна быть автономным кликером как основой. Базовый принцип: самый скучный и надежный сбор данных через HTTP/DOM/Playwright, а агентные инструменты использовать для разведки, починки и смысловой оценки.

## 2. Ключевое решение на текущий момент

Рекомендуемая архитектура:

```text
cron / scheduler
  -> source adapters
  -> HTTP/DOM/Playwright fetch layer
  -> normalized listings
  -> SQLite/Postgres storage
  -> dedup + change detection
  -> rules filter
  -> LLM/Pi/Codex evaluator
  -> Telegram/email/Google Sheet report
```

Роли инструментов:

- `HTTP/DOM` - первый выбор для production-сбора.
- `Playwright` - production fallback, если сайт требует JS.
- `browser-use/browser-harness` - разведка, отладка, live-browser fallback, починка селекторов, site-specific lessons.
- `Pi` - агентская оболочка и router для экспериментов с моделями.
- `Codex` - разработка, ревью, разовая оценка, возможно отдельный evaluator через CLI.
- Vision/скриншоты - только для оценки фото/визуальных признаков, не для цены и площади.

## 2.1. Итог после первых прогонов

Главный вывод разведки: строить не браузерного кликера, а скучный HTTP-first мониторинг.

`browser-harness` подтвердил HTTP-разведку: данные списков и карточек доступны без обязательного JS-рендера. Браузер нужен для разведки, скриншотов, проверки UI-фильтров и ремонта адаптеров.

Verdict MVP:

1. `megapolis-real.by`: `HTTP -> HTML parser`.
2. `realt.by`: `HTTP -> parse __NEXT_DATA__`.
3. `re.kufar.by`: опционально и осторожно: SSR HTML / `__NEXT_DATA__`, либо API только после явного принятия robots/terms риска.
4. `Playwright` и `browser-harness`: не cron-основа, а инструмент диагностики.
5. Vision: не нужен для цены, площади, адреса и даты.

Сводка по сайтам:

| Сайт | Лучший способ | JS нужен | API/JSON | Риск защиты | VPS риск | Сложность | Уверенность |
|---|---|---:|---|---:|---:|---:|---:|
| `megapolis-real.by` | HTTP + DOM parser | Нет | Полезного listing API нет | Низкий | Низкий-средний | Средняя | Высокая |
| `realt.by` | HTTP + `__NEXT_DATA__` | Нет | Да, `pageProps.objects/object` | Низкий-средний | Средний | Низкая-средняя | Высокая |
| `re.kufar.by` | Технически HTTP JSON/SSR, practically cautious SSR | Нет | Да, `__NEXT_DATA__` + API | Средний | Средний-высокий | Средняя | Средняя |

## 3. Почему не строить все на browser-harness

`browser-harness` хорош, когда агенту нужно работать с реальным браузером, читать DOM/network, кликать, чинить helper'ы и накапливать `domain-skills`.

Но для ежедневного мониторинга он хуже как основной путь:

- дороже по токенам и времени;
- больше зависит от состояния браузера;
- может требовать ручного разрешения Chrome при подключении к обычному профилю;
- сложнее воспроизводить ошибки;
- избыточен для публичных страниц без логина.

Правильная роль: "разведчик и ремонтник", не основной сборщик.

## 4. Browser strategy

Порядок извлечения данных:

1. Network/API/embedded JSON.
   Самый желательный вариант. Проверить JSON-LD, Next/Nuxt state, XHR/fetch endpoints.

2. Static HTML + DOM parser.
   Подходит для цены, площади, адреса, заголовка, описания, ссылки, ID объявления.

3. Playwright headless.
   Использовать, если данные появляются только после JS-рендера.

4. browser-harness.
   Использовать для ручной/агентной разведки, если непонятна структура страницы, есть iframe/shadow DOM, сложные фильтры, странная пагинация или нужно проверить реальный Chrome.

5. Screenshot + vision.
   Использовать только для визуальных признаков: состояние ремонта, похожесть на зал/ангар, наличие колонн, примерная просторность. Результат vision считать гипотезой, не фактом.

## 5. Playwright skill vs browser-harness

Playwright skill - это инструкции для coding agent, как пользоваться `playwright-cli`: sessions, tracing, storage, tests, debugging. Это не заменяет production-код.

Playwright как библиотека - хороший production-инструмент для headless browser scraping.

browser-harness - инструмент живого браузера через CDP, полезен для агентной работы и диагностики.

Выбор:

- production cron: `HTTP/DOM` + `Playwright`.
- browser exploration/debug: `browser-harness`.
- agent workflow/model experiments: `Pi` + skills.

Сравнение стратегий после разведки:

| Стратегия | Плюсы | Минусы | Когда использовать |
|---|---|---|---|
| HTTP parser | Самый простой cron | Нужны селекторы | Megapolis |
| HTTP + embedded JSON | Стабильнее DOM | Может меняться схема | Realt, Kufar |
| Playwright headless | Видит JS UI | Тяжелее, больше bot-риск | Только fallback |
| browser-harness | Реальный Chrome, скрины, DOM/network | Не production-runner | Разведка и ремонт |
| VPS | Автономно | IP-риск | Megapolis/Realt после тестов |
| Local PC cron | Меньше IP-рисков | ПК должен быть включен | Первый тестовый период |
| Browser Use Cloud | Изоляция | Дороже и сложнее | Не нужен для MVP |

## 6. ПК или VPS

Текущая рекомендация:

1. Сначала обкатать на своем ПК 7 дней.
2. Если сайты не блокируют и адаптеры стабильны, перенести на VPS.
3. Если VPS/data-center IP вызывает блоки, оставить проблемный источник на локальном ПК или использовать remote/cloud browser только для него.

### ПК

Плюсы:

- домашний IP выглядит естественнее;
- проще использовать реальный браузер;
- легче первично отлаживать;
- не надо платить за VPS.

Минусы:

- ПК может быть выключен;
- сон/обновления/перезагрузки ломают расписание;
- хуже observability;
- не идеально для автономной работы неделями.

### VPS

Плюсы:

- работает постоянно;
- удобно использовать `cron`/`systemd timer`;
- проще хранить логи, базу, отчеты;
- лучше для Telegram-бота и стабильного расписания.

Минусы:

- data-center IP могут чаще попадать под антибот;
- нужен безопасный setup;
- браузерный headed-login сложнее;
- есть стоимость.

## 7. Авторизация и отдельный Chrome

Для сайтов недвижимости логин не нужен, поэтому production-сбор не должен зависеть от авторизованного браузера.

Если в будущем нужен browser-harness для авторизованных сервисов:

- не использовать основной личный Chrome profile;
- запускать отдельный automation profile через `--user-data-dir`;
- один раз вручную залогиниться в этом отдельном браузере;
- дальше запускать тот же profile, чтобы cookies/localStorage сохранялись;
- держать CDP endpoint только на `127.0.0.1`;
- не открывать remote debugging port наружу на VPS.

Отчеты лучше отправлять через API:

- Telegram Bot API вместо Telegram Web;
- Google Sheets API/service account вместо Google Sheets UI;
- email provider/API вместо Gmail Web.

## 8. Модельный слой

Нужна возможность экспериментировать не только с GPT.

Кандидаты:

- OpenAI API;
- Codex CLI / Codex по подписке для локальных доверенных workflow;
- DeepSeek;
- Kimi;
- Qwen/ZAI/MiniMax/Xiaomi;
- OpenRouter;
- Google Gemini;
- локальные модели через Ollama/LM Studio/vLLM.

Рекомендуемая роль Pi:

- model/router/agent shell;
- запуск evaluator'ов разными моделями;
- сравнение оценок моделей;
- хранение reusable skills/prompts;
- не основной scraper.

Пример логики:

```text
cheap model -> первичный semantic score
strong model -> финальная оценка top-N вариантов
rules -> жесткие фильтры до LLM
```

## 9. Данные объявления

Минимальная нормализованная структура:

```text
source
source_listing_id
url
canonical_url
title
price
currency
area_m2
price_per_m2
address
city
district
property_type
floor
description
photos
contact_type
published_at
updated_at
first_seen_at
last_seen_at
content_hash
status
raw_snapshot_path
```

Для MVP можно начать с SQLite. Postgres нужен позже, если появятся веб-интерфейс, несколько пользователей, большие объемы или сложная аналитика.

## 10. Dedup и изменения

Нужно отличать:

- новое объявление;
- повторно найденное объявление;
- изменение цены;
- изменение площади/описания;
- исчезнувшее объявление;
- дубликаты между сайтами.

Уровни dedup:

1. По `source + source_listing_id`.
2. По canonical URL.
3. По fuzzy matching: адрес + площадь + цена + ключевые слова.

## 11. Scoring

Score должен состоять из двух частей.

Жесткие правила:

- город/район;
- минимальная площадь;
- максимальный бюджет;
- тип помещения;
- исключения: подвалы, кабинеты, коворкинги, офисы, 2+ этаж без грузового лифта и т.п.

LLM-оценка:

- подходит / сомнительно / не подходит;
- score 0-100;
- краткое объяснение;
- какие данные отсутствуют;
- какие вопросы задать арендодателю;
- стоит ли открыть карточку руками.

LLM не должен переопределять жесткие ограничения без явной причины.

## 12. Отчет

MVP-отчет:

- отправка в Telegram;
- ежедневная сводка;
- отдельный блок "новые хорошие варианты";
- отдельный блок "изменения цены";
- top-N вариантов с кратким объяснением;
- ссылки на карточки;
- пометка источника и confidence.

Формат одного варианта:

```text
[82/100] Склад/зал, 620 м², Минск, 4 500 BYN/мес
Почему интересно: большая площадь, первый этаж, отдельный вход.
Риски: не указана высота потолка, нет данных по отоплению.
Источник: kufar.by
URL: ...
```

## 13. Антибот и этика

Нужно действовать аккуратно:

- 1-2 запуска в день;
- не выкачивать весь сайт;
- использовать фильтры и сортировку по новизне;
- кешировать сырье;
- не дергать карточку повторно без причины;
- ставить задержки;
- уважать robots/terms как риск;
- не обходить капчи агрессивно;
- если капча/блок - фиксировать `needs_manual_check`.

## 14. Разведка субагентов

Раздел обновлен результатами первых прогонов.

Скриншоты:

- [Megapolis screenshots](</C:/Users/user/Documents/ZeroFucks/browser-harness/agent-workspace/screenshots/megapolis>)
- [Kufar screenshots](</C:/Users/user/Documents/ZeroFucks/browser-harness/agent-workspace/screenshots/kufar>)
- [Realt screenshots](</C:/Users/user/Documents/ZeroFucks/browser-harness/agent-workspace/screenshots/realt>)

Заметки для будущей разведки:

- [Megapolis note](</C:/Users/user/Documents/ZeroFucks/browser-harness/domain-skills/megapolis-real/commercial-rent-monitoring.md>)
- [Kufar note](</C:/Users/user/Documents/ZeroFucks/browser-harness/domain-skills/kufar/commercial-rent-monitoring.md>)
- [Realt note](</C:/Users/user/Documents/ZeroFucks/browser-harness/domain-skills/realt/commercial-rent-monitoring.md>)

### 14.1 megapolis-real.by

Практичные URL:

- `https://megapolis-real.by/realt/torgovaya-nedvizhimost/tip/pomeshheniya-pod-uslugi/fitnes/`
- `https://megapolis-real.by/realt/skladskaya-nedvizhimost/arenda/`
- `https://megapolis-real.by/realt/torgovaya-nedvizhimost/arenda/`

Факты разведки:

- DOM содержит около 30 карточек на странице.
- В карточках есть `data-go-url`.
- Сортировка по новизне выражается через `sortBy=createdon`, `sortDir=DESC`.
- Пагинация работает через `?page=2`.
- Капчи в прогоне не было.
- Полезного listing API не найдено.

Вывод:

- лучший adapter: `HTTP + DOM parser`;
- JS не нужен;
- риск защиты низкий;
- VPS риск низкий-средний;
- сложность средняя;
- confidence высокий.

Особенность: HTML шумный, поэтому нужен нормальный DOM parser, а не regex по всему тексту.

### 14.2 kufar.by

Практичные URL:

- `https://re.kufar.by/l/minsk/snyat/kommercheskaya`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/sklady`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/promyshlennye`
- `https://re.kufar.by/l/minsk/snyat/kommercheskaya/magaziny`

Факты разведки:

- Есть `__NEXT_DATA__`.
- В данных есть `listing.ads`, `vip`, `pagination`.
- В detail есть `adView.data.initial`.
- Cookie modal есть.
- Капчи в прогоне не было.
- Технически данные доступны через HTTP JSON/SSR.

Вывод:

- лучший adapter для MVP: cautious SSR / `__NEXT_DATA__`;
- API технически удобный, но использовать его только после явного принятия robots/terms риска;
- JS не нужен;
- риск защиты средний;
- VPS риск средний-высокий;
- сложность средняя;
- confidence средний.

Ограничения:

- включать отдельным флагом;
- не делать deep pagination;
- не собирать и не раскрывать телефоны автоматически;
- хранить URL/превью фото, не скачивать пачками.

### 14.3 realt.by

Практичные URL:

- `https://realt.by/rent/warehouses/`
- `https://realt.by/rent/storages/`
- `https://realt.by/rent/production/`
- `https://realt.by/rent/services/`
- `https://realt.by/rent/shops/`

Факты разведки:

- Есть `__NEXT_DATA__`.
- На списках есть `pageProps.objects`.
- На detail есть `pageProps.object`.
- Фоновые `/bff/graphql` запросы видны, но для MVP не нужны.
- JS-рендер не нужен для извлечения базовых данных.

Вывод:

- лучший adapter: `HTTP + embedded JSON`;
- JS не нужен;
- риск защиты низкий-средний;
- VPS риск средний;
- сложность низкая-средняя;
- confidence высокий.

Особенность: дефолтная сортировка "Рекомендуемые", не чистая новизна. Нужны поля `createdAt`/`updatedAt` или отдельная проверка сортировки.

## 15. Вопросы Трофиму

Минимум:

1. Где ищем: город и районы?
2. Под что помещение: точно падел-корт или шире спорт/зал?
3. Минимальная площадь?
4. Минимальная высота потолка?
5. Максимальный бюджет в месяц?
6. Максимальная цена за м²?
7. Какие типы помещений допустимы: склад, ангар, спортзал, торговое, производственное, офис?
8. Что сразу исключать?
9. Нужны ли парковка, первый этаж, отдельный вход, метро/МКАД?
10. Можно ли помещение под ремонт или только готовое?
11. Нужен ли анализ фотографий?
12. Куда слать отчет и как часто?

Вопросы для выбора ПК/VPS:

1. Насколько критично, чтобы проверка сработала каждый день?
2. ПК обычно включен в нужное время?
3. Ок ли платить за VPS 5-10 USD/мес?
4. Если VPS начнет ловить блоки, ок ли оставить запуск с домашнего ПК?
5. Достаточно отчета 1-2 раза в день или нужны почти мгновенные уведомления?

## 16. MVP на 7 дней

День 1:

- зафиксировать практичные URL;
- сохранить raw samples;
- закрепить выводы раздела 14.

День 2-3:

- написать adapters: Megapolis HTML, Realt Next JSON, Kufar cautious;
- сохранять raw HTML/JSON;
- нормализовать объявления.

День 4:

- SQLite schema;
- dedup;
- change detection.

День 5:

- rules filter;
- LLM scoring prompt;
- попробовать 2-3 модели через Pi/API/Codex.

День 6:

- Telegram report;
- формат top-N;
- ошибки и empty reports.

День 7:

- локальный cron;
- тест VPS;
- сравнить блокировки, скорость, стабильность;
- определить стоп-сигналы и формат логов ошибок.

## 17. Acceptance criteria для MVP

MVP считается успешным, если:

- система стабильно собирает объявления минимум с 2 из 3 сайтов;
- не делает массовый scraping;
- хранит историю найденных объявлений;
- отличает новые объявления от старых;
- присылает Telegram-отчет;
- показывает score и объяснение;
- ошибки по одному сайту не ломают весь запуск;
- есть логи последнего запуска;
- можно вручную открыть raw snapshot и понять, почему парсер ошибся.

## 18. Основные риски

Реальные проблемы, подтвержденные или выявленные разведкой:

- `Kufar`: API удобный, но `robots.txt` запрещает многие query/cursor/sort URL. Использовать осторожно.
- `Realt`: дефолтная сортировка "Рекомендуемые", не чистая новизна. Нужны `createdAt`/`updatedAt`.
- `Megapolis`: HTML шумный, нужен DOM parser, не regex по всему тексту.
- Дубли между сайтами почти неизбежны.
- Контакты/телефоны лучше не собирать и не раскрывать автоматически.
- Фото не скачивать пачками, хранить URL/превью.

Технические:

- сайт меняет верстку;
- данные спрятаны за JS;
- API endpoint меняет формат;
- VPS IP блокируется;
- карточки дублируются;
- цена/площадь парсятся неоднозначно;
- LLM переоценивает плохие варианты из-за красивого описания.

Эксплуатационные:

- ПК выключен;
- Chrome profile разлогинился;
- Telegram token утек;
- cron упал без уведомления;
- сырье не сохраняется, и ошибку невозможно воспроизвести.

Продуктовые:

- критерии поиска слишком широкие;
- отчет зашумлен мусором;
- нет жестких исключений;
- неясно, что такое "подходит".

## 19. Открытые решения

Решено после первых прогонов:

- первый adapter можно начинать с Realt или Megapolis;
- Playwright не нужен как базовый путь;
- Browser Use Cloud не нужен для MVP;
- Vision не нужен для структурных данных;
- browser-harness остается инструментом разведки и ремонта.

Остается решить:

- выдержит ли VPS реальные запуски без блокировок;
- какие модели использовать для scoring;
- нужен ли Google Sheet кроме Telegram;
- нужен ли web dashboard.
- включать ли Kufar в MVP сразу или отдельным feature flag.

## 20. Итоговая рекомендация после первых прогонов

Начать с локальной обкатки на ПК:

```text
HTTP/DOM first
Megapolis: HTTP + DOM parser
Realt: HTTP + __NEXT_DATA__
Kufar: cautious SSR / feature flag
Playwright: fallback only
browser-harness: exploration/debug
Pi for model experiments
SQLite for storage
Telegram Bot API for reports
```

После 7 дней:

- если сайты не блокируют VPS, перенести Megapolis и Realt на VPS;
- если VPS блокируют, оставить проблемные источники локально;
- Kufar включать отдельно, без deep pagination и без телефонов;
- если нужен сложный браузерный fallback, рассмотреть Browser Use Cloud точечно.
