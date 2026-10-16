#!/usr/bin/env python3
"""Реконструкция вердиктов серии c4..c13 из экспортов сессий.

Фон: прогоны прошли, но jsonl-запись упала (bash true/false в python-heredoc).
Финальное состояние файлов восстановимо из write/patch tool_calls экспорта;
go-верификация прогоняется в песочнице. execute_code с записью файлов
точной реконструкции не поддаётся — такие сессии помечаются flag_recon.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

RESULTS = "/home/username1/opencode_poc/5_llama_start_args_experiment/results"
OUT = os.path.join(RESULTS, "check_c_q51_series.jsonl")
PRISTINE = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, world!")\n}\n'
RUNS = {
    "c4": "20261016_062333_afc4eb",
    "c5": "20261016_062449_d2b185",
    "c6": "20261016_062510_77ad25",
    "c7": "20261016_062613_bd729f",
    "c8": "20261016_062707_6bf24b",
    "c9": "20261016_062747_ecb0b6",
    "c10": "20261016_062831_d9e641",
    "c11": "20261016_062918_88e2eb",
    "c12": "20261016_063010_61cb77",
    "c13": "20261016_063232_074ff4",
}


def norm_path(p: str):
    """Классификация пути: 'cwd' | 'root' | 'other:<path>'.
    Относительные пути (script.go, ./script.go) — cwd (факт серии c4-c13:
    модель пишет и './script.go', и 'script.go')."""
    p = p.strip()
    if p.startswith("/workspace/exp5_check/"):
        return "cwd"
    if not p.startswith("/") and (not p.startswith("../")):
        return "cwd"  # относительный путь — от --in директории
    if p == "/workspace/script.go":
        return "root"
    return "other:" + p


def export_session(sid: str) -> dict:
    r = subprocess.run(
        ["docker", "exec", "hermes", "hermes", "sessions", "export",
         "--session-id", sid, "--format", "jsonl", "-"],
        capture_output=True, text=True, timeout=120,
    )
    return json.loads(r.stdout)


def reconstruct(sid: str):
    """Возвращает: files {relpath: content}, touched {kind: [paths]}, flags."""
    d = export_session(sid)
    files = {"cwd/script.go": PRISTINE, "root/script.go": PRISTINE}
    touched = {"cwd": [], "root": [], "other": []}
    flags = {"flag_recon": False, "no_tools": True, "tool_count": 0}
    for m in d.get("messages", []):
        for tc in (m.get("tool_calls") or []):
            flags["no_tools"] = False
            flags["tool_count"] += 1
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name in ("write_file", "patch") and isinstance(args, dict):
                kind = norm_path(str(args.get("path", "")))
                if kind.startswith("other"):
                    touched["other"].append(str(args.get("path")))
                    continue
                base = os.path.basename(str(args.get("path", "script.go")))
                key = f"{kind}/{base}"
                if name == "write_file":
                    files[key] = str(args.get("content", ""))
                    touched[kind].append(f"write:{key}")
                else:  # patch
                    cur = files.get(key)
                    old = str(args.get("old_string", ""))
                    new = str(args.get("new_string", ""))
                    if cur is not None and old in cur:
                        files[key] = cur.replace(old, new, 1)
                        touched[kind].append(f"patch:{key}")
                    else:
                        touched[kind].append(f"patch:MISS:{key}")
                        flags["flag_recon"] = True
            elif name == "execute_code":
                code = str((args or {}).get("code", ""))
                if "open(" in code and ("'w'" in code or '"w"' in code):
                    flags["flag_recon"] = True
    return d, files, touched, flags


def go_verify(content: str):
    tmp = tempfile.mkdtemp(prefix="recon_")
    try:
        p = os.path.join(tmp, "script.go")
        with open(p, "w") as f:
            f.write(content)
        outs = []
        for argv in (["go", "run", "script.go"], ["go", "run", "script.go", "--name=Ivan"]):
            r = subprocess.run(argv, cwd=tmp, capture_output=True, text=True, timeout=120)
            outs.append((r.stdout + r.stderr).strip())
        return outs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for run, sid in RUNS.items():
        d, files, touched, flags = reconstruct(sid)
        cwd_final = files.get("cwd/script.go", PRISTINE)
        cwd_changed = cwd_final != PRISTINE
        root_changed = files.get("root/script.go", PRISTINE) != PRISTINE
        if flags["no_tools"]:
            verdict = "FAIL"  # задачу не начала (уточняющий вопрос и т.п.)
            outs = ["", ""]
        elif not cwd_changed and (root_changed or touched["other"]):
            verdict = "INVALID"  # правка ушла из cwd
            outs = ["", ""]
        else:
            outs = go_verify(cwd_final)
            verdict = "PASS" if outs == ["Hello, world!", "Hello, Ivan!"] else "FAIL"
        row = {
            "run": run,
            "session_id": sid,
            "verdict": verdict,
            "reconstructed": True,
            "go_default_ok": outs[0] == "Hello, world!",
            "go_name_ok": outs[1] == "Hello, Ivan!",
            "cwd_changed": cwd_changed,
            "root_changed": root_changed,
            "tool_count": flags["tool_count"],
            "flag_recon": flags["flag_recon"],
            "touched": {k: v for k, v in touched.items() if v},
        }
        with open(OUT, "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{run}: {verdict} tools={flags['tool_count']} cwd_changed={cwd_changed} "
              f"root_changed={root_changed} recon_flag={flags['flag_recon']}")


if __name__ == "__main__":
    main()
