# Ollama на macOS — установка и настройка

## 1. Установка

### Через Homebrew (рекомендуется)

```bash
brew install ollama
```

### Прямой download

Скачать `.dmg` с [ollama.com/download](https://ollama.com/download) и установить как обычное приложение.

> Версия из Homebrew — CLI без трея. Версия с сайта — полноценное приложение с иконкой в меню бара.

---

## 2. Запуск

### Если установил через Homebrew

```bash
# Запустить сервер (держи терминал открытым, или используй launchd ниже)
ollama serve

# Или как фоновый сервис через launchd
brew services start ollama
brew services stop ollama
brew services restart ollama
```

### Если установил .dmg

Открой приложение Ollama — оно появится в меню баре (иконка ламы).
Сервер запускается автоматически при старте системы.

### Проверить что работает

```bash
curl http://localhost:11434/api/tags
# Должен вернуть JSON со списком моделей
```

---

## 3. Скачать модели

```bash
# Лёгкая, быстрая (рекомендую начать с неё)
ollama pull qwen2.5-coder:7b

# Лучше качество, нужно ~8 GB RAM
ollama pull qwen2.5-coder:14b

# Топ для кода, нужно ~9 GB RAM
ollama pull deepseek-coder-v2:16b

# Список всего что скачал
ollama list

# Удалить модель
ollama rm qwen2.5-coder:7b
```

### Сколько RAM нужно

| Модель | Параметры | RAM |
|---|---|---|
| `qwen2.5-coder:7b` | 7B | ~5 GB |
| `qwen2.5-coder:14b` | 14B | ~9 GB |
| `deepseek-coder-v2:16b` | 16B | ~11 GB |
| `codestral:22b` | 22B | ~14 GB |
| `qwen2.5-coder:32b` | 32B | ~20 GB |

На Apple Silicon (M1/M2/M3/M4) модели грузятся в unified memory — и RAM и VRAM одно и то же.

---

## 4. Базовые команды

```bash
# Запустить интерактивный чат в терминале
ollama run qwen2.5-coder:7b

# Спросить что-то без интерактивного режима
echo "напиши функцию на Python для сортировки списка" | ollama run qwen2.5-coder:7b

# Посмотреть что запущено прямо сейчас
ollama ps

# Остановить модель (освободить память)
ollama stop qwen2.5-coder:7b
```

---

## 5. Конфигурация

### Переменные окружения

Добавь в `~/.zshrc` (или `~/.bashrc`):

```bash
# Держать модель в памяти бесконечно (по умолчанию выгружается через 5 минут)
export OLLAMA_KEEP_ALIVE=-1

# Разрешить запросы с других машин в сети (по умолчанию только localhost)
export OLLAMA_HOST=0.0.0.0:11434

# Количество GPU слоёв (по умолчанию максимум, обычно не нужно менять)
export OLLAMA_NUM_GPU=1

# Сколько запросов обрабатывать параллельно
export OLLAMA_NUM_PARALLEL=2
```

После изменения — перезапустить:

```bash
source ~/.zshrc
brew services restart ollama
# или если .dmg — перезапустить приложение
```

### Параметры при запуске модели

```bash
# Задать количество токенов контекста (по умолчанию зависит от модели)
ollama run qwen2.5-coder:7b --verbose

# Через API с параметрами
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5-coder:7b",
  "prompt": "hello",
  "options": {
    "num_ctx": 32768,
    "temperature": 0.1
  }
}'
```

---

## 6. Использование OpenAI-compatible API

Ollama полностью совместим с OpenAI API — любой инструмент который умеет работать с OpenAI, можно направить на Ollama.

```bash
# Базовый URL
http://localhost:11434/v1

# Список моделей
curl http://localhost:11434/v1/models

# Chat completion (OpenAI-формат)
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "привет"}]
  }'
```

---

## 7. Интеграция с OpenCode (контейнер)

Если Ollama запущена нативно на Mac, а OpenCode в Docker — используй `host.docker.internal`:

В `opencode_poc/.env`:

```env
OPENCODE_MODEL=qwen2.5-coder:7b
OLLAMA_HOST=host.docker.internal
```

Убери сервис `ollama` из `docker-compose.yml` (или закомментируй) — он не нужен.

---

## 8. Docker Desktop: "mounts denied" при поднятии compose

Если при `docker compose up` (или `make up`) видишь ошибку вида:

```
Error response from daemon: mounts denied:
The path /your/project/path is not shared from the host and is not known to Docker.
You can configure shared paths from Docker -> Preferences... -> Resources -> File Sharing.
```

Это не баг проекта, а ограничение Docker Desktop на macOS: он монтирует внутрь контейнеров только те пути,
которые явно разрешены в File Sharing (по умолчанию разрешены `/Users`, `/Volumes`, `/private`, `/tmp`, `/var/folders`).
Ошибка возникает, когда `WORKSPACE_PATH` в `.env` указывает на директорию вне этого списка — например, путь скопирован с Linux-машины (`/home/...`) и на маке такой директории вообще нет или она не расшарена.

**Как исправить:**

1. Проверь `WORKSPACE_PATH` в `.env` — на macOS путь обычно должен лежать под `/Users/<имя>/...`, а не `/home/...`.
2. Если путь корректный, но лежит вне `/Users`, `/Volumes`, `/private`, `/tmp` — расшарь его вручную:
   Docker Desktop → Settings (⚙️) → Resources → File Sharing → `+` → выбрать нужную директорию → **Apply & Restart**.
3. После этого повторно подними compose:
   ```bash
   docker compose up
   # или
   make up
   ```

Подробнее: [docs.docker.com/go/mac-file-sharing](https://docs.docker.com/go/mac-file-sharing/).

---

## 9. Автозапуск при входе в систему

### Homebrew (launchd)

```bash
brew services start ollama
# Проверить статус
brew services list | grep ollama
```

### .dmg версия

Настройки → Login Items → добавить Ollama, или включить в самом приложении через меню бара.

---

## 10. Полезные ссылки

- Все доступные модели: [ollama.com/library](https://ollama.com/library)
- Документация API: [github.com/ollama/ollama/blob/main/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md)
- OpenAI compatibility: [github.com/ollama/ollama/blob/main/docs/openai.md](https://github.com/ollama/ollama/blob/main/docs/openai.md)
