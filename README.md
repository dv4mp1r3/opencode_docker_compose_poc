# OpenCode + Ollama — локальная агентская среда

Минимальный стек для кодинга с локальными LLM-моделями в контейнерах.

## Что внутри

| Контейнер | Образ | Роль |
|---|---|---|
| `ollama` | `ollama/ollama` | Запускает LLM локально |
| `opencode` | `ghcr.io/sst/opencode` | Агентный AI-кодинг в терминале |

## Быстрый старт

```bash
# 1. Скопировать конфиг
cp .env.example .env

# 2. Поднять контейнеры
make up

# 3. Скачать модель
make pull MODEL=qwen2.5-coder:7b

# 4. Открыть OpenCode
make code
```

## Выбор модели

Модель и tool-calling настраиваются в `config/opencode.jsonc` (`.env`/`OPENCODE_MODEL` на это не влияет — реально используется только `opencode.jsonc`).

По умолчанию — `gpt-oss:20b`: надёжно использует структурированный `tool_calls` (проверено напрямую через Ollama API). **`qwen2.5-coder:14b` держится в конфиге с `"tools": false`** — эта модель стабильно (100% случаев в тестах) не оборачивает вызовы инструментов в `<tool_call>`, из-за чего вызов любого tool (edit/grep/task/...) превращается в сырой JSON прямо в чате. С `tools: false` она безопасна для обычного чата, но не для агентной работы.

Популярные модели для кода:

| Модель | Размер | Хорошо для |
|---|---|---|
| `qwen2.5-coder:7b` | ~4 GB | Общие задачи, быстро (только chat, не для tool-calling — см. выше) |
| `qwen2.5-coder:14b` | ~8 GB | Сложные задачи (только chat — см. выше) |
| `gpt-oss:20b` | ~13 GB | Агентная работа, надёжный tool-calling — используется по умолчанию |
| `deepseek-coder-v2:16b` | ~9 GB | Рефакторинг, архитектура |
| `codestral:22b` | ~12 GB | Максимальное качество |

## Субагент scout (исследование больших PHP-проектов)

Для незнакомых/больших кодовых баз (WordPress, OpenCart и т.п.), которые не влезают в контекст модели, primary-агент `auto` может делегировать read-only исследование субагенту `scout` через встроенный `task`-инструмент — `scout` только читает/ищет код (`read`/`grep`/`glob`/`list`), не может редактировать файлы или выполнять команды, и возвращает сжатую выжимку вместо полных файлов. Это экономит контекст `auto` при работе с большими проектами.

Учти: один вызов `task(subagent_type="scout", ...)` — это отдельный полный проход инференса на локальной модели, не бесплатная операция (на MacBook Air M4 один хоп занимает ~1.5-2 минуты). `auto` сам решает, когда делегировать, а когда читать напрямую — см. `config/agent_prompt.txt`.

## Свой проект вместо ./workspace

В `.env` укажи абсолютный путь:

```
WORKSPACE_PATH=/Users/username/my-project
```

Затем перезапусти: `make down && make up`

## GPU (только Linux + NVIDIA)

```bash
make up-gpu
```

Требует `nvidia-container-toolkit`.

## macOS / Apple Silicon

Ollama в Docker на Mac работает **без GPU** (Metal недоступен в контейнерах).
Если нужна максимальная скорость — установи Ollama нативно и измени `.env`:

```
# Указать на нативный Ollama вместо контейнера
OPENCODE_BASE_URL=http://host.docker.internal:11434/v1
```

И убери сервис `ollama` из `docker-compose.yml`.

## Прокси

Если внешние запросы должны идти через прокси, задай в `.env`:

```dotenv
HTTP_PROXY=http://proxy.corp.example.com:8118
HTTPS_PROXY=http://proxy.corp.example.com:8118
# NO_PROXY по умолчанию: localhost,127.0.0.1,host.docker.internal,ollama
```

Проверить доступность прокси из контейнера:

```bash
make check-proxy                              # по умолчанию host.docker.internal:8118
make check-proxy PROXY_HOST=10.0.0.1 PROXY_PORT=3128   # другой адрес
```

Или напрямую:

```bash
docker compose run --rm --entrypoint bash opencode -c \
    'timeout 3 bash -c "cat /dev/null > /dev/tcp/host.docker.internal/8118" \
     && echo "reachable" || echo "unreachable"'
```

## Тестовые прогоны и логирование

Три независимых способа собрать полный лог того, что происходит внутри opencode (что написано, какие инструменты вызваны, что вернула модель).

### Debug-лог одним файлом на прогон (рекомендуется для ручного тестирования)

`opencode run` с `--print-logs` пишет в stderr служебные события (выбор модели, permission-проверки, ошибки), а в stdout — обычный видимый вывод (текст ответа, индикаторы вызова инструментов). Редиректом обоих потоков в один файл получаем полную картину одного прогона:

```bash
docker exec opencode sh -c 'cd /workspace && opencode run --agent auto --print-logs --log-level DEBUG "твой промпт"' > test1.log 2>&1
```

### Машиночитаемый поток событий

`--format json` вместо форматированного текста отдаёт сырые JSON-события — удобно, если логи потом парсятся скриптом:

```bash
docker exec opencode sh -c 'opencode run --agent auto --format json "твой промпт"' > test1.jsonl
```

### Полная стенограмма сессии (включая интерактивный TUI)

opencode сам хранит каждую сессию и умеет отдавать её целиком как структурированный JSON (сообщения, вызовы инструментов, результаты, токены, стоимость):

```bash
docker exec opencode opencode session list            # найти sessionID
docker exec opencode opencode export ses_XXXXXXXX      # выгрузить сессию целиком
```
Флаг `--sanitize` у `export` вычищает пути/потенциально чувствительные данные из выгрузки.

Тот же функционал есть короче через `make`:
```bash
make log list                     # список сессий
make log get ses_XXXXXXXX         # выгрузить сессию целиком (JSON)
```

### Постоянный debug-лог на диске

opencode всегда (без всяких флагов) пишет внутренний debug-лог в `/home/node/.local/share/opencode/log/opencode.log` — это тот же поток событий, что и `--print-logs`, но без текста самой переписки. Директория примонтирована в `./logs/opencode` на хосте (см. `docker-compose.yml`), так что лог переживает пересоздание контейнера и читается напрямую:

```bash
tail -f logs/opencode/opencode.log
```

## Команды

```bash
make up           # запустить
make down         # остановить
make pull         # скачать модель (MODEL=name)
make list         # список моделей
make code         # открыть OpenCode
make logs         # логи всех сервисов (docker compose logs)
make log list     # список сессий opencode
make log get ID   # выгрузить сессию opencode целиком (JSON)
make shell        # shell в контейнере opencode
make check-proxy  # проверить доступ к прокси из контейнера
```
