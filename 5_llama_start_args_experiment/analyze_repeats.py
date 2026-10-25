#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализатор серий канонической проверки (T3/T4 протокола N_RETRIES_PROTOCOL.md).

Единственный источник p-значений для выводов кампании (правило R6 протокола).
Использует только стандартную библиотеку Python; запускать через
`python3 -I analyze_repeats.py <команда> <аргументы>` (флаг -I изолирует
запуск от текущего каталога).

Команды:
  scan [--results КАТАЛОГ] [--assign ФАЙЛ=ТОЧКА[:СЕРИЯ]]...
      Сводная таблица: по каждой серии — доля успешных прогонов; по каждой
      точке — суммарный пул (все засчитанные прогоны точки) с доверительным
      интервалом Уилсона 95% и внутриточечным разбросом (разность между
      лучшей и худшей серией).
  pair ТОЧКА1 ТОЧКА2 [--results КАТАЛОГ] [--assign ...]
      Сравнение двух точек по правилу R3: пулы, доверительные интервалы,
      точный двусторонний тест Фишера, разрыв средних и вердикт
      «влияет / не показано».
  pool-pair "УСПЕХИ/ВСЕГО,УСПЕХИ/ВСЕГО"
      Тест Фишера для двух вручную заданных пулов (сверка с числами из
      PLAN.md).

Как собираются данные. Серии читаются из каталога results; имя файла имеет
вид `check_<точка>_s<N>_series.jsonl` (серии кампании) либо
`check_<метка>_series.jsonl` (серии дня 2026-10-16, старый формат имён) —
точка и серия выводятся из имени; ключ `--assign ФАЙЛ=ТОЧКА[:СЕРИЯ]`
переопределяет разбор для указанного файла.

Какие прогоны попадают в пулы. Механические вердикты PASS, FAIL и INVALID
учитываются (правило R1); любые прочие значения (CONFUND и т.п.) в пулы не
входят и показываются отдельно. Серия целиком исключается из пулов (правило
R5), если её файлы помечены суффиксом `_confund` либо внутри неё есть строка
с вердиктом CONFUND. Строки с признаком "reconstructed": true учитываются и
помечаются (реконструкция утраченных экспортов — урок серии (c)).
"""
import argparse
import json
import math
import os
import re
import sys

VALID = ("PASS", "FAIL", "INVALID")
# Имена файлов серий кампании: точка и номер серии извлекаются из имени.
SERIES_RE = re.compile(r"^check_(.+)_s\d+_series\.jsonl$")
# Имена файлов дня 2026-10-16: вся метка целиком считается точкой.
LEGACY_RE = re.compile(r"^check_(.+)_series\.jsonl$")


def fisher_two_sided(a, b, c, d):
    """Точный двусторонний тест Фишера для таблицы 2x2.

    Таблица задана по строкам: (a | b) — первая точка, (c | d) — вторая.
    Возвращается суммарная вероятность всех таблиц не менее крайних,
    чем наблюдаемая, при фиксации итогов по строкам и столбцам.
    """
    n = a + b + c + d
    r1, c1 = a + b, a + c
    col1, col2 = c1, n - c1

    def logC(k, x):
        return math.lgamma(k + 1) - math.lgamma(x + 1) - math.lgamma(k - x + 1)

    def logprob(x):
        return logC(col1, x) + logC(col2, r1 - x) - logC(n, r1)

    p_obs = logprob(a)
    lo, hi = max(0, r1 - col2), min(r1, col1)
    total = 0.0
    for x in range(lo, hi + 1):
        if logprob(x) <= p_obs + 1e-9:
            total += math.exp(logprob(x))
    return min(1.0, total)


def wilson(passes, total, z=1.959963984540054):
    """Доверительный интервал Уилсона уровня 95%; возвращает (низ, верх)."""
    if total == 0:
        return (0.0, 0.0)
    ph = passes / total
    denom = 1 + z * z / total
    center = (ph + z * z / (2 * total)) / denom
    half = z * math.sqrt(ph * (1 - ph) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def pct(x):
    return f"{100 * x:.1f}%"


def load_series(path):
    """Читает файл серии и возвращает сводку по прогонам."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    counted = [r for r in rows if r.get("verdict") in VALID]
    other = [r for r in rows if r.get("verdict") not in VALID]
    return {
        "path": path,
        "rows": rows,
        "n": len(counted),
        "pass": sum(1 for r in counted if r["verdict"] == "PASS"),
        "fail": sum(1 for r in counted if r["verdict"] == "FAIL"),
        "invalid": sum(1 for r in counted if r["verdict"] == "INVALID"),
        "other": len(other),
        "confund": sum(1 for r in other if r.get("verdict") == "CONFUND"),
        "reconstructed": sum(1 for r in counted if r.get("reconstructed")),
    }


