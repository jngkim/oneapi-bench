"""End to end: plan -> job scripts -> run locally with bash -> report."""

import json
import subprocess

import pytest

from obench import collect, run
from obench.cli import main
from obench.config import ConfigError, Registry


def test_plan_skips_impossible_cases(toy_repo):
    reg = Registry(toy_repo)
    site, wl = reg.site("test"), reg.workload("toy/strong")
    skipped = []
    cases = run.plan_cases(site, wl, nodes=["1", "2"], devices=["1", "max", "4"], log=skipped.append)
    assert [c.name for c in cases] == ["n1-d1", "n1-d2", "n2-d1", "n2-d2"]
    assert any("site has 2 devices per node" in s for s in skipped)


def test_tile_mode_doubles_devices(toy_repo):
    reg = Registry(toy_repo)
    assert reg.site("tiles").devices_per_node == 4
    case = run.plan_cases(reg.site("tiles"), reg.workload("toy/strong"), devices=["max"])[0]
    assert (case.ranks, case.cpus_per_rank) == (4, 2)


def test_unbuilt_app_is_refused_unless_dry_run(toy_repo):
    reg = Registry(toy_repo)
    with pytest.raises(ConfigError, match="obench build toy"):
        run.prepare(reg, reg.site("test"), reg.workload("toy/strong"), log=lambda *_: None)
    exp_dir, exp = run.prepare(reg, reg.site("test"), reg.workload("toy/strong"),
                               dry_run=True, log=lambda *_: None)
    assert (exp_dir / "n1-d2" / "job.sh").exists()


def test_unknown_param_override(toy_built):
    reg = toy_built
    with pytest.raises(ConfigError, match="no parameter 'sise'"):
        run.prepare(reg, reg.site("test"), reg.workload("toy/strong"), params={"sise": 3},
                    log=lambda *_: None)


def test_local_end_to_end(toy_built):
    reg = toy_built
    site, wl = reg.site("test"), reg.workload("toy/strong")
    exp_dir, exp = run.prepare(reg, site, wl, params={"base": 5}, log=lambda *_: None)
    case = {c["name"]: c for c in exp["cases"]}
    assert case["n1-d2"]["params"]["size"] == 20          # "=2 * {base} * {total_devices}"
    assert case["n1-d2"]["params"]["flag"] == "-x"        # from hooks.context (2 ranks)
    run.submit_experiment(site, exp_dir, exp, log=lambda *_: None)

    rep = exp_dir / "n1-d2" / "rep1"
    assert (rep / "prepared.txt").read_text().strip() == "prepared"
    stdout = (rep / "stdout.log").read_text()
    assert "size=20 devices=2" in stdout
    assert "mask=0" in stdout and "env=from-app" in stdout   # gpu_bind.sh and app env
    assert json.loads((rep / "status.json").read_text())["exit_code"] == 0

    text, problems, rows = collect.report(reg, exp_dir)
    assert not problems
    assert {r["state"] for r in rows} == {"passed"}
    summary = collect.summarize(json.loads((exp_dir / "experiment.json").read_text()), rows)
    by_case = {e["case"]: e for e in summary}
    assert by_case["n1-d2"]["speedup"] == pytest.approx(2.0)
    assert by_case["n1-d2"]["efficiency"] == pytest.approx(1.0)
    assert "| n1-d2 | 1 | 2 | 2/2 |" in text
    assert (exp_dir / "results.csv").read_text().startswith("case,")


def test_failed_and_invalid_runs_are_reported(toy_built):
    reg = toy_built
    site, wl = reg.site("test"), reg.workload("toy/strong")
    exp_dir, exp = run.prepare(reg, site, wl, devices=["1"], reps=2, log=lambda *_: None)
    run.submit_experiment(site, exp_dir, exp, log=lambda *_: None)
    rep1, rep2 = exp_dir / "n1-d1" / "rep1", exp_dir / "n1-d1" / "rep2"
    status = json.loads((rep1 / "status.json").read_text())
    status["exit_code"] = 3
    (rep1 / "status.json").write_text(json.dumps(status))
    (rep2 / "stdout.log").write_text("rate=0\n")           # fails the hook's min_rate check
    _, problems, rows = collect.report(reg, exp_dir)
    states = {r["rep"]: r for r in rows}
    assert states[1]["state"] == "failed" and "exit" in states[1]["detail"]
    assert states[2]["state"] == "invalid" and "rate too low" in states[2]["detail"]
    assert len(problems) == 2


def test_cli_dry_run_and_validate(toy_repo, monkeypatch, capsys):
    monkeypatch.setenv("OBENCH_ROOT", str(toy_repo))
    assert main(["validate"]) == 0
    assert main(["run", "toy/strong", "--site", "test", "--dry-run", "--set", "base=7"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "case n1-d2" in out
    assert main(["show", "toy/strong"]) == 0
    assert main(["run", "toy/strng", "--site", "test", "--dry-run"]) == 2
    assert "did you mean 'toy/strong'" in capsys.readouterr().err


def test_scaffold_creates_valid_files(toy_repo, monkeypatch, capsys):
    monkeypatch.setenv("OBENCH_ROOT", str(toy_repo))
    assert main(["new", "app", "newapp"]) == 0
    assert main(["new", "workload", "toy/second"]) == 0
    assert main(["new", "site", "mysite"]) == 0
    reg = Registry(toy_repo)
    assert "example" in reg.app("newapp").workloads
    assert "second" in reg.app("toy").workloads
    assert reg.site("mysite").devices_per_node == 8


def test_build_script_generation(toy_repo):
    from obench import build
    reg = Registry(toy_repo)
    site, app = reg.site("test"), reg.app("toy")
    script, prefix = build.generate(reg, site, app, "1.0", {"EXTRA": "x"})
    text = script.read_text()
    assert 'export OBENCH_PREFIX="%s"' % prefix in text
    assert 'export EXTRA="x"' in text
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_gpu_bind_modes(tmp_path):
    from obench.run import BIND_SCRIPT

    def bind(**env):
        out = subprocess.run(["bash", str(BIND_SCRIPT), "bash", "-c",
                              "echo $ZE_FLAT_DEVICE_HIERARCHY:$ZE_AFFINITY_MASK"],
                             env=dict(env, PATH="/usr/bin:/bin"), capture_output=True, text=True)
        return out.stdout.strip() or out.stderr.strip()

    assert bind(SLURM_LOCALID="3", OBENCH_GPU_MODE="tile") == "FLAT:3"
    assert bind(SLURM_LOCALID="3", OBENCH_GPU_MODE="gpu", OBENCH_RANKS_PER_DEVICE="2") == "COMPOSITE:1"
    assert bind(SLURM_LOCALID="1", OBENCH_GPU_MODE="tile", OBENCH_DEVICE_LIST="4,5") == "FLAT:5"
    assert "needs device slot" in bind(SLURM_LOCALID="2", OBENCH_DEVICE_LIST="4,5")


def test_job_time_limit_covers_all_repetitions():
    assert run.job_time_limit("00:30:00", 3) == "1:40:00"
    assert run.job_time_limit("45", 2) == "1:40:00"
    assert run.job_time_limit("1-00:00:00", 1) == "24:10:00"
    with pytest.raises(ConfigError):
        run.job_time_limit("soon", 1)


def test_repeated_runs_get_distinct_directories(toy_built):
    reg = toy_built
    first, _ = run.prepare(reg, reg.site("test"), reg.workload("toy/strong"), log=lambda *_: None)
    second, exp = run.prepare(reg, reg.site("test"), reg.workload("toy/strong"), log=lambda *_: None)
    assert first != second and exp["id"] == second.name
