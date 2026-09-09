.PHONY: up up-gpu down logs pull models chat shell check-proxy help

# Makefile для эксперимента 4 (Hermes Agent + llama.cpp). Старый Makefile для
# opencode+ollama переименован в Makefile.old — его цели работают через
# `docker compose -f docker-compose.yml ...` напрямую, если понадобятся.

MODEL ?= Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M

PROXY_HOST ?= host.docker.internal
PROXY_PORT ?= 8118

COMPOSE := docker compose -f hermes-llamacpp.yml

help:
	@echo "Доступные команды (Hermes Agent + llama.cpp):"
	@echo "  make up          — запустить (CPU)"
	@echo "  make up-gpu      — запустить с NVIDIA GPU (Linux, требует hermes-llamacpp.gpu.yml)"
	@echo "  make down        — остановить"
	@echo "  make logs        — логи всех сервисов"
	@echo "  make pull        — поднять llama-cpp и прогреть докачку модели (MODEL=repo:quant)"
	@echo "  make models      — список GGUF-файлов в кэше llama.cpp"
	@echo "  make chat        — открыть Hermes в терминале (docker exec -it hermes hermes)"
	@echo "  make shell       — shell внутри контейнера hermes"
	@echo "  make check-proxy — проверить доступ к прокси из контейнера hermes"
	@echo ""
	@echo "config/hermes/config.yaml уже настроен на llama-cpp (см. config/hermes/README.md)."
	@echo "Баг #18470 (temperature/parallel_tool_calls) всё ещё open — проверить логирующим"
	@echo "прокси при первом реальном прогоне, обхода в конфиге нет."

up:
	@cp -n .env.example .env 2>/dev/null || true
	$(COMPOSE) up -d
	@echo ""
	@echo "llama.cpp API: http://localhost:$$(grep LLAMACPP_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)"
	@echo "Конфиг Hermes: config/hermes/config.yaml (баг #18470 temperature/parallel_tool_calls всё ещё не закрыт — см. config/hermes/README.md)"
	@echo "Затем: make chat"

up-gpu:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose -f hermes-llamacpp.yml -f hermes-llamacpp.gpu.yml up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

pull:
	@echo "Поднимаю llama-cpp, докачка модели $(MODEL) идёт при первом старте сервера"
	LLAMACPP_MODEL="$(MODEL)" $(COMPOSE) up -d llama-cpp
	@echo "Прогресс — в 'make logs' (llama-server пишет прогресс докачки в свой stdout)"

models:
	$(COMPOSE) exec llama-cpp find /models -maxdepth 4 -iname '*.gguf'

chat:
	@if [ -z "$$($(COMPOSE) ps -q hermes --status running 2>/dev/null)" ]; then \
		echo "Контейнер hermes не запущен — запускаю..."; \
		$(COMPOSE) up -d hermes; \
	fi
	$(COMPOSE) exec -it hermes hermes

shell:
	$(COMPOSE) exec -it hermes sh

check-proxy:
	@echo "Проверяю доступ к прокси $(PROXY_HOST):$(PROXY_PORT) из контейнера..."
	$(COMPOSE) run --rm --entrypoint sh hermes -c \
		'timeout 3 sh -c "cat /dev/null > /dev/tcp/$(PROXY_HOST)/$(PROXY_PORT)" \
		&& echo "OK: прокси доступен" || echo "FAIL: прокси недоступен"'
