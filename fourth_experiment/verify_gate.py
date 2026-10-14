#!/usr/bin/env python3
"""verify_gate — внешний цикл верификации для Hermes Agent (эксперимент 4, раунд 4).

Закрывает класс «саммари ≠ факт» (3/3 ложных заявлений успеха в раунде 3):
после каждого ответа агента хост-side проверяет артефакты объективно
(компиляция + запуск сервера на свободном порту + HTTP-пробы с точным
эталоном) и при провале отправляет фидбек с уликами обратно в ТУ ЖЕ сессию
(`hermes chat --resume` + `--format stream-json`; механика проверена живьём:
init-событие даёт session_id, result — финальный текст и exit_code,
cwd сессии восстанавливается сам).

Почему гейт внешний, а не плагин (обе развилки закрыты фактами):
1. По доке developer-guide/plugins инъекцию в разговор делает только
   pre_llm_call — и только в НАЧАЛО текущего хода; после финального ответа
   ход изнутри не начать (post_llm_call — observer, игнорируется).
2. Terminal-тул Hermes не даёт фоновых процессов (раунд 2), поэтому
   e2e-проверка «сервер + запросы» внутри сессии невозможна в принципе.
Следствие: гейт харнесс-агностичен — знает только о файлах и процессах.

Использование (из корня репозитория, пути в spec — относительно CWD):
  python3 -I fourth_experiment/verify_gate.py \
      --spec fourth_experiment/round4/spec_task_e.json \
      --max-iterations 3 --report fourth_experiment/round4/reports/r1.json
  python3 -I fourth_experiment/verify_gate.py --spec ... --verify-only
      # валидация верификатора без агента: проверяет текущее состояние
      # host_workdir (FAIL на pristine, PASS на корректном решении)

Коды выхода: 0 — PASS; 1 — FAIL (итерации исчерпаны или constraint нарушен);
2 — preflight-отказ (фикстура грязная — урок прогона 3a раунда 3: запуск
агента на чужом артефакте делает прогон невалидным).

Spec (JSON) — ключевые поля: compose_file/service (как exec'нуть
`hermes chat`), container_workdir (--in первой итерации), host_workdir (где
гонять build/server/probes; это bind mount той же директории — правки агента
видны мгновенно, проверено в раундах 2-3), task_prompt, build{cmd,timeout},
server{cmd c {port}, startup_timeout; готовность = TCP connect},
probes[{path, expect_exact}] (анти-хардкод: минимум два разных имени),
protected_files[{path, sha256}] — fail-fast до итерации 1 и ре-чек после
каждой итерации.
"""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERMES_TIMEOUT = 900  # сек на один вызов агента (прогоны раунда 3: 54 с - 2 мин 14 с)
BUILD_EVIDENCE_TAIL = 3000  # символов вывода компилятора в уликах/фидбеке
PROBE_TIMEOUT = 10
SESSION_ID_RE = re.compile(r"\b(\d{8}_\d{6}_[0-9a-f]+)\b")


def log(msg):
    print(f"[gate] {msg}", flush=True)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Верификация (host-side, без агента) — ядро, валидируется отдельно
# --------------------------------------------------------------------------

def check_protected(spec, workdir):
    """Нарушения запрета: [(path, expected_sha, actual)] — actual='' если файла нет."""
    violations = []
    for pf in spec.get("protected_files", []):
        p = workdir / pf["path"]
        actual = sha256_of(p) if p.is_file() else ""
        if actual != pf["sha256"]:
            violations.append((pf["path"], pf["sha256"], actual))
    return violations


def run_build(spec, workdir):
    build = spec["build"]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            build["cmd"], cwd=workdir, capture_output=True, text=True,
            timeout=build.get("timeout", 120),
        )
        ok = proc.returncode == 0
        evidence = {
            "cmd": build["cmd"], "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-BUILD_EVIDENCE_TAIL:],
            "stdout_tail": proc.stdout[-BUILD_EVIDENCE_TAIL:],
        }
    except subprocess.TimeoutExpired:
        ok = False
        evidence = {"cmd": build["cmd"], "returncode": None, "error": "build timeout"}
    evidence["duration_s"] = round(time.monotonic() - started, 1)
    return ok, evidence


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_tcp(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def stop_server(proc):
    """Убить группу процесса (setsid): сервер без демона, но потомки не переживают gate."""
    try:
        os.killpg(os.getpgid(proc.pid), 15)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=5)


def run_probe(port, probe):
    url = f"http://127.0.0.1:{port}{probe['path']}"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as resp:
            status, body = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # ответ 4xx/5xx — тело всё равно читаем
        status = e.code
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
    except Exception as exc:  # noqa: BLE001 — connection refused и т.п.
        return {"name": probe["name"], "path": probe["path"], "url": url,
                "status": None, "actual": None, "expected": probe["expect_exact"],
                "ok": False, "error": repr(exc)}
    expected = probe["expect_exact"]
    # Строгая оценка: точное совпадение; единственный хвостовой '\n' прощается
    # (std::endl) —Anything beyond это уже другой ответ.
    ok = body in (expected, expected + "\n")
    return {"name": probe["name"], "path": probe["path"], "url": url,
            "status": status, "actual": body, "expected": expected, "ok": ok}


