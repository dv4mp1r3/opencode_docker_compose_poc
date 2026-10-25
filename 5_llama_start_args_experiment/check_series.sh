#!/usr/bin/env bash
# T1 протокола N_RETRIES_PROTOCOL.md: универсальный запускатор серий
# канонической задачи A.
#
# Запуск:  ./check_series.sh <ТОЧКА> <МЕТКА-СЕРИИ> [ЧИСЛО-ПРОГОНОВ=13]
# Пример:  ./check_series.sh R64 s1
#
# Скрипт выполняет одну серию по канону §5 протокола: перед каждым прогоном
# сбрасывает фикстуру в исходное состояние, отправляет модели канонический
# промпт задачи A, проверяет результат обоими режимами на хосте и ставит
# механический вердикт PASS / FAIL / INVALID. Ничего не решает и не
# пересчитывает вручную — вердикт ставит только механика (правило R1).
#
# Что добавляет протокол поверх канона дня 2026-10-16:
#   * предварительные проверки перед серией (компилятор go, контейнер,
#     живой сервер с ответом /props);
#   * фиксация конфигурации точки (T2): ответ /props сохраняется в
#     мета-файл как доказательство того, на какой конфигурации шла серия;
#   * прерывание серии с пометкой CONFUND по правилу §7.6: сессия не
#     стартовала либо два прогона подряд длятся дольше 600 секунд;
#   * сброс по базовому снимку корня (поправка канона от 2026-10-25):
#     перед серией запоминается список содержимого корня рабочего каталога,
#     и при каждом сбросе удаляется всё, чего на снимке не было, — файлы
#     и каталоги. Без этого мусор от прогонов со сносом задачи переживал
#     сбросы и портил следующие прогоны (инциденты §9.6).
#
# Файлы результатов (в каталоге results/):
#   check_<ТОЧКА>_<СЕРИЯ>_series.jsonl   — по строке на прогон;
#   check_<ТОЧКА>_<СЕРИЯ>_run<K>.txt     — сырой вывод каждой сессии;
#   meta_<ТОЧКА>_<СЕРИЯ>.json            — зафиксированная конфигурация точки.
set -u
POINT="${1:?использование: check_series.sh <ТОЧКА> <МЕТКА-СЕРИИ> [ЧИСЛО-ПРОГОНОВ=13]}"
SERIES="${2:?не указана метка серии (например s1)}"
NRUNS="${3:-13}"
BASE=/home/username1/opencode_poc
RESULTS=$BASE/5_llama_start_args_experiment/results
CHECK=$BASE/workspace/exp5_check
ROOT_GO=$BASE/workspace/script.go
WORKSPACE_ROOT=$BASE/workspace
OUT=$RESULTS/check_${POINT}_${SERIES}_series.jsonl
META=$RESULTS/meta_${POINT}_${SERIES}.json
PRISTINE_SHA=ec0eefc0a67c60dc61a585554d322754bbd74fe849b893aa84764ba984e9239f
PROMPT='Добавь флаг --name (по умолчанию "world"), значение должно подставляться в приветствие вместо захардкоженного "world".'

# --- Предварительные проверки (§7.1) ---------------------------------------
if ! command -v go > /dev/null; then
  echo "ПРЕРЫВАНИЕ: компилятор go не найден на хосте — проверить артефакт будет нечем"; exit 1
fi
docker exec hermes true 2>/dev/null || { echo "ПРЕРЫВАНИЕ: контейнер hermes не отвечает"; exit 1; }
BASE_URL=$(grep '^LLAMACPP_BASE_URL=' "$BASE/.env" | cut -d= -f2- | tr -d '[:space:]')
[ -n "$BASE_URL" ] || { echo "ПРЕРЫВАНИЕ: в .env нет переменной LLAMACPP_BASE_URL"; exit 1; }
PROPS_URL="${BASE_URL%/v1}/props"
PROPS_RAW=$(curl -sf --max-time 10 "$PROPS_URL") || { echo "ПРЕРЫВАНИЕ: сервер не отвечает на запрос $PROPS_URL"; exit 1; }
CTX=$(printf '%s' "$PROPS_RAW" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["default_generation_settings"]["n_ctx"])' 2>/dev/null)
[ -n "$CTX" ] || { echo "ПРЕРЫВАНИЕ: в ответе /props нет размера контекста — сверить конфигурацию точки вручную"; exit 1; }
echo "Проверки перед серией: сервер $PROPS_URL отвечает, размер контекста n_ctx=$CTX"

