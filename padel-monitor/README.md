# Падел-монитор

Ищет в Минске и окрестностях помещения под падел-клуб (1–2 корта): ежедневно
собирает объявления с realt.by и re.kufar.by, фильтрует по падел-критериям
(площадь, высота, отопление, колонны), раз в неделю Pi-агент оценивает
кандидатов (включая фотографии), сравнивает с прошлыми находками и присылает
отчёт в Telegram.

Устройство двухслойное: **Python-коллекторы** (детерминированный сбор, только
через uv) + **Pi-агент** (LLM-скоринг, vision, судья, отправка отчёта; модели —
по подписке через `pi /login`, единый LLM-доступ через pi-ai).

---

## Что нужно установить

| Инструмент | Зачем | Как поставить |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python-слой (никаких pip/poetry) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js ≥ 20 | рантайм для Pi | nodejs.org или nvm |
| Pi | агентный рантайм | `npm install -g --ignore-scripts @earendil-works/pi-coding-agent` |

Python отдельно ставить не нужно — uv сам скачает нужный интерпретатор.

## Первый запуск (5 шагов)

Все команды — из каталога `padel-monitor/`.

**1. Окружение Python:**

```bash
uv sync --all-groups
```

Создаст `.venv` со всеми зависимостями, включая dev-группу (browser-harness).

**2. Секреты.** Создайте `.env` по образцу `.env.example`:

```
TELEGRAM_BOT_TOKEN=1234567890:AA...   # токен бота от @BotFather
HEALTHCHECKS_URL=                      # опционально, см. «Надёжность»
```

`chat_id` получателя уже задан в `config.yaml` (`telegram.chat_id`). Чтобы
бот мог писать вам, один раз отправьте ему `/start`.

**3. Логин Pi в LLM-провайдера** (свои ключи не нужны):

```bash
pi          # откроется интерактивный режим
/login      # выберите «OpenAI ChatGPT Plus/Pro (Codex)» или «Anthropic Pro/Max»
/model      # выберите модель; для анализа фото нужна модель с поддержкой изображений
```

Токены сохраняются в `~/.pi/agent/auth.json` (авто-обновление), в проект не
попадают. Без логина недельный отчёт не заработает — Pi ответит
`No API key found for the selected model`.

**4. Проверка сбора:**

```bash
uv run padel-collect
```

Ожидаемый вывод — JSON-сводка вида:

```json
{"ok": true, "sources": {"realt": {"ok": true, "found": 300, "new": 3, ...},
 "kufar": {"ok": true, "found": 84, ...}, "megapolis": {"ok": null, "skipped": true}}}
```

`megapolis: skipped` — это норма (см. «Известные ограничения»).

**5. Первый недельный отчёт:**

```bash
pi -p "Запусти недельный отчёт по скиллу padel-weekly-report" --no-session
```

Pi сам вызовет сбор, прочитает кандидатов, посмотрит фото, поставит оценки,
запишет вердикты в базу и отправит отчёт в Telegram. Первый прогон стоит
посмотреть глазами.

---

## Как этим пользоваться

- **Ничего не делать.** Настройте cron (ниже) — сбор идёт ежедневно, отчёт
  приходит в Telegram раз в неделю. Отчёт приходит **всегда**, даже пустой;
  если бот молчит неделю — система сломалась.
- **Прочитать отчёт.** Формат карточки: `[score/100]`, площадь («от X м²» =
  можно арендовать часть), высота, отопление, чеклист ✓/✗/? (1 этаж, отдельный
  вход, парковка, метро), вердикт судьи, риски, `⚖` сравнение с прошлыми
  лидерами, `📷` что видно на фото, ссылка на объявление.
- **Поменять критерии поиска** — правьте `config.yaml` (секция `profile`:
  площади, высоты, исключения), затем `uv run padel-rescore`, чтобы пересчитать
  уже собранную базу.
- **Разовые ручные команды:**

```bash
uv run padel-candidates            # JSON: кандидаты недели + контекст (для отладки)
uv run padel-telegram --text "тест" # проверить доставку в Telegram
uv run padel-rescore               # пересчёт правил по всей базе
pi                                  # интерактивная сессия Pi в проекте
```

## Расписание (cron)

Готовый пример — `deploy/crontab.example`:

```cron
CRON_TZ=Europe/Minsk
PATH=/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin

40 8 * * * cd /opt/padel-monitor && uv run padel-collect >> data/collect.log 2>&1
0 18 * * 0 cd /opt/padel-monitor && pi -p "Запусти недельный отчёт по скиллу padel-weekly-report" --no-session >> data/report.log 2>&1
```

На машине с cron должны быть uv, node и pi, и на ней нужно один раз выполнить
`pi /login`. ⚠️ Проверено: `pi -p` возвращает код 0 даже при ошибке («No API
key found») — по exit-коду cron поломку не заметит, поэтому нужен следующий пункт.

### Надёжность