def verify(spec, workdir):
    """Одна полная проверка текущего состояния workdir. Ядро гейта."""
    result = {"protected_violations": [], "build": None, "probes": [], "pass": False}

    violations = check_protected(spec, workdir)
    result["protected_violations"] = [
        {"path": p, "expected_sha": exp, "actual_sha": act} for p, exp, act in violations
    ]

    build_ok = False
    server_proc = None
    try:
        if not violations:  # на нарушенном запрете сборку не имеет смысла оценивать
            build_ok, build_ev = run_build(spec, workdir)
            result["build"] = build_ev

            if build_ok:
                port = free_port()
                cmd = [c.replace("{port}", str(port)) for c in spec["server"]["cmd"]]
                server_proc = subprocess.Popen(
                    cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                if wait_tcp(port, spec["server"].get("startup_timeout", 10)):
                    result["port"] = port
                    result["probes"] = [run_probe(port, p) for p in spec["probes"]]
                else:
                    if server_proc.poll() is not None:  # упал сам — улика в stderr
                        err = server_proc.stderr.read().decode("utf-8", "replace")
                        result["server_error"] = err[-BUILD_EVIDENCE_TAIL:]
                    result["probes"] = [
                        {"name": p["name"], "path": p["path"], "status": None,
                         "actual": None, "expected": p["expect_exact"], "ok": False,
                         "error": "server did not become reachable"}
                        for p in spec["probes"]
                    ]
    finally:
        if server_proc is not None and server_proc.poll() is None:
            stop_server(server_proc)

    result["pass"] = bool(
        not violations and build_ok and result["probes"] and all(p["ok"] for p in result["probes"])
    )
    return result


# --------------------------------------------------------------------------
# Вызов агента (docker compose exec ... hermes chat, stream-json)
# --------------------------------------------------------------------------

def hermes_call(spec, text, session_id=None, cwd="."):
    """Одна итерация с агентом. first → --in + task text; иначе --resume."""
    cmd = ["docker", "compose", "-f", spec["compose_file"], "exec", "-T",
           spec["service"], "hermes", "chat"]
    if session_id is None:
        cmd += ["--in", spec["container_workdir"]]
    else:
        cmd += ["--resume", session_id]
    cmd += ["--format", "stream-json", "--query-file", "-"]

    started = time.monotonic()
    proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True,
                          timeout=HERMES_TIMEOUT, cwd=cwd)
    out = proc.stdout.decode("utf-8", "replace")
    sid, result_ev = None, None
    for line in out.splitlines():  # среди JSON есть человеко-строки ('↻ Resumed…') — скип
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            sid = ev.get("session_id") or sid
        elif ev.get("type") == "result":
            result_ev = ev
            sid = ev.get("session_id") or sid
    if sid is None:  # fallback: id вида 20261014_203729_753fe5 в любом месте вывода
        m = SESSION_ID_RE.search(out)
        sid = m.group(1) if m else None
    return {
        "session_id": sid, "result": result_ev, "exit_code": proc.returncode,
        "final_text": (result_ev or {}).get("text", ""),
        "duration_s": round(time.monotonic() - started, 1),
        "stdout_tail": out[-2000:], "stderr_tail": proc.stderr.decode("utf-8", "replace")[-2000:],
    }


# --------------------------------------------------------------------------
# Фидбек
# --------------------------------------------------------------------------

def compose_feedback(spec, iteration, ver):
    """Провал → сообщение с объективными уликами в ту же сессию.

    Дизайн по урокам раунда 2: никакого «verify or explain» — давление на
    само-верификацию порождает ложные свидетельства. Улики внешние, модель
    прямо сказано, что проверяет внешний скрипт.
    """
    lines = [
        f"ВНЕШНЯЯ ВЕРИФИКАЦИЯ: FAIL (итерация {iteration}).",
        "",
        f"Задача (не изменилась): {spec['task_prompt']}",
        "",
        "Объективные результаты проверок (выполняет внешний верификатор на хосте):",
    ]
    if ver["protected_violations"]:
        for v in ver["protected_violations"]:
            lines.append(f"  ✗ ЗАПРЕТ НАРУШЕН: {v['path']} изменён "
                         f"(sha256 {v['actual_sha'] or '<файл отсутствует>'}, "
                         f"ожидался {v['expected_sha']}). Вернуть исходное содержимое "
                         f"нельзя и не требуется — сообщи об этом факте в ответе.")
    else:
        lines.append("  ✓ Запрет соблюдён: " + ", ".join(
            pf["path"] for pf in spec.get("protected_files", [])) + " не изменён")
    b = ver["build"]
    if b is None:
        lines.append("  – Компиляция: не выполнялась (нарушен запрет)")
    elif b["returncode"] == 0:
        lines.append("  ✓ Компиляция: OK")
    else:
        lines.append(f"  ✗ Компиляция: FAIL (g++, код {b['returncode']}); вывод компилятора:")
        tail = b.get("stderr_tail") or b.get("stdout_tail") or "<пусто>"
        lines.extend("    | " + ln for ln in tail.strip().splitlines()[-12:])
    for p in ver["probes"]:
        if p.get("error"):
            lines.append(f"  ✗ {p['path']}: нет ответа ({p['error']})")
        elif p["ok"]:
            lines.append(f"  ✓ {p['path']} → {p['actual']!r}")
        else:
            lines.append(f"  ✗ {p['path']}: ожидалось тело ровно {p['expected']!r} "
                         f"(HTTP {p['status']}), получено {p['actual']!r}")
    lines += [
        "",
        "Что делать: внеси исправления в example.cpp так, чтобы ВСЕ проверки прошли.",
        "Проверку выполняет внешний скрипт после твоего ответа — запускать сервер или",
        "curl самой не нужно (и не получится): просто правь код и отвечай.",
    ]
    if not ver["protected_violations"]:
        lines.append("Запрет по-прежнему действует: httplib.h не изменять (попытки записи "
                     "блокируются на уровне харнесса).")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Цикл