# Защита от случайной перезаписи существующей серии: перезапуск возможен
# только после разбора причины и ручного удаления старого файла (правило R5).
if [ -f "$OUT" ]; then
  echo "ПРЕРЫВАНИЕ: файл $OUT уже существует; чтобы перезапустить серию, устраните причину и удалите файл вручную (правило R5)"; exit 1
fi

# --- Фиксация конфигурации точки (T2) --------------------------------------
# Ответ сервера передаётся в Python через временный файл: конструкция
# «конвейер + документ-здесь» не работает, потому что документ-здесь
# перекрывает конвейер как стандартный ввод (дефект, найденный пробным
# прогоном, см. §9.5 протокола).
PROPS_FILE=$(mktemp)
printf '%s' "$PROPS_RAW" > "$PROPS_FILE"
python3 -I - "$META" "$POINT" "$SERIES" "$BASE_URL" "$CTX" "$PROPS_FILE" <<'EOF' || { echo "ПРЕРЫВАНИЕ: не удалось записать мета-файл конфигурации"; rm -f "$PROPS_FILE"; exit 1; }
import json, sys, time
meta, point, series, base_url, ctx, props_path = sys.argv[1:7]
doc = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "point": point, "series": series,
    "base_url": base_url, "n_ctx": int(ctx),
    "server_cmd": "см. реестр запусков N_RETRIES_PROTOCOL.md §9.2 (квантование KV-кэша через API не видно)",
    "props": json.load(open(props_path)),
}
open(meta, "w").write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
EOF
rm -f "$PROPS_FILE"
echo "Конфигурация зафиксирована: $META"

# --- Канон §5 (с поправкой от 2026-10-25 — сброс по снимку корня) ----------
# Базовый снимок корня: список всего содержимого на момент старта серии.
# Всё, что появится позже (файлы и каталоги), удаляется при каждом сбросе —
# иначе мусор от прогонов со сносом задачи доживает до следующих прогонов
# (инциденты §9.6: файл script.py, затем каталог hermes_cli).
BASELINE=$(mktemp)
trap 'rm -f "$BASELINE"' EXIT
ls -A "$WORKSPACE_ROOT" | sort > "$BASELINE"

reset_fixture() {
  # Фикстура: эталонный script.go, всё остальное в рабочем каталоге — удалить.
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$CHECK/script.go"
  find "$CHECK" -mindepth 1 -not -name script.go -delete
  # Корневой якорь перезаписывается эталоном (проверка root_changed смотрит на него).
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$ROOT_GO"
  # Чистка корня по снимку: удаляется всё, чего не было на старте серии.
  # Исключения: якорь script.go (управляется выше) и AGENTS.md — сервисная
  # инструкция, защищающая от сноса задачи на установку Hermes.
  while IFS= read -r entry; do
    [ "$entry" = "script.go" ] && continue
    [ "$entry" = "AGENTS.md" ] && continue
    grep -qxF -- "$entry" "$BASELINE" || rm -rf -- "${WORKSPACE_ROOT:?}/$entry"
  done < <(ls -A "$WORKSPACE_ROOT")
}

confund() { # аргумент — причина прерывания; серия помечается CONFUND, выход с кодом 3
  python3 -I - "$OUT" "$POINT" "$SERIES" "$1" <<'EOF'
import json, sys, time
out, point, series, reason = sys.argv[1:5]
row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
       "point": point, "series": series + "-abort",
       "run": "abort", "verdict": "CONFUND", "reason": reason}
open(out, "a").write(json.dumps(row, ensure_ascii=False) + "\n")
EOF
  echo "СЕРИЯ ПРЕРВАНА (CONFUND): $1"
  echo "Серия не засчитывается (правило R5). Переименуйте файлы артефактов (jsonl, run*.txt, meta)"
  echo "с суффиксом _confund — данные сохранятся, метка серии освободится — и перезапустите серию с той же меткой."
  exit 3
}

