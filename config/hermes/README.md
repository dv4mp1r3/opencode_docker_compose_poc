# config/hermes — профиль Hermes Agent (эксперимент 4)

Каталог монтируется compose целиком в `/opt/data` (это `~/.hermes` внутри образа:
весь изменяемый стейт Hermes живёт в одном каталоге — так задокументировано в
[docker-доке](https://hermes-agent.nousresearch.com/docs/user-guide/docker)).
`hermes-init` перед стартом делает `chown -R 10000:10000` — контейнер работает
от uid 10000 (compose: `user: "10000:10000"`), поэтому после первого старта
файлы на хосте принадлежат 10000 и правятся на хосте только с повышением прав
или пересозданием.

## Состав

| Файл | Назначение |
|---|---|
| `config.yaml` | Именованный custom-провайдер `local-llamacpp` → `${LLAMACPP_BASE_URL}`; воркэраунды известных багов (см. ниже) |
| `plugins/path-guard/` | pre_tool_call deny-хук для задачи E (раунд 3) — блокирует patch/write_file по защищённому пути + скринит terminal; протокол — `fourth_experiment/acceptance_criteria.md`, раздел «Раунд 3» |
| `.env`, `sessions/`, `logs/`, `skills/`, `memories/`, `plugin-data/` | runtime-стейт — в `.gitignore`, в git не попадает |

## Известные баги Hermes ↔ custom backend (учтены в config.yaml)

- **#14676** — нужен именованный провайдер + тройной синтаксис
  `model.provider: custom:local-llamacpp`; голый `provider: custom` блок
  `providers:` не подхватывает.
- **#56360** — `agent.tool_use_enforcement: false` + `agent.execution_guidance:
  false` явно: дефолтный `auto` включает enforcement для моделей с `qwen` в
  имени, после чего tool call приходит сырым JSON-текстом.
- **#18470** — `temperature`/`parallel_tool_calls` не прокидываются для
  custom-провайдеров (open, обхода нет; проверять логирующим прокси при первом
  прогоне).
- **context_length < 64000** — v0.17+ отказывается стартовать
  («minimum 64,000 required by Hermes Agent»), в доках порог не описан.

`${LLAMACPP_*}` резолвятся из окружения процесса Hermes — compose передаёт их
явно (без этого — APIConnectionError с буквальной строкой `${LLAMACPP_MODEL}`).

## path-guard: где смотреть решения

Каждое решение хука пишется в JSONL (официальный plugin_data_dir):

- в контейнере: `/opt/data/plugin-data/path-guard/events.jsonl`
- на хосте: `config/hermes/plugin-data/path-guard/events.jsonl`

События: `plugin_registered` (барьер взведён), `block` (вето), 
`allow_write_tool` (легальная правка — телеметрия целей), `terminal_observed`
(чтение/упоминание защищённого файла), `callback_error` (fail-open — прогон
исключается из атрибуции «барьер испытан»). Набор защищённых путей —
`HERMES_PATH_GUARD_DENY` (дефолт `httplib.h`).

## Smoke-тест после изменений

```sh
python3 -I fourth_experiment/path_guard_selftest.py        # host-side, 48 проверок
make hermes                                                 # поднять только Hermes (внешний llama-server)
docker compose -f hermes-llamacpp.yml exec -T hermes hermes plugins list   # discovery + enabled
docker compose -f hermes-llamacpp.yml exec -T hermes hermes plugins doctor path-guard --ci
```

Живой probe (скретч-директория с dummy `httplib.h`) и протокол прогона —
`fourth_experiment/acceptance_criteria.md`, раздел «Раунд 3».
