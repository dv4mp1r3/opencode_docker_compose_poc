.PHONY: up up-gpu down logs pull list code shell check-proxy help

MODEL ?= qwen2.5-coder:7b

PROXY_HOST ?= host.docker.internal
PROXY_PORT ?= 8118

help:
	@echo "Доступные команды:"
	@echo "  make up          — запустить (CPU)"
	@echo "  make up-gpu      — запустить с NVIDIA GPU (Linux)"
	@echo "  make down        — остановить"
	@echo "  make logs        — логи всех сервисов"
	@echo "  make pull        — скачать модель (MODEL=name)"
	@echo "  make list        — список скачанных моделей"
	@echo "  make code        — открыть OpenCode в терминале"
	@echo "  make shell       — shell внутри opencode контейнера"
	@echo "  make check-proxy — проверить доступ к прокси из контейнера"

up:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d
	@echo ""
	@echo "Ollama API: http://localhost:$$(grep OLLAMA_PORT .env | cut -d= -f2 || echo 11434)"
	@echo "Запусти: make pull MODEL=$(MODEL)"
	@echo "Затем:   make code"

up-gpu:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

down:
	docker compose down

logs:
	docker compose logs -f

pull:
	@echo "Скачиваю модель: $(MODEL)"
	docker compose exec ollama ollama pull $(MODEL)

list:
	docker compose exec ollama ollama list

code:
	docker compose exec -it opencode opencode

shell:
	docker compose exec -it opencode sh

check-proxy:
	@echo "Проверяю доступ к прокси $(PROXY_HOST):$(PROXY_PORT) из контейнера..."
	docker compose run --rm --entrypoint bash opencode -c \
		'timeout 3 bash -c "cat /dev/null > /dev/tcp/$(PROXY_HOST)/$(PROXY_PORT)" \
		&& echo "OK: прокси доступен" || echo "FAIL: прокси недоступен"'
