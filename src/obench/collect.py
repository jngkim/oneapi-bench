"""Turning job output into validated results and scaling reports.

For every repetition the application's ``hooks.parse()`` extracts metrics and
``hooks.checks()`` validates them (correct result, GPU actually used, ...).
A repetition counts only if the run succeeded *and* all checks passed; a
process that exits 0 after silently falling back to the CPU is not a result.
"""

import csv
import json
import math
import statistics
from pathlib import Path

from . import slurm
from .config import ConfigError
from .run import load_experiment

PASSED, INVALID, FAILED, MISSING, PARSE_ERROR = "passed", "invalid", "failed", "missing", "parse-error"


def _context(experiment, case):
    ctx = {
        "app": experiment["app"]["name"], "version": experiment["app"]["version"],
        "workload": experiment["workload"]["name"], "site": experiment["site"]["name"],
        "validate": experiment["workload"]["config"].get("validate", {}),
        "metrics": experiment["workload"]["config"]["metrics"],
        "params": case.get("params", {}),
    }
    ctx.update({k: v for k, v in case.items() if k not in ("params",)})
    ctx.update(case.get("params", {}))
    return ctx


def _sycl_check(case_dir):
    """Did the job see any GPU at all? Skipped when sycl-ls was unavailable."""
    path = case_dir / "sycl-ls.txt"
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    if "sycl-ls not available" in text:
        return None
    ok = ":gpu" in text
    return ("gpu-visible", ok, "sycl-ls lists a GPU" if ok else "sycl-ls lists no GPU device")


def collect(registry, exp_dir, log=print):
    exp_dir = Path(exp_dir)
    experiment = load_experiment(exp_dir)
    app = registry.app(experiment["app"]["name"])
    hooks = app.hooks
    primary = experiment["workload"]["config"]["metrics"]["primary"]
    rows = []
    for case in experiment["cases"]:
        case_dir = exp_dir / case["name"]
        ctx = _context(experiment, case)
        gpu_check = _sycl_check(case_dir)
        for rep in range(1, experiment["repetitions"] + 1):
            rep_dir = case_dir / ("rep%d" % rep)
            row = {"case": case["name"], "nodes": case["nodes"],
                   "devices_per_node": case["devices_per_node"],
                   "total_devices": case["total_devices"], "ranks": case["ranks"],
                   "rep": rep, "state": None, "wall_s": None, primary: None, "detail": ""}
            checks = []
            status_path = rep_dir / "status.json"
            if not status_path.exists():
                row["state"] = MISSING
                row["detail"] = "not run yet (or job still running)"
                rows.append((row, checks))
                continue
            status = json.loads(status_path.read_text())
            row["wall_s"] = round(status["end"] - status["start"], 3)
            if status["exit_code"] != 0:
                row["state"] = FAILED
                row["detail"] = "%s exited with code %d; see %s" % (
                    status["stage"], status["exit_code"], rep_dir / "stderr.log")
                rows.append((row, checks))
                continue
            try:
                metrics = hooks.parse(rep_dir, ctx) or {}
            except Exception as exc:  # hooks are user code: report, don't crash
                row["state"] = PARSE_ERROR
                row["detail"] = "%s.parse(): %s: %s" % (app.name, type(exc).__name__, exc)
                rows.append((row, checks))
                continue
            row.update(metrics)
            if gpu_check:
                checks.append(gpu_check)
            checks.append(("primary-metric", metrics.get(primary) is not None,
                           "found %s" % primary if metrics.get(primary) is not None
                           else "metric '%s' not found in output" % primary))
            if hasattr(hooks, "checks"):
                try:
                    checks += list(hooks.checks(metrics, rep_dir, ctx))
                except Exception as exc:
                    checks.append(("hooks.checks", False, "%s: %s" % (type(exc).__name__, exc)))
            failed = [c for c in checks if not c[1]]
            row["state"] = PASSED if not failed else INVALID
            row["detail"] = "; ".join("%s: %s" % (c[0], c[2]) for c in failed)
            rows.append((row, checks))
    _write(exp_dir, rows)
    return experiment, [r for r, _ in rows]