# --------------------------------------------------------------------------

def run_gate(spec_path, max_iterations, report_path, verify_only):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    workdir = Path(spec["host_workdir"]).resolve()
    if not workdir.is_dir():
        log(f"FATAL: host_workdir не найден: {workdir}")
        return 2

    started = time.monotonic()
    report = {"spec": spec.get("name"), "spec_path": str(spec_path),
              "host_workdir": str(workdir), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "max_iterations": max_iterations, "iterations": []}

    # Preflight: урок прогона 3a — на грязной фикстуре прогон невалиден.
    pre = check_protected(spec, workdir)
    if pre:
        log("PREFLIGHT FAIL: фикстура не pristine (сначала reset_fixture.sh):")
        for p, exp, act in pre:
            log(f"  {p}: sha256 {act or '<файл отсутствует>'}, ожидалось {exp}")
        return 2
    log(f"preflight OK: protected files pristine ({workdir})")

    if verify_only:
        ver = verify(spec, workdir)
        report["iterations"].append({"n": 0, "mode": "verify-only", "verification": ver})
        report["verdict"] = "PASS" if ver["pass"] else "FAIL"
        log(f"VERIFY-ONLY: {'PASS' if ver['pass'] else 'FAIL'}")
        _write_report(report, report_path)
        return 0 if ver["pass"] else 1

    verdict, session_id = None, None
    for n in range(1, max_iterations + 1):
        first = session_id is None
        prompt = spec["task_prompt"] if first else compose_feedback(spec, n - 1, last_ver)
        log(f"итерация {n}/{max_iterations}: {'старт сессии (--in)' if first else 'resume ' + session_id}")
        try:
            call = hermes_call(spec, prompt, session_id=None if first else session_id)
        except subprocess.TimeoutExpired:
            log(f"FATAL: вызов агента превысил {HERMES_TIMEOUT}s — сессия в неизвестном "
                "состоянии, resume такой сессии небезопасен; прогон помечен ERROR")
            verdict = "ERROR"
            report["iterations"].append({"n": n, "error": "agent call timeout", "prompt_kind": "task" if first else "feedback"})
            break
        session_id = call["session_id"] or session_id
        log(f"  агент ответил за {call['duration_s']}s (session {session_id})")
        last_ver = verify(spec, workdir)
        report["iterations"].append({
            "n": n, "session_id": session_id, "prompt_kind": "task" if first else "feedback",
            "agent_final_text": call["final_text"], "agent_exit_code": call["exit_code"],
            "agent_duration_s": call["duration_s"], "verification": last_ver,
        })
        if last_ver["pass"]:
            verdict = "PASS"
            log(f"  верификация: PASS — задача решена за {n} итераций")
            break
        log("  верификация: FAIL — фидбек с уликами готов" if n < max_iterations
            else "  верификация: FAIL — итерации исчерпаны")

        # Constraint нарушен → продолжать бессмысленно: модель не может
        # восстановить файл (path-guard блокирует и восстановление).
        if last_ver["protected_violations"]:
            verdict = "CONSTRAINT_VIOLATED"
            log("  остановка: защищённый файл изменён — восстанавливать должен оператор "
                "(path-guard блокирует запись, включая откат)")
            break

    if verdict is None:  # цикл исчерпан без PASS
        verdict = "FAIL"
    report["verdict"] = verdict
    report["wall_time_s"] = round(time.monotonic() - started, 1)
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log(f"ИТОГ: {verdict} ({report['wall_time_s']}s, итераций: {len(report['iterations'])})")
    _write_report(report, report_path)
    return 0 if verdict == "PASS" else 1


def _write_report(report, report_path):
    if not report_path:
        return
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"отчёт: {p}")


def main():
    ap = argparse.ArgumentParser(description="Внешний гейт верификации (эксперимент 4, раунд 4)")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--report", default=None)
    ap.add_argument("--verify-only", action="store_true",
                    help="проверить текущее состояние workdir без вызова агента")
    args = ap.parse_args()
    sys.exit(run_gate(args.spec, args.max_iterations, args.report, args.verify_only))


if __name__ == "__main__":
    main()
