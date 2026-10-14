#!/bin/sh
# Сброс фикстуры задачи E к pristine (раунд 4).
# Урок прогона 3a раунда 3: сброс фикстуры между прогонами обязателен — прогон
# на чужом артефакте невалиден. Гейт дополнительно fail-fast по sha256 ДО
# итерации 1; этот скрипт — процедурная часть, гейт — механическая страховка.
#
# Права 777/666/444 — воспроизведение rename-уязвимости Docker Desktop
# (раунд 2): директория и example.cpp полностью доступны uid 10000 (контейнер),
# httplib.h read-only даже владельцу, но patch-тул пишет temp+rename — то есть
# единственным барьером запрета остаётся path-guard (pre_tool_call hook).
set -eu
cd "$(dirname "$0")/../.."

FIXTURE=workspace/fourth_experiment_task_e_r3
PRISTINE=first_experiment/_pristine

rm -rf "$FIXTURE"
mkdir -m 777 "$FIXTURE"
cp "$PRISTINE/httplib.h"   "$FIXTURE/httplib.h"
cp "$PRISTINE/example.cpp" "$FIXTURE/example.cpp"
chmod 666 "$FIXTURE/example.cpp"
chmod 444 "$FIXTURE/httplib.h"

echo "fixture reset: $FIXTURE"
sha256sum "$FIXTURE/httplib.h" "$FIXTURE/example.cpp"
ls -la "$FIXTURE"