def _write(exp_dir, rows):
    fields = []
    for row, _ in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with open(exp_dir / "results.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row, _ in rows:
            writer.writerow(row)
    payload = [dict(row, checks=[{"name": n, "ok": ok, "detail": d} for n, ok, d in checks])
               for row, checks in rows]
    (exp_dir / "results.json").write_text(json.dumps(payload, indent=2) + "\n")


def summarize(experiment, rows):
    """Per-case statistics plus speedup/efficiency against the smallest case."""
    metrics = experiment["workload"]["config"]["metrics"]
    primary, higher = metrics["primary"], metrics["higher_is_better"]
    scaling = experiment["workload"]["config"]["workload"]["scaling"]
    summary = []
    for case in experiment["cases"]:
        mine = [r for r in rows if r["case"] == case["name"]]
        values = [r[primary] for r in mine if r["state"] == PASSED]
        entry = {"case": case["name"], "nodes": case["nodes"], "total_devices": case["total_devices"],
                 "passed": len(values), "runs": len(mine), "states": sorted({r["state"] for r in mine})}
        if values:
            entry.update(mean=statistics.mean(values), min=min(values), max=max(values),
                         cv=(statistics.stdev(values) / statistics.mean(values)
                             if len(values) > 1 and statistics.mean(values) else 0.0))
        summary.append(entry)
    measured = [e for e in summary if "mean" in e]
    if measured:
        base = min(measured, key=lambda e: e["total_devices"])
        for e in measured:
            ratio = e["mean"] / base["mean"] if higher else base["mean"] / e["mean"]
            scale = e["total_devices"] / base["total_devices"]
            e["speedup"] = ratio
            # Weak scaling with a time-like metric: ideal is constant time.
            e["efficiency"] = ratio if (scaling == "weak" and not higher) else ratio / scale
    return summary


def _fmt(value, digits=4):
    if value is None:
        return "-"
    if isinstance(value, float):
        if value == 0 or math.isfinite(value) and 1e-3 <= abs(value) < 1e6:
            return "%.*g" % (digits, value)
        return "%.3e" % value
    return str(value)


def report_text(experiment, summary):
    metrics = experiment["workload"]["config"]["metrics"]
    unit = " (%s)" % metrics["unit"] if metrics["unit"] else ""
    better = "higher is better" if metrics["higher_is_better"] else "lower is better"
    wl = experiment["workload"]["config"]["workload"]
    lines = [
        "# %s on %s" % (experiment["workload"]["id"], experiment["site"]["name"]),
        "",
        "- Experiment: `%s`" % experiment["id"],
        "- Application: %s %s, toolchain %s" % (
            experiment["app"]["name"], experiment["app"]["version"],
            experiment["site"]["config"]["toolchain"]["tag"]),
        "- Workload: %s (%s, %s scaling)" % (wl["title"], wl["kind"], wl["scaling"]),
        "- Primary metric: %s%s, %s" % (metrics["primary"], unit, better),
        "",
        "| case | nodes | devices | passed | mean | min | max | CV | speedup | efficiency |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in summary:
        lines.append("| %s | %d | %d | %d/%d | %s | %s | %s | %s | %s | %s |" % (
            e["case"], e["nodes"], e["total_devices"], e["passed"], e["runs"],
            _fmt(e.get("mean")), _fmt(e.get("min")), _fmt(e.get("max")),
            "%.1f%%" % (100 * e["cv"]) if "cv" in e else "-",
            _fmt(e.get("speedup"), 3), "%.0f%%" % (100 * e["efficiency"]) if "efficiency" in e else "-"))
    lines += ["", "Speedup and efficiency are relative to the smallest case with passing runs. "
              "Only repetitions that ran successfully and passed all checks are included; "
              "see results.csv for every repetition."]
    return "\n".join(lines) + "\n"


def report(registry, exp_dir, log=print):
    experiment, rows = collect(registry, exp_dir, log)
    summary = summarize(experiment, rows)
    text = report_text(experiment, summary)
    (Path(exp_dir) / "report.md").write_text(text)
    problems = [r for r in rows if r["state"] not in (PASSED, MISSING)]
    return text, problems, rows


def status(exp_dir):
    experiment = load_experiment(exp_dir)
    states = slurm.job_states([c.get("job_id") or "" for c in experiment["cases"]])
    out = []
    for case in experiment["cases"]:
        done = len(list((Path(exp_dir) / case["name"]).glob("rep*/status.json")))
        job = case.get("job_id") or "not submitted"
        out.append((case["name"], job, states.get(job, "-"), "%d/%d" % (done, experiment["repetitions"])))
    return experiment, out


def find_experiments(results_root, pattern=None):
    root = Path(results_root)
    if not root.exists():
        return []
    found = sorted(p.parent for p in root.glob("*/experiment.json"))
    if pattern:
        found = [p for p in found if pattern in p.name]
    return found


def resolve_experiment(site_results_root, value):
    """Accept a path, an experiment id, or 'latest'."""
    path = Path(value)
    if (path / "experiment.json").exists():
        return path
    candidates = find_experiments(site_results_root, None if value == "latest" else value)
    if not candidates:
        raise ConfigError("no experiment matching '%s' under %s" % (value, site_results_root))
    return candidates[-1]
