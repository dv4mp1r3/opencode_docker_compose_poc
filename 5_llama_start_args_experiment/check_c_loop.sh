#!/usr/bin/env bash
# Добор канонического чека (c) q5_1 до N=13 валидных прогонов (c4..c13).
# Протокол идентичен ручным c1/c2/c3/c2': изолированная директория,
# канон задачи A, fixture reset перед каждым прогоном (включая корневой
# script.go — конфаунд c2), верификация обоих режимов на хосте.
set -u
CHECK=/home/username1/opencode_poc/workspace/exp5_check
ROOT_GO=/home/username1/opencode_poc/workspace/script.go
RESULTS=/home/username1/opencode_poc/5_llama_start_args_experiment/results
OUT=$RESULTS/check_c_q51_series.jsonl
PRISTINE_SHA=ec0eefc0a67c60dc61a585554d322754bbd74fe849b893aa84764ba984e9239f
PROMPT='Добавь флаг --name (по умолчанию "world"), значение должно подставляться в приветствие вместо захардкоженного "world".'

reset_fixture() {
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$CHECK/script.go"
  rm -f "$CHECK/script.py" "$CHECK/main.py"
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$ROOT_GO"
}

mkdir -p "$RESULTS"
for i in $(seq 4 13); do
  reset_fixture
  t0=$(date +%s)
  docker exec hermes hermes chat --in /workspace/exp5_check -q "$PROMPT" -Q --yolo --run-budget 180 > "$RESULTS/check_c_q51_run$i.txt" 2>&1
  t1=$(date +%s)
  SID=$(grep -oE '[0-9]{8}_[0-9]{6}_[a-f0-9]{6}' "$RESULTS/check_c_q51_run$i.txt" | head -1)
  GODEF=$(cd "$CHECK" && go run script.go 2>&1)
  GONAME=$(cd "$CHECK" && go run script.go --name=Ivan 2>&1)
  SHA=$(sha256sum "$CHECK/script.go" | cut -d' ' -f1)
  RSHA=$(sha256sum "$ROOT_GO" | cut -d' ' -f1)
  EXTRA=$(ls "$CHECK" | grep -v '^script\.go$' | tr '\n' ' ')
  if [ "$SHA" = "$PRISTINE_SHA" ]; then
    VERDICT=INVALID   # правка ушла из cwd (или её нет)
  elif [ "$GODEF" = "Hello, world!" ] && [ "$GONAME" = "Hello, Ivan!" ]; then
    VERDICT=PASS
  else
    VERDICT=FAIL
  fi
  CWD_CHANGED=false; [ "$SHA" != "$PRISTINE_SHA" ] && CWD_CHANGED=true
  ROOT_CHANGED=false; [ "$RSHA" != "$PRISTINE_SHA" ] && ROOT_CHANGED=true
  python3 -I - "$OUT" <<EOF
import json, sys, time
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "run": "c$i",
    "session_id": "$SID",
    "latency_s": $((t1 - t0)),
    "verdict": "$VERDICT",
    "go_default_ok": $([ "$GODEF" = "Hello, world!" ] && echo true || echo false),
    "go_name_ok": $([ "$GONAME" = "Hello, Ivan!" ] && echo true || echo false),
    "cwd_changed": $CWD_CHANGED,
    "root_changed": $ROOT_CHANGED,
    "extra_files": "$EXTRA",
}
open(sys.argv[1], "a").write(json.dumps(row) + "\n")
print(f"c$i: $VERDICT latency={t1-t0}s sid=$SID root_changed=$ROOT_CHANGED extra='$EXTRA'")
EOF
done
echo "=== серия завершена ==="
python3 -I - "$OUT" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
v = {}
for r in rows: v[r["verdict"]] = v.get(r["verdict"], 0) + 1
print(f"итого серийных прогонов: {len(rows)}, вердикты: {v}")
EOF