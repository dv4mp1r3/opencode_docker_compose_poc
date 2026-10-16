#!/usr/bin/env python3
"""Замер prefill/decode скорости llama-server при заданных длинах промпта.

Эндпоинт — нативный /completion (поле timings; у /v1/chat/completions
timing-полей нет — факт раунда 5 эксп. 4). Запускать с машины-клиента,
не с GPU-хоста. VRAM меряется отдельно на хосте:
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -l 2 > vram_<label>.log

Протокол на каждую цель (5_llama_start_args_experiment/PLAN.md):
  1) fit: 1-3 запроса n_predict=1 — подгонка фактического prompt_n под цель
     с точностью до 2%; каждый fit-запрос попутно является prefill-замером;
  2) decode cold: тот же промпт, n_predict=N, cache_prompt=false — prefill + decode;
  3) decode warm x (repeats-1): тот же промпт, cache_prompt=true — чистый decode
     (prefill почти мгновенно берётся из кэша префикса слота).

Цель (target) должна быть МЕНЬШЕ -c сервера на ≥4096: KV-слот вмещает
промпт + генерацию, полный -c промптом не замеряется. Правило: target = -c − 4096.

Примеры:
  python3 -I 5_llama_start_args_experiment/bench_ctx.py --label e0_64k_ncm10 --targets 61440
  python3 -I 5_llama_start_args_experiment/bench_ctx.py --label e2_q5_1 --targets 196608 --prefill-only
  python3 -I 5_llama_start_args_experiment/bench_ctx.py --label e3_cache --cache-ab
"""

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
import os

# Шаблоны псевдо-кода: различающиеся строки с уникальными номерами и словами из
# словаря — чтобы текст не вырождался в повтор (токенизация близка к реальному коду).
TEMPLATES = [
    "static inline int32_t fn_{i}(const uint8_t *buf, size_t len) {{ return (int32_t)(buf[{j} % (len ? len : 1)]) + {k}; }}",
    "/* {w} {w2}: validate that field_{i} == expected_{j} before committing the transaction */",
    "if (unlikely(state_{i} == STATE_{J} && !retry_{i})) {{ log_warn(\"{w} failed at step {j}\"); return -EIO; }}",
    "struct config_{w}_{i} {{ uint32_t magic; uint16_t version; char name[64]; struct {w2}_ops *ops; }};",
    "def handle_{w}_{i}(request):  # {w2} path handler, returns json response or None on error_{j}",
    "assert results_{i} == golden_{j}, f\"{w} mismatch: got {{results_{i}}}, want {{golden_{j}}}\"",
    "self.{w}_cache[{i}] = lru_cache(maxsize={k})({w2}_compute)  # {J} eviction policy",
]
WORDS = [
    "buffer", "checksum", "session", "handler", "runtime", "pool", "worker",
    "snapshot", "backoff", "telemetry", "pipeline", "fragment", "throttle",
    "deadlock", "watchdog", "cursor", "barrier", "manifest", "shard", "ledger",
]

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def gen_text(n_chars: int, rng: random.Random) -> str:
    parts, total, i = [], 0, 0
    while total < n_chars:
        t = rng.choice(TEMPLATES)
        line = t.format(
            i=i, j=rng.randrange(10 ** 6), k=rng.randrange(10 ** 5),
            w=rng.choice(WORDS), w2=rng.choice(WORDS), J=rng.choice(WORDS).upper(),
        )
        parts.append(line)
        total += len(line) + 1
        i += 1
    return "\n".join(parts)


def query(base: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        base + "/completion",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def timings(r: dict) -> dict:
    t = r.get("timings", {})
    return {
        "prompt_n": t.get("prompt_n"),
        "prompt_ms": t.get("prompt_ms"),
        "prompt_per_second": t.get("prompt_per_second"),
        "predicted_n": t.get("predicted_n"),
        "predicted_ms": t.get("predicted_ms"),
        "predicted_per_second": t.get("predicted_per_second"),
    }


def record(out, label, phase, target, cache_prompt, t, note=None):
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "phase": phase,
        "target": target,
        "cache_prompt": cache_prompt,
        **t,
    }
    if note:
        row["note"] = note
    out.write(json.dumps(row) + "\n")
    out.flush()


def die(out, label, target, msg: str):
    record(out, label, "error", target, None, {}, note=msg[:500])
    print(f"ERROR [{label} target={target}]: {msg}", file=sys.stderr)
    sys.exit(2)


def normalize_base(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


def run_target(base, out, args, target):
    label = args.label
    print(f"=== [{label}] target={target} tokens ===")
    try:
        props = json.loads(OPENER.open(base + "/props", timeout=30).read().decode())
        n_ctx = props.get("default_generation_settings", {}).get("n_ctx")
        if n_ctx and target + args.n_predict + 32 > n_ctx:
            print(f"  WARNING: target({target}) + n_predict({args.n_predict}) почти/выше "
                  f"n_ctx({n_ctx}) — генерация будет обрезана (t/s не искажается, но "
                  f"чистый decode-замер лучше при target = n_ctx − 4096)")
    except Exception:
        pass  # /props недоступен — не критично
    rng = random.Random(args.seed + target)
    # стартовая оценка для этого генератора: 2.83 симв/токен (факт, замер
    # 2026-10-16 по n_prompt_tokens из ошибки exceed_context_size сервера)
    est_chars = int(target * 2.83)
    text, achieved = None, None
    for attempt in range(1, 4):
        text = gen_text(est_chars, rng)
        try:
            r = query(base, {"prompt": text, "n_predict": 1, "cache_prompt": False,
                             "temperature": 0, "seed": args.seed}, args.timeout)
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code == 400 and b"n_prompt_tokens" in body:
                # промпт вылез за -c сервера: сервер сам сообщает фактическую
                # токенизацию — это точнее любой оценки, пересчитываем и продолжаем
                try:
                    actual = json.loads(body)["error"]["n_prompt_tokens"]
                except (ValueError, KeyError):
                    die(out, label, target, f"fit HTTP 400 без n_prompt_tokens: {body[:500]}")
                record(out, label, f"fit{attempt}_over_limit", target, False, {},
                       note=f"HTTP 400 exceed_context_size, n_prompt_tokens={actual}")
                print(f"  fit{attempt}: промпт вылез за -c ({actual} tok), пересчёт по факту")
                est_chars = int(est_chars * target / actual)
                continue
            die(out, label, target, f"fit HTTP {e.code}: {body[:500]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            die(out, label, target, f"fit connection failed (сервер упал? OOM?): {e}")
        t = timings(r)
        achieved = t["prompt_n"]
        record(out, label, f"fit{attempt}", target, False, t)
        print(f"  fit{attempt}: prompt_n={achieved} prefill={t['prompt_per_second']:.1f} t/s")
        if abs(achieved - target) / target <= 0.02:
            break
        est_chars = int(est_chars * target / achieved)

    if achieved is None:
        die(out, label, target, "все fit-попытки ушли в exceed_context_size — target больше -c?")

    if not args.prefill_only:
        try:
            r = query(base, {"prompt": text, "n_predict": args.n_predict,
                             "cache_prompt": False, "temperature": 0,
                             "seed": args.seed}, args.timeout)
        except urllib.error.HTTPError as e:
            die(out, label, target, f"decode-cold HTTP {e.code}: {e.read()[:500]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            die(out, label, target, f"decode-cold connection failed: {e}")
        t = timings(r)
        record(out, label, "decode_cold", target, False, t)
        print(f"  decode cold: prefill={t['prompt_per_second']:.1f} t/s "
              f"decode={t['predicted_per_second']:.1f} t/s ({t['predicted_n']} tok)")

        for k in range(2, args.repeats + 1):
            try:
                r = query(base, {"prompt": text, "n_predict": args.n_predict,
                                 "cache_prompt": True, "temperature": 0,
                                 "seed": args.seed}, args.timeout)
            except urllib.error.HTTPError as e:
                die(out, label, target, f"decode-warm HTTP {e.code}: {e.read()[:500]}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                die(out, label, target, f"decode-warm connection failed: {e}")
            t = timings(r)
            record(out, label, f"decode_warm{k}", target, True, t)
            print(f"  decode warm{k}: prefill={t['prompt_per_second']:.1f} t/s (cached) "
                  f"decode={t['predicted_per_second']:.1f} t/s")


def run_cache_ab(base, out, args):
    label = args.label
    print(f"=== [{label}] cache-ab, prefix={args.cache_prefix} tokens ===")
    rng = random.Random(args.seed + 999)
    # nonce в начале — каждый запуск гарантированно cold, даже при повторе
    nonce = f"// bench nonce {time.time_ns()}\n"
    prefix = nonce + gen_text(int(args.cache_prefix * 2.83), rng)
    suffix1 = gen_text(2000, rng)
    suffix2 = gen_text(2000, rng)
    res = []
    for i, suffix in enumerate((suffix1, suffix2), 1):
        try:
            r = query(base, {"prompt": prefix + suffix, "n_predict": 16,
                             "cache_prompt": True, "temperature": 0,
                             "seed": args.seed}, args.timeout)
        except urllib.error.HTTPError as e:
            die(out, label, args.cache_prefix, f"cache-ab req{i} HTTP {e.code}: {e.read()[:500]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            die(out, label, args.cache_prefix, f"cache-ab req{i} connection failed: {e}")
        t = timings(r)
        record(out, label, f"cacheab_req{i}", args.cache_prefix, True, t)
        print(f"  req{i}: prompt_n={t['prompt_n']} prompt_ms={t['prompt_ms']:.0f} "
              f"(prefill {t['prompt_per_second']:.1f} t/s)")
        res.append(t)
    eff = 1 - res[1]["prompt_ms"] / res[0]["prompt_ms"]
    print(f"  эффективность кэша: итерация 2 стоит {res[1]['prompt_ms'] / res[0]['prompt_ms']:.1%} "
          f"от холодного prefill (переиспользовано {eff:.1%})")
    record(out, label, "cacheab_summary", args.cache_prefix, True,
           {"prompt_ms": res[1]["prompt_ms"], "prompt_n": res[1]["prompt_n"]},
           note=f"cold_ms={res[0]['prompt_ms']:.0f} reuse={eff:.1%}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base-url", default=None,
                   help="корень llama-server (напр. http://localhost:8080); "
                        "/v1-суффикс срезается; дефолт — $LLAMACPP_BASE_URL")
    p.add_argument("--label", required=True, help="метка конфигурации для jsonl/stdout")
    p.add_argument("--targets", default="",
                   help="целевые длины промпта в токенах через запятую (напр. 65536,131072)")
    p.add_argument("--repeats", type=int, default=3,
                   help="число decode-замеров на цель (1 cold + (n-1) warm), дефолт 3")
    p.add_argument("--n-predict", type=int, default=256, help="токенов генерации в decode-замере")
    p.add_argument("--prefill-only", action="store_true",
                   help="без decode-замеров (быстрый отсев вариантов; fit-запросы = prefill-цифры)")
    p.add_argument("--cache-ab", action="store_true",
                   help="режим A/B кэша префикса (этап 3) вместо лестницы длин")
    p.add_argument("--cache-prefix", type=int, default=57344,
                   help="длина общего префикса для --cache-ab, токенов (дефолт 65536−8192)")
    p.add_argument("--timeout", type=int, default=7200, help="таймаут запроса, сек (256k-prefill ~час)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default=None,
                   help="jsonl-файл результатов (дефолт: 5_llama_start_args_experiment/results/bench.jsonl)")
    args = p.parse_args()

    if not args.targets and not args.cache_ab:
        p.error("нужен --targets или --cache-ab")

    base = args.base_url or os.environ.get("LLAMACPP_BASE_URL")
    if not base:
        p.error("--base-url не задан и $LLAMACPP_BASE_URL пуст")
    base = normalize_base(base)

    out_path = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "results", "bench.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "a") as out:
        if args.cache_ab:
            run_cache_ab(base, out, args)
        else:
            for target in (int(x) for x in args.targets.split(",")):
                run_target(base, out, args, target)
    print(f"jsonl: {out_path}")


if __name__ == "__main__":
    main()
