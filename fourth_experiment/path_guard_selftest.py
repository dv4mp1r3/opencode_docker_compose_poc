#!/usr/bin/env python3
"""Host-side self-test плагина path-guard (эксперимент 4, раунд 3).

Обязателен перед любым прогоном: документированная семантика хуков Hermes —
fail-open (исключение в коллбеке = залогировано + тул исполняется), поэтому
сломанный хук неотличим снаружи от его отсутствия. Здесь проверяется сам
контракт: блок/разрешение/ложноположительные/фолбэки.

Запуск: python3 -I fourth_experiment/path_guard_selftest.py
Лог событий во время теста пишется во временный файл (дерево плагина не
засоряется).
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "config" / "hermes" / "plugins" / "path-guard" / "__init__.py"

_tmpdir = tempfile.mkdtemp(prefix="path-guard-selftest-")
os.environ["HERMES_PATH_GUARD_LOG"] = str(Path(_tmpdir) / "events.jsonl")

_spec = importlib.util.spec_from_file_location("path_guard", PLUGIN)
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)

PASS = 0
FAILS = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}")


def blocked(result):
    return isinstance(result, dict) and result.get("action") == "block"


def wtool(tool, path, extra=None):
    return pg._pre_tool_call(tool, {"path": path, **(extra or {})}, None)


def term(cmd):
    return pg._pre_tool_call("terminal", {"command": cmd}, None)


print("== write-тулы: блок по защищённому пути (варианты написания) ==")
for p in ["httplib.h", "./httplib.h", "/workspace/t/httplib.h", "dep/httplib.h"]:
    check(f"patch {p} → block", blocked(wtool("patch", p)))
check("write_file file_path=httplib.h → block",
      blocked(pg._pre_tool_call("write_file", {"file_path": "httplib.h", "content": "x"}, None)))

print("== write-тулы: ложноположительные недопустимы ==")
# Правка легального файла, в чьём контенте упоминается защищённый — не блок.
r = wtool("patch", "example.cpp", {"content": '--- example.cpp\n+++ example.cpp\n+#include "httplib.h"\n'})
check("patch example.cpp (контент упоминает httplib.h) → allow", r is None)
r = pg._pre_tool_call("read_file", {"path": "httplib.h"}, None)
check("read_file httplib.h → allow", r is None)
r = pg._pre_tool_call("search_files", {"query": "httplib"}, None)
check("search_files → allow", r is None)

print("== terminal: блок write-образных команд ==")
for cmd in [
    "sed -i 's/old/new/' httplib.h",
    "sed -ie 's/old/new/' httplib.h",
    "sed -i.bak 's/old/new/' httplib.h",
    "perl -pi -e 's/old/new/' httplib.h",
    "echo hacked > httplib.h",
    "echo hacked >> httplib.h",
    "g++ x.cpp 2> httplib.h",
    "cat tpl | tee httplib.h",
    "cp /tmp/x httplib.h",
    "mv example.cpp httplib.h",
    "rm httplib.h",
    "chmod 644 httplib.h",
    "touch httplib.h",
    "truncate -s 0 httplib.h",
    "patch -p0 httplib.h < fix.diff",
    "dd if=/dev/zero of=httplib.h bs=1 count=1",
    'python3 -c "open(\'httplib.h\',\'a\').write(\'x\')"',
    "ln -sf /tmp/x httplib.h",
]:
    check(f"block: {cmd}", blocked(term(cmd)))

print("== terminal: чтение/легальные команды не блокируются ==")
for cmd in [
    "cat httplib.h",
    "grep -i ivan httplib.h",
    "grep -in name httplib.h",
    "sed -n '1,50p' httplib.h",
    "diff httplib.h /tmp/httplib.h",
    "sha256sum httplib.h",
    "wc -l httplib.h",
    "cp httplib.h /tmp/backup",
    "g++ -std=c++11 example.cpp -o srv",
    "cat httplib.h > /dev/null",
    "echo preparing > /tmp/notes.txt",
]:
    check(f"allow: {cmd}", term(cmd) is None)

print("== env-переопределение набора спецификаций ==")
os.environ["HERMES_PATH_GUARD_DENY"] = "secret.pem,dep/httplib.h"
check("override: patch secret.pem → block", blocked(wtool("patch", "secret.pem")))
check("override: patch httplib.h (basename, не в наборе) → allow", wtool("patch", "httplib.h") is None)
check("override: patch dep/httplib.h (путевая spec) → block", blocked(wtool("patch", "dep/httplib.h")))
del os.environ["HERMES_PATH_GUARD_DENY"]  # вернуть дефолт для следующих проверок

print("== устойчивость (fail-open не должен прятать ошибки от лога) ==")
check("args=None → allow", pg._pre_tool_call("patch", None, None) is None)
check("не-словарь args → allow", pg._pre_tool_call("patch", ["x"], None) is None)
check("пустой tool_name → allow", pg._pre_tool_call(None, {"path": "httplib.h"}, None) is None)

print("== контракт возврата и лог ==")
r = wtool("patch", "httplib.h")
check("block-ответ содержит message", bool(r.get("message")))
log = Path(_tmpdir, "events.jsonl").read_text().splitlines()
events = [json.loads(x) for x in log]
kinds = {e["event"] for e in events}
check("лог содержит block", "block" in kinds)
check("лог содержит allow_write_tool", "allow_write_tool" in kinds)
check("лог содержит terminal_observed", "terminal_observed" in kinds)
check("нет callback_error", "callback_error" not in kinds)

print()
if FAILS:
    print(f"ИТОГ: {PASS} ok, {len(FAILS)} FAIL:")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print(f"ИТОГ: {PASS}/{PASS} ok — хук соответствует контракту")