1. Заведите бесплатный чек на [healthchecks.io](https://healthchecks.io)
   (период — 1 день) и впишите его URL в `.env` → `HEALTHCHECKS_URL`. После
   каждого успешного сбора уходит ping; пропал ping — вам придёт алерт.
2. Правило «отчёт всегда»: пустой недельный отчёт — это сигнал «система жива».

## Починка источников (browser-harness)

Если `padel-collect` начал падать или парсить мусор — сайт поменял вёрстку.
Ремонт делает Pi-агент по скиллу `collector-repair`:

```bash
pi -p "Коллектор realt сломался, продиагностируй и почини по скиллу collector-repair"
```

Сначала он смотрит сохранённое сырьё (`data/raw/<дата>/`), справочники
`pi/site-specs/*.md` и разведнотесы `pi/browser-harness/domain-skills/*`.
Если этого мало — живая разведка через browser-harness (dev-зависимость uv,
**не** production-сборщик: только DOM/network, скриншоты, проверка UI-фильтров,
ремонт site specs). Для неё нужен изолированный Chrome с CDP на localhost:

**Windows (PowerShell):**

```powershell
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "$env:TEMP\padel-monitor-browser-profile"
$port = 9333

Start-Process -FilePath $chrome -ArgumentList @(
  "--remote-debugging-port=$port",
  "--remote-debugging-address=127.0.0.1",
  "--user-data-dir=$profile",
  "--no-first-run",
  "--no-default-browser-check",
  "about:blank"
)

$env:BU_NAME="padel-monitor"
$env:BU_CDP_URL="http://127.0.0.1:$port"

uv run browser-harness
```

**macOS/Linux:**

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$TMPDIR/padel-monitor-browser-profile" \
  --no-first-run --no-default-browser-check about:blank &

BU_NAME=padel-monitor BU_CDP_URL=http://127.0.0.1:9333 uv run browser-harness
```

CDP-порт держите только на 127.0.0.1. Итог любого ремонта — данные снова идут
через `uv run padel-collect`, браузер в ежедневном сборе не участвует.

---

## Статус: что проверено, а что нет (2026-07-05)

| Что | Статус |
|---|---|
| `uv sync --all-groups`, все 5 CLI-команд | ✅ проверено, работает |
| Сбор Realt + Kufar (`padel-collect`) | ✅ проверено: 300 + 89 объявлений, новые находятся |
| Доставка в Telegram | ✅ проверено, отчёты доходят |
| `browser-harness` через uv | ✅ ставится и запускается (живая разведка не гонялась) |
| Pi (v0.80.3) + `/login` openai-codex | ✅ залогинен, модель по умолчанию gpt-5.5 |
| Недельный отчёт через Pi end-to-end | ✅ **прогнан 2026-07-05**: сбор → кандидаты → фото топ-10 → 15 вердиктов в базу → отчёт в Telegram (~5 мин) |
| Vision-анализ фото | ✅ работает на gpt-5.5: в вердиктах реальные наблюдения (колонны, арочные пролёты, радиаторы, оценка высоты) |
| Источник megapolis-real.by | ❌ **выключен**: сайт не отвечает не с белорусских IP; адаптер написан по разведке, но вживую не проверен. План включения: `pi/site-specs/megapolis.md` |
| healthchecks.io | ⚠️ код готов, URL в `.env` не задан — алертов о поломке пока нет |
| Windows | ⚠️ команды uv/pi те же, но на Windows проект не запускался |

Известные долги: Telegram-токен ранее засветился в переписке — стоит
перевыпустить у @BotFather (`/revoke`) и обновить `.env`.

## Структура репозитория

```
pyproject.toml, uv.lock   Python-слой (uv); dev-группа: browser-harness
padel_monitor/            коллекторы: adapters/, normalize, rules, db, telegram, cli
config.yaml               падел-профиль, источники, chat_id
.env                      секреты (не в git)
AGENTS.md                 контекст проекта для Pi
.pi/skills/               скиллы Pi: padel-weekly-report, collector-repair
pi/site-specs/            спеки источников: контракты, грабли, стоп-сигналы
pi/browser-harness/domain-skills/   разведнотесы по сайтам
data/                     SQLite-база и raw-снапшоты (не в git)
deploy/crontab.example    расписание
```

## Частые ошибки

| Симптом | Причина и лечение |
|---|---|
| `No API key found for the selected model` | Pi не залогинен: `pi` → `/login` → выбрать подписку |
| `TELEGRAM_BOT_TOKEN не задан (.env)` | создать `.env` из `.env.example`, вписать токен |
| Бот не пишет, хотя `{"sent": true}` | получатель не нажал `/start` у бота, либо `chat_id` в `config.yaml` не ваш |
| `"megapolis": {"skipped": true}` | норма: источник выключен до проверки с BY-IP |
| В сводке `"ok": false` у источника со `STOP:` | сайт отдал 403/капчу или сменил вёрстку — скилл `collector-repair` |
| `uv: command not found` в cron | добавить `$HOME/.local/bin` в `PATH` внутри crontab |
