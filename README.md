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

Отредактируй `.env`:

```
OPENCODE_MODEL=qwen2.5-coder:7b
```

Популярные модели для кода:

| Модель | Размер | Хорошо для |
|---|---|---|
| `qwen2.5-coder:7b` | ~4 GB | Общие задачи, быстро |
| `qwen2.5-coder:14b` | ~8 GB | Сложные задачи |
| `deepseek-coder-v2:16b` | ~9 GB | Рефакторинг, архитектура |
| `codestral:22b` | ~12 GB | Максимальное качество |

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

## Команды

```bash
make up           # запустить
make down         # остановить
make pull         # скачать модель (MODEL=name)
make list         # список моделей
make code         # открыть OpenCode
make logs         # логи
make shell        # shell в контейнере opencode
make check-proxy  # проверить доступ к прокси из контейнера
```
