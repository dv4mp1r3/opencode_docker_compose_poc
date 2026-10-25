#!/usr/bin/env bash
# Контрольная серия δ: q8_0/q8_0 KV @ -c 131072 (N=38) → 13 канонических прогонов ПОДРЯД без пауз.
# Развилка ζ/δ решена: ζ 7/13 ⇒ виноват q5_1-квант; δ — кандидат в рабочую точку (ожидание 13/13).
# Протокол идентичен c-серии: изолированная директория, канон задачи A,
# reset fixture (exp5_check + корневой script.go) перед каждым прогоном,
# верификация обоих режимов на хосте, вердикт в jsonl.
# Фиксы против check_c_loop.sh: python-литералы True/False вместо bash-true/false.
set -u
CHECK=/home/username1/opencode_poc/workspace/exp5_check
ROOT_GO=/home/username1/opencode_poc/workspace/script.go
RESULTS=/home/username1/opencode_poc/5_llama_start_args_experiment/results
OUT=$RESULTS/check_delta_series.jsonl
PRISTINE_SHA=ec0eefc0a67c60dc61a585554d322754bbd74fe849b893aa84764ba984e9239f
PROMPT='Добавь флаг --name (по умолчанию "world"), значение должно подставляться в приветствие вместо захардкоженного "world".'

reset_fixture() {
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$CHECK/script.go"
  find "$CHECK" -mindepth 1 -not -name script.go -delete
  printf 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n' > "$ROOT_GO"
}

: > "$OUT"
for i in $(seq 1 13); do
  reset_fixture
  t0=$(date +%s)
  docker exec hermes hermes chat --in /workspace/exp5_check -q "$PROMPT" -Q --yolo --run-budget 180 > "$RESULTS/check_delta_run$i.txt" 2>&1
  t1=$(date +%s)
  SID=$(grep -oE '[0-9]{8}_[0-9]{6}_[a-f0-9]{6}' "$RESULTS/check_delta_run$i.txt" | head -1)
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
  python3 -I - "$OUT" <<EOF
import json, sys, time
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "run": "d$i",
    "session_id": "$SID",
    "latency_s": $((t1 - t0)),
    "verdict": "$VERDICT",
    "go_default_ok": $GODEF_OK,
    "go_name_ok": $GONAME_OK,
    "cwd_changed": $CWD_CHANGED,
    "root_changed": $ROOT_CHANGED,
    "extra_files": "$EXTRA",
}
open(sys.argv[1], "a").write(json.dumps(row) + "\n")
print(f"d$i: $VERDICT latency=$((t1-t0))s sid=$SID root_changed=$ROOT_CHANGED extra='$EXTRA'", flush=True)
EOF
done
echo "=== серия δ завершена ==="
python3 -I - "$OUT" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
v = {}
for r in rows: v[r["verdict"]] = v.get(r["verdict"], 0) + 1
print(f"итого: {len(rows)} прогонов, вердикты: {v}")
EOF