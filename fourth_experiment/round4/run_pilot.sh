#!/bin/sh
# Пилотный прогон раунда 4: сброс фикстуры → полный цикл гейта (агент + верификация).
# Использование: run_pilot.sh <run_id> [max_iterations]   (по умолчанию 3)
# Отчёт: fourth_experiment/round4/reports/gate_report_<run_id>.json
# Выход гейта: 0 PASS, 1 FAIL/CONSTRAINT_VIOLATED, 2 preflight (фикстура грязная).
set -eu
cd "$(dirname "$0")/../.."

RUN_ID="${1:?usage: run_pilot.sh <run_id> [max_iterations]}"
MAX="${2:-3}"

fourth_experiment/round4/reset_fixture.sh

mkdir -p fourth_experiment/round4/reports
python3 -I fourth_experiment/verify_gate.py \
  --spec fourth_experiment/round4/spec_task_e.json \
  --max-iterations "$MAX" \
  --report "fourth_experiment/round4/reports/gate_report_${RUN_ID}.json"