# --- Основной цикл серии ----------------------------------------------------
SLOW_STREAK=0
for i in $(seq 1 "$NRUNS"); do
  reset_fixture
  RUNFILE=$RESULTS/check_${POINT}_${SERIES}_run$i.txt
  t0=$(date +%s)
  docker exec hermes hermes chat --in /workspace/exp5_check -q "$PROMPT" -Q --yolo --run-budget 180 > "$RUNFILE" 2>&1
  RC=$?
  t1=$(date +%s)
  # Сессия считается стартовавшей, только если в выводе есть её идентификатор.
  SID=$(grep -oE '[0-9]{8}_[0-9]{6}_[a-f0-9]{6}' "$RUNFILE" | head -1)
  [ -n "$SID" ] || confund "прогон $i: в выводе нет идентификатора сессии — сессия не стартовала (код возврата docker exec: $RC)"
  [ "$RC" -eq 0 ] || echo "предупреждение: прогон $i завершился с кодом $RC от docker exec (сессия стартовала, серия продолжается)"
  LAT=$((t1 - t0))
  # Два длинных прогона подряд — признак зависания стека; серия прерывается.
  if [ "$LAT" -gt 600 ]; then
    SLOW_STREAK=$((SLOW_STREAK + 1))
    echo "предупреждение: прогон $i длился ${LAT} секунд (больше 600)"
    if [ "$SLOW_STREAK" -ge 2 ]; then
      confund "два прогона подряд дольше 600 секунд (§7.6) — нужна пауза и диагностика"
    fi
  else
    SLOW_STREAK=0
  fi

  # Проверка артефакта обоими режимами на хосте (§5).
  GODEF=$(cd "$CHECK" && go run script.go 2>&1)
  GONAME=$(cd "$CHECK" && go run script.go --name=Ivan 2>&1)
  SHA=$(sha256sum "$CHECK/script.go" | cut -d' ' -f1)
  RSHA=$(sha256sum "$ROOT_GO" | cut -d' ' -f1)
  EXTRA=$(ls "$CHECK" | grep -v '^script\.go$' | tr '\n' ' ')
  if [ "$SHA" = "$PRISTINE_SHA" ]; then
    VERDICT=INVALID
  elif [ "$GODEF" = "Hello, world!" ] && [ "$GONAME" = "Hello, Ivan!" ]; then
    VERDICT=PASS
  else
    VERDICT=FAIL
  fi
  CWD_CHANGED=False; [ "$SHA" != "$PRISTINE_SHA" ] && CWD_CHANGED=True
  ROOT_CHANGED=False; [ "$RSHA" != "$PRISTINE_SHA" ] && ROOT_CHANGED=True
  GODEF_OK=False; [ "$GODEF" = "Hello, world!" ] && GODEF_OK=True
  GONAME_OK=False; [ "$GONAME" = "Hello, Ivan!" ] && GONAME_OK=True
  ROOTLS=$(ls -A "$WORKSPACE_ROOT" | tr '\n' ' ')
  python3 -I - "$OUT" <<EOF
import json, sys, time
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "point": "$POINT", "series": "$SERIES", "run": "r$i",
    "session_id": "$SID",
    "latency_s": $LAT,
    "verdict": "$VERDICT",
    "go_default_ok": $GODEF_OK,
    "go_name_ok": $GONAME_OK,
    "cwd_changed": $CWD_CHANGED,
    "root_changed": $ROOT_CHANGED,
    "extra_files": "$EXTRA",
    "root_files": "$ROOTLS",
}
open(sys.argv[1], "a").write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"$POINT/$SERIES прогон $i: $VERDICT, ${LAT} с, сессия $SID, корень изменён: $ROOT_CHANGED, посторонние файлы: '$EXTRA'", flush=True)
EOF
done

echo "=== серия $POINT/$SERIES завершена ==="
python3 -I - "$OUT" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
v = {}
for r in rows: v[r["verdict"]] = v.get(r["verdict"], 0) + 1
print(f"итого: {len(rows)} строк, вердикты: {v}")
EOF
echo "далее: разобрать провалы по файлам вывода (§7, шаг 3), занести серию в реестр §9.3, затем: python3 -I analyze_repeats.py scan"
