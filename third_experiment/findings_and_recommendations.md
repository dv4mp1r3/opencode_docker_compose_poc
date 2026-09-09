# Эксперимент 3: находки и рекомендации (живой документ)

Начато 2026-08-22. Обновляется по мере прогонов, описанных в `acceptance_criteria.md` этой же
директории. Пока прогонов не было — ниже план запуска (команды, подготовленные в переписке
2026-08-22, зафиксированы дословно, чтобы не разойтись с тем, что реально выполнялось) и контекст
по каждому кандидату.

## Статус: PLANNED, прогонов не выполнено (2026-08-22)

---

## `Devstral-Small-2-24B` через vLLM (`cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit`)

**Контекст**: в `second_experiment` этот кандидат (через Ollama) показал качественно лучший
профиль, чем остальные (ни разу не галлюцинировал несуществующее имя тула), но 0/10 success —
падал на schema-ошибках (`Missing key ["oldString"]`/`["filePath"]`) и один раз дошёл до реального
`edit`, но забыл `import "flag"`. Гипотеза: часть этих ошибок — не поведенческая путаница модели, а
следствие того, что Ollama использует общий Go-шаблон вместо специализированного tool-call
парсера, который для Devstral официально требуется в его же рекомендованном стеке.

**Известный риск, обязательно проверить перед прогоном**: в стабильных релизах vLLM (на момент
исследования, версия v0.15.1 упоминалась в источниках) есть баг — AWQ 4-bit квант Devstral
загружается с неверным классом архитектуры (`MistralForCausalLM` вместо правильного
`Ministral3ForCausalLM`, которого нет в реестре моделей этой версии vLLM) — модель выдаёт связный
текст на коротких ответах (<50 токенов), но скатывается в повторяющуюся бессмыслицу на длинных.
Источник: обсуждения вокруг квантов Devstral-Small-2 на Hugging Face (карточка
`cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit` прямо указывает на конкретный
[фиксирующий коммит](https://github.com/vllm-project/vllm/commit/5c213d2899f5a2d439c8d771a0abc156a5412a2b)
и рекомендует nightly/main-ветку vLLM, а не `pip install vllm` из PyPI).

**Установка (nightly, с нужным фиксом)**:
```bash
pip install --pre vllm --extra-index-url https://wheels.vllm.ai/nightly
```

**Запуск сервера**:
```bash
vllm serve cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit \
  --tool-call-parser mistral \
  --enable-auto-tool-choice \
  --gpu-memory-utilization 0.85 \
  --max-model-len 32768
```
Если OOM при загрузке — снижать `--gpu-memory-utilization` (до 0.75-0.8) и/или `--max-model-len`
(до 16384) как первый шаг диагностики, не менять квант сразу.

**Backend-level check (ОБЯЗАТЕЛЕН до подключения opencode)**:
```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "cyankiwi/Devstral-Small-2-24B-Instruct-2512-AWQ-4bit",
    "messages": [{"role": "user", "content": "list files in current dir"}],
    "tools": [{"type":"function","function":{"name":"bash","description":"run shell command","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}}]
  }'
```
Критерий прохода: ответ содержит структурированное поле `tool_calls`, не сырой текст/JSON. Если
именно тут проявляется известный баг (деградация на длинных ответах) — он будет виден уже на этом
шаге, не тратя время на прогон через opencode.

**Результаты**: не прогонялось.

---

## `Qwen3-Coder-30B-A3B` через vLLM (`stelterlab/Qwen3-Coder-30B-A3B-Instruct-AWQ`)

**Контекст**: в `second_experiment` этот кандидат (через Ollama) провалил smoke-test 2/2 с новым
классом сбоя — сырой XML-псевдо-tool-call (`<function=explore>...`) либо текстом напрямую, либо
пойманный как `invalid tool: 'explore'`. Галлюцинированное имя `explore` — точное совпадение с
именем встроенного read-only субагента [Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/sub-agents/),
официального CLI-харнесса Alibaba для этих же моделей — то есть модель, вероятно, отвечает в
формате, который ожидает конкретный харнесс, а не в формате, который парсит Ollama+opencode.

**Ситуация чище, чем у Devstral**: `Qwen/Qwen3-Coder-30B-A3B-Instruct` прямо в официальном списке
поддерживаемых моделей на странице [vLLM tool calling docs](https://docs.vllm.ai/en/latest/features/tool_calling.html),
с однозначным именем парсера `qwen3_xml` (более старый парсер `qwen3_coder` существовал, но по
обсуждениям в vLLM его сменили на `qwen3_xml` — чинили зависание на длинных ответах, содержащих
tool-calls). Открытых issue уровня "неверный класс архитектуры" (как у Devstral) не найдено.

**Установка**: обычный `pip install vllm` (в отличие от Devstral, nightly не требуется по
имеющимся данным — перепроверить на месте, если backend-level check не пройдёт с релизной
версией).

**Запуск сервера**:
```bash
vllm serve stelterlab/Qwen3-Coder-30B-A3B-Instruct-AWQ \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --gpu-memory-utilization 0.85 \
  --max-model-len 32768
```
VRAM (~17GB заявлено) впритык к лимиту хоста (~15GB usable) — вероятно потребуется снижать
`--max-model-len` сразу, не дожидаясь OOM (в отличие от Devstral, где ~13GB весов оставляют больше
запаса). Альтернативный квант `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ` существует как резерв,
но по отзывам заметно теряет качество на 4-bit — пробовать первым `stelterlab`.

**Backend-level check** — тот же формат `curl`, что у Devstral выше, с `"model":
"stelterlab/Qwen3-Coder-30B-A3B-Instruct-AWQ"`.

**Результаты**: не прогонялось.

---

## `gpt-oss:20b` — сознательно НЕ включён в этот раунд

Официальный контракт gpt-oss — "native Harmony harness", специфичная для OpenAI архитектура
формата ответа (каналы `analysis`/`commentary`/`final`, специальные токены), а не просто флаг
`--tool-call-parser` в vLLM, который можно проверить тем же быстрым способом, что у двух
кандидатов выше. Заметно более трудоёмкая задача — не начинать без отдельного решения
пользователя, если результаты по Devstral/Qwen3-Coder окажутся достаточно интересными, чтобы
продолжать эту линию исследования.

## Синтез (заполняется после первых прогонов)

Пока нет данных для синтеза.
