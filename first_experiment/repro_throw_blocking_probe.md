# Репро: проверка throw-блокировки в `tool.execute.before` (opencode 1.18.16)

Дата: 2026-08-10. Цель: независимо проверить, действительно ли `throw` внутри хука плагина
`tool.execute.before` блокирует выполнение tool-call (как заявляет официальная документация
opencode), или он глушится движком (как утверждал устаревший комментарий в
`config/no_diff_markers_plugin.js` из более ранней сессии). Не связано с golden-set из
`acceptance_criteria.md` — см. `repro_protocol.md` для остальных экспериментов, здесь только
этот один точечный тест.

## Предусловия

- Контейнер `opencode` поднят: `docker compose up -d` (или `make up`), `docker ps` → `Up`.
- Команды ниже — с хоста, из корня репозитория (`opencode_poc/`).
- Эксперимент временно правит `config/opencode.jsonc` (добавляет пробный plugin в массив
  `"plugin"`) — раздел «Откат» в конце обязателен.

## Шаг 1 — источник утверждения из официальной доки

`https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/plugins.mdx`
— раздел про `tool.execute.before`, пример: `throw new Error("Do not read .env files")`.
Ветка `dev` может быть новее установленной версии — сверить версию (шаг 2).

## Шаг 2 — зафиксировать версию opencode

```bash
docker exec opencode sh -c 'cat /usr/local/lib/node_modules/opencode-ai/package.json | grep "\"version\""'
```
Ожидается: `"version": "1.18.16"`. Другая версия — результат не переносится автоматически,
эксперимент нужно повторить на ней.

## Шаг 3 — убедиться, что артефакта прошлого прогона нет

```bash
docker exec opencode sh -c 'test -e /tmp/throw_probe_marker.txt && echo EXISTS || echo CLEAN'
```
Ожидается: `CLEAN`.

## Шаг 4 — создать пробный plugin

```bash
cat > /tmp/probe_throw_plugin.js <<'EOF'
export default async function probeThrowPlugin() {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;
      const cmd = output && output.args && output.args.command;
      if (typeof cmd !== "string" || !cmd.includes("THROW_PROBE")) return;
      console.error("[probe_throw_plugin] HOOK FIRED for command: " + cmd);
      throw new Error("PROBE: intentionally blocking this bash call");
    },
  };
}
EOF
```
Хук реагирует только на `bash`-команды с маркером `THROW_PROBE` (не задевает ничего
постороннего), сначала логирует сам факт срабатывания (докажет вызов хука независимо от
исхода), затем `throw`-ит.

## Шаг 5 — скопировать plugin в контейнер

```bash
docker cp /tmp/probe_throw_plugin.js opencode:/home/node/.config/opencode/probe_throw_plugin.js
```
`~/.config/opencode/` в контейнере не является bind-mount как единое целое (примонтированы
только отдельные файлы, см. `docker-compose.yml`) — `docker cp` кладёт файл в writable-слой
контейнера, хост не затрагивается.

## Шаг 6 — временно подключить plugin в конфиге

В `config/opencode.jsonc` заменить:
```json
"plugin": ["/home/node/.config/opencode/no_diff_markers_plugin.js"],
```
на:
```json
"plugin": ["/home/node/.config/opencode/no_diff_markers_plugin.js", "/home/node/.config/opencode/probe_throw_plugin.js"],
```
Файл смонтирован read-only, но правки хоста подхватываются живьём — `opencode run` перечитывает
конфиг при каждом запуске (видно в логе: `message=loading path=.../opencode.jsonc`), рестарт
контейнера не нужен.

## Шаг 7 — прогнать headless-сессию с маркированной командой

```bash
docker exec opencode sh -c 'cd /workspace && opencode run --agent auto --print-logs --log-level DEBUG "Выполни ровно один bash-вызов с командой ровно такой: echo THROW_PROBE_TEST_OK > /tmp/throw_probe_marker.txt — больше ничего не делай, ничего не объясняй, просто выполни эту команду и кратко отчитайся."' \
  > /tmp/throw_probe_run.log 2>&1
```

## Шаг 8 — проверить три независимых признака

```bash
grep -n "probe_throw_plugin" /tmp/throw_probe_run.log       # (a) хук вызывался?
grep -n "PROBE: intentionally" /tmp/throw_probe_run.log     # (b) ошибка дошла до движка?
docker exec opencode sh -c 'test -f /tmp/throw_probe_marker.txt && (echo EXISTS; cat /tmp/throw_probe_marker.txt) || echo MISSING'  # (c) команда реально выполнилась?
```

## Ожидаемый результат, если throw блокирует (гипотеза из доки)

- (a) непусто — `[probe_throw_plugin] HOOK FIRED for command: echo THROW_PROBE_TEST_OK > /tmp/throw_probe_marker.txt`
- (b) непусто — `Error: PROBE: intentionally blocking this bash call`
- (c) `MISSING`
- В логе также строка `✗ echo ... failed`, и финальный ответ модели должен признавать провал,
  не заявлять успех.

Если вместо этого (c) даёт `EXISTS` — throw в этой версии НЕ блокирует, несмотря на
срабатывание хука (воспроизводится старое поведение из `no_diff_markers_plugin.js`).

**Фактически полученный результат при прогоне 2026-08-10 (версия 1.18.16)**: все три признака
совпали с гипотезой "throw блокирует" — (a)/(b) непустые, (c) = `MISSING`. Финальный ответ
модели: «Команда не была выполнена из‑за ограничения на запись в `/tmp`. Файл не создан.»
(причину модель угадала неверно — дело не в `/tmp`, а в плагине — но факт провала распознала
верно и не заявила ложный успех). См. также память `project-opencode-plugin-hooks`.

## Откат — обязательно после эксперимента

```bash
# 1. Вернуть строку "plugin" в config/opencode.jsonc к исходному виду вручную (в файле на
#    момент эксперимента были и другие незакоммиченные правки — откатывать всем файлом
#    через git checkout нельзя, только точечно эту строку):
#    "plugin": ["/home/node/.config/opencode/no_diff_markers_plugin.js"],

# 2. Удалить plugin-файл и артефакт из контейнера (может понадобиться -u root — docker cp
#    кладёт файл от UID хоста, контейнер работает от node):
docker exec -u root opencode sh -c 'rm -f /home/node/.config/opencode/probe_throw_plugin.js /tmp/throw_probe_marker.txt'

# 3. Проверить, что диф снова содержит только исходные правки:
git diff -- config/opencode.jsonc
```

## Ограничения этого репро

- Throw проверен только для `input.tool === "bash"`. Для `edit`/`write` (где
  `no_diff_markers_plugin.js` сознательно использует мутацию `args`, а не throw) поведение
  отдельно не перепроверялось — при необходимости повторить тот же протокол с
  `input.tool === "edit"` / `"write"` и условием на `output.args`.
- Один прогон, не серия повторов — для бинарного факта о поведении движка (не о стохастичности
  модели) этого достаточно; если результат когда-либо не воспроизведётся — не списывать на
  флуктуацию, разбираться отдельно.
