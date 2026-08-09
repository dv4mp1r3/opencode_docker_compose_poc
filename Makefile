.PHONY: up up-gpu down logs pull list code shell check-proxy log help

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
	@echo "  make log list    — список сессий opencode"
	@echo "  make log get ID  — выгрузить конкретную сессию opencode (JSON)"

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

log:
	@case "$(word 2,$(MAKECMDGOALS))" in \
		list) docker compose exec -T -e PAGER=cat opencode opencode session list ;; \
		get) \
			if [ -z "$(word 3,$(MAKECMDGOALS))" ]; then \
				echo "Использование: make log get <sessionID>"; \
				exit 1; \
			fi; \
			docker compose exec -T -e PAGER=cat opencode opencode export $(word 3,$(MAKECMDGOALS)) ;; \
		*) echo "Использование: make log list | make log get <sessionID>" ;; \
	esac

# Позволяет писать "make log list" / "make log get <id>" — без этого make
# попытался бы собрать "list"/"get"/"<id>" как отдельные цели.
ifeq (log,$(firstword $(MAKECMDGOALS)))
  LOG_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  $(eval $(LOG_ARGS):;@:)
endif
