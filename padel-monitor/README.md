# Падел-монитор (на базе Pi)

Мониторинг аренды помещений под падел-клуб (Минск, 1–2 корта).

Архитектура двухслойная:

- **Python-коллекторы (uv)** — детерминированный сбор: HTTP → парсинг →
  SQLite → жёсткие правила → эвристический pre-score. Bounded JSON-контракты,
  ноль LLM-кода.
- **Pi (pi-mono)** — агентный рантайм: LLM-скоринг, vision-анализ фото, судья
  со сравнением с прошлыми лидерами, композиция и отправка недельного отчёта.
  Пакеты: `pi-coding-agent` (CLI/TUI), `pi-agent-core` (рантайм),
  `pi-ai` (единый multi-provider LLM API — весь доступ к моделям идёт через
  него, своих LLM-клиентов в проекте нет).

Полная архитектура: `../docs/final-architecture.md`.

## Установка

```bash
# Python-слой (только uv; pip/poetry не используются)
uv sync --all-groups        # включая dev-группу с browser-harness

# Pi
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

`.env` в корне проекта: `TELEGRAM_BOT_TOKEN=...` (+ опционально
`HEALTHCHECKS_URL=...`).

### Аутентификация LLM: подписка через Pi

Свой OAuth не реализуем — используется штатная механика Pi:

```bash
pi            # интерактивно
/login        # выбрать «OpenAI ChatGPT Plus/Pro (Codex)» (или Anthropic Pro/Max)
/model        # выбрать модель (для vision-анализа фото нужна модель с image input)
```

Токены живут в `~/.pi/agent/auth.json` (авто-рефреш), в проект не попадают.

## Запуск

```bash
uv run padel-collect                  # ежедневный сбор (детерминированный)
pi -p "Запусти недельный отчёт по скиллу padel-weekly-report"   # недельный отчёт
```

Pi подхватывает `AGENTS.md` и скиллы из `.pi/skills/`:

- `padel-weekly-report` — сбор → кандидаты → фото → судейство → вердикты в
  базу → отчёт в Telegram;
- `collector-repair` — диагностика/ремонт сломавшегося адаптера.

CLI-контракты (используются скиллами, пригодны и для ручной отладки):

```bash
uv run padel-candidates               # JSON: кандидаты + прошлые лидеры + контекст
uv run padel-save-verdicts --file verdicts.json
uv run padel-telegram --file report.html
uv run padel-rescore                  # после изменения правил в config.yaml/rules.py
```

## Расписание (cron)

См. `deploy/crontab.example`: ежедневно `uv run padel-collect` (плюс ping
healthchecks), еженедельно `pi -p ...` для отчёта. Отчёт отправляется всегда,
даже пустой — молчание бота означает поломку.

## browser-harness: разведка и ремонт (НЕ production)

`browser-harness` — явная dev-зависимость (`[dependency-groups] dev` в
`pyproject.toml`), ставится и запускается только через uv. Применение:

- разведка DOM/network источников;
- скриншоты;
- проверка UI-фильтров;
- ремонт site specs (`pi/site-specs/*.md`);
- обновление domain skills (`pi/browser-harness/domain-skills/*`).

Production-сбор всегда остаётся за HTTP-коллекторами: даже после ремонта через
браузер данные возвращаются в bounded JSON-контракт (`padel-collect`).

### Изолированный Chrome (Windows, без ручного разрешения)

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

### Изолированный Chrome (macOS/Linux)

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$TMPDIR/padel-monitor-browser-profile" \
  --no-first-run --no-default-browser-check about:blank &

BU_NAME=padel-monitor BU_CDP_URL=http://127.0.0.1:9333 uv run browser-harness
```

CDP-порт держать только на 127.0.0.1 и не открывать наружу.

## Структура

```
pyproject.toml, uv.lock      Python-слой (uv); dev-группа: browser-harness
padel_monitor/               коллекторы: adapters, normalize, rules, db, cli
config.yaml                  падел-профиль, источники, chat_id
AGENTS.md                    контекст проекта для Pi
.pi/skills/                  скиллы Pi (weekly report, collector repair)
pi/site-specs/               спеки источников: контракты, грабли, стоп-сигналы
pi/browser-harness/domain-skills/   разведнотесы по сайтам
data/                        SQLite + raw-снапшоты (в git не попадает)
deploy/crontab.example       расписание
```

## Известные ограничения

- Megapolis выключен: сайт недоступен не с BY-IP; включать по
  `pi/site-specs/megapolis.md`.
- Vision-анализ фото требует модели с image input (выбирается в `pi /model`);
  без него скилл честно помечает отчёт «фото не анализировались».