def collect(results_dir, assigns):
    """Собирает серии по точкам из всех файлов-журналов каталога."""
    override = {}
    for a in assigns:
        if "=" not in a:
            sys.exit(f"--assign: нет символа '=' в «{a}» (формат: ФАЙЛ=ТОЧКА[:СЕРИЯ])")
        stem, label = a.split("=", 1)
        if ":" in label:
            point, series = label.split(":", 1)
        else:
            point, series = label, None
        override[stem] = (point, series)

    points = {}
    for name in sorted(os.listdir(results_dir)):
        m = SERIES_RE.match(name) or LEGACY_RE.match(name)
        if not m:
            continue
        stem = m.group(1)
        if stem in override:
            point, series = override[stem]
        elif SERIES_RE.match(name):
            point = re.match(r"^check_(.+)_s(\d+)_series\.jsonl$", name).group(1)
            series = re.match(r"^check_(.+)_s(\d+)_series\.jsonl$", name).group(2)
        else:
            point, series = stem, "1"
        info = load_series(os.path.join(results_dir, name))
        info["stem"] = stem
        info["series_label"] = series
        if "_confund" in stem:
            info["excluded"] = "файлы помечены суффиксом _confund (забракованная серия, правило R5)"
        elif info["confund"] > 0:
            info["excluded"] = f"внутри файла {info['confund']} строк с вердиктом CONFUND (правило R5)"
        else:
            info["excluded"] = None
        points.setdefault(point, []).append(info)
    return points


def active(series_list):
    """Серии, допущенные к пулам (не забракованные)."""
    return [s for s in series_list if not s["excluded"]]


def point_stats(series_list):
    good = active(series_list)
    n = sum(s["n"] for s in good)
    p = sum(s["pass"] for s in good)
    return n, p


def cmd_scan(args):
    points = collect(args.results, args.assign)
    for point, series_list in sorted(points.items()):
        print(f"=== точка {point} ===")
        for s in series_list:
            if s["excluded"]:
                raw = f"{s['pass']}/{s['n']} PASS"
                print(f"  {s['stem']}: ИСКЛЮЧЕНА из пулов ({s['excluded']}; сырые данные: {raw})")
        for s in active(series_list):
            note = []
            if s["other"]:
                note.append(f"прогонов вне пулов: {s['other']}")
            if s["reconstructed"]:
                note.append(f"реконструировано строк: {s['reconstructed']}")
            rate = pct(s["pass"] / s["n"]) if s["n"] else "—"
            print(f"  {s['stem']}: {s['pass']}/{s['n']} PASS "
                  f"(FAIL {s['fail']}, INVALID {s['invalid']}; {rate})"
                  + (f" [{'; '.join(note)}]" if note else ""))
        good = active(series_list)
        n, p = point_stats(series_list)
        lo, hi = wilson(p, n)
        rates = [s["pass"] / s["n"] for s in good if s["n"]]
        spread = max(rates) - min(rates) if len(rates) > 1 else 0.0
        print(f"  ПУЛ {point} (все засчитанные прогоны точки): {p}/{n} = {pct(p / n) if n else '—'} "
              f"(Уилсон 95%: {pct(lo)}–{pct(hi)}), "
              f"серий {len(good)}, внутриточечный разброс {pct(spread)}")


def point_pool(points, name):
    if name not in points:
        sys.exit(f"точка «{name}» не найдена; есть: {', '.join(sorted(points))}")
    series_list = active(points[name])
    if not series_list:
        sys.exit(f"точка «{name}»: все серии исключены (забракованы по правилу R5)")
    n, p = point_stats(points[name])
    rates = [s["pass"] / s["n"] for s in series_list if s["n"]]
    spread = max(rates) - min(rates) if len(rates) > 1 else 0.0
    return p, n, spread, series_list


def cmd_pair(args):
    points = collect(args.results, args.assign)
    pa, na, spread_a, sa = point_pool(points, args.point1)
    pb, nb, spread_b, sb = point_pool(points, args.point2)
    for name, lst in ((args.point1, sa), (args.point2, sb)):
        detail = ", ".join(f"{s['pass']}/{s['n']}" for s in lst)
        print(f"{name}: серии {detail}")
    if na == 0 or nb == 0:
        sys.exit("один из пулов пуст — сравнение невозможно")
    pval = fisher_two_sided(pa, na - pa, pb, nb - pb)
    lo_a, hi_a = wilson(pa, na)
    lo_b, hi_b = wilson(pb, nb)
    gap = abs(pa / na - pb / nb)
    print(f"пулы: {args.point1} {pa}/{na} = {pct(pa / na)} "
          f"(Уилсон 95%: {pct(lo_a)}–{pct(hi_a)}); "
          f"{args.point2} {pb}/{nb} = {pct(pb / nb)} "
          f"(Уилсон 95%: {pct(lo_b)}–{pct(hi_b)})")
    print(f"точный двусторонний тест Фишера: p = {pval:.4f}")
    print(f"разрыв средних {pct(gap)}; внутриточечный разброс: "
          f"{args.point1} — {pct(spread_a)}, {args.point2} — {pct(spread_b)}")
    spread_ok = gap > (spread_a + spread_b) / 2
    fisher_ok = pval < 0.05
    if fisher_ok and spread_ok:
        verdict = "ВЛИЯЕТ (правило R3: значимый тест Фишера и разрыв больше полусуммы разбросов)"
    elif fisher_ok:
        verdict = "ПОГРАНИЧНОЕ: тест Фишера значим, но разрыв не превышает внутриточечный разброс (правило R3, условие «а» не выполнено)"
    else:
        verdict = "различие не показано (правило R3)"
    print(f"вердикт R3: {verdict}")


def cmd_pool_pair(args):
    try:
        left, right = args.pools.split(",")
        pa, na = (int(x) for x in left.strip().split("/"))
        pb, nb = (int(x) for x in right.strip().split("/"))
    except ValueError:
        sys.exit('формат аргумента: "УСПЕХИ/ВСЕГО,УСПЕХИ/ВСЕГО", например "24/26,43/67"')
    pval = fisher_two_sided(pa, na - pa, pb, nb - pb)
    lo_a, hi_a = wilson(pa, na)
    lo_b, hi_b = wilson(pb, nb)
    print(f"{pa}/{na} = {pct(pa / na)} (Уилсон 95%: {pct(lo_a)}–{pct(hi_a)})  против  "
          f"{pb}/{nb} = {pct(pb / nb)} (Уилсон 95%: {pct(lo_b)}–{pct(hi_b)})")
    print(f"точный двусторонний тест Фишера: p = {pval:.4f}")


def main():
    ap = argparse.ArgumentParser(
        description="Анализатор серий протокола повторов (T3): "
                    "сводки по точкам, попарные сравнения по правилу R3, "
                    "тест Фишера для ручных пулов.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--results", default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results"),
            help="каталог с файлами серий (по умолчанию: results рядом со скриптом)")
        sp.add_argument("--assign", action="append", default=[],
                        metavar="ФАЙЛ=ТОЧКА[:СЕРИЯ]",
                        help="переопределить разбор имени файла (можно указывать несколько раз)")

    sp_scan = sub.add_parser("scan", help="сводная таблица серий и пулов по точкам")
    add_common(sp_scan)
    sp_scan.set_defaults(func=cmd_scan)

    sp_pair = sub.add_parser("pair", help="сравнение двух точек по правилу R3")
    sp_pair.add_argument("point1", help="метка первой точки")
    sp_pair.add_argument("point2", help="метка второй точки")
    add_common(sp_pair)
    sp_pair.set_defaults(func=cmd_pair)

    sp_pp = sub.add_parser("pool-pair", help="тест Фишера для двух вручную заданных пулов")
    sp_pp.add_argument("pools", metavar='"УСПЕХИ/ВСЕГО,УСПЕХИ/ВСЕГО"')
    sp_pp.set_defaults(func=cmd_pool_pair)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
