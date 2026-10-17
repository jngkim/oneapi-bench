"""Parsers and checks of the real applications, on synthetic logs.

The log excerpts reproduce the print statements of the application sources
(GROMACS 2026.4 md.log, WarpX 26.10 WarpXEvolve.cpp/main.cpp with AMReX, heFFTe
2.4.1 benchmarks/speed3d.h). Replace them with logs from real runs when available.
"""

import pytest

from obench import run
from obench.config import ConfigError

GROMACS_LOG = """
On host x4001 2 GPUs selected for this run.
Mapping of GPU IDs to the 2 GPU tasks in the 2 ranks on this node:
  PP:0,PME:1
PP tasks will do (non-perturbed) short-ranged and most bonded interactions on the GPU
PP task will update and constrain coordinates on the GPU
PME tasks will do all aspects on the GPU
GPU direct communication will be used between MPI ranks.

               Core t (s)   Wall t (s)        (%)
       Time:     1630.345       58.227     2800.0
                 (ns/day)    (hour/ns)
Performance:       59.351        0.404
Finished mdrun on rank 0 Fri Oct 17 12:00:00 2026
"""

WARPX_LOG = """
Initializing SYCL...
SYCL initialized with 1 device.
MPI initialized with 2 MPI processes
""" + "".join(
    "STEP %d ends. TIME = 1e-15 DT = 1e-16\\nEvolve time = 1 s; This step = %s s; Avg. per step = 1 s\\n\\n"
    .replace("\\\\n", "\\n") % (i, "0.5" if i == 1 else "0.1") for i in range(1, 6)
) + "Total Time                     : 3.21\\n".replace("\\\\n", "\\n")

HEFFTE_LOG = """
-----------------------------------------------------------------------------
heFFTe performance test
-----------------------------------------------------------------------------
Backend:   onemkl
Size:      512x512x512
MPI ranks:    4
Grids: (1, 2, 2)  (1, 2, 2)  (2, 1, 2)  (2, 2, 1)  (1, 2, 2)
Time per run: 0.0123 (s)
Performance:  1471.23 GFlops/s
Memory usage: 4096MB/rank
Tolerance:    1e-11
Max error:    3.4e-15
"""


def _ctx(registry, ident, site="example-pvc", devices=("2",), nodes=("1",)):
    site = registry.site(site)
    wl = registry.workload(ident)
    case = run.plan_cases(site, wl, nodes=list(nodes), devices=list(devices))[0]
    base = run.base_variables(site, wl, wl.app.version_for(site), None)
    variables, params = run.case_context(site, wl, case, base, {})
    ctx = dict(variables, validate=wl.data["validate"])
    return wl.app.hooks, ctx, variables


def test_gromacs(registry, tmp_path):
    hooks, ctx, variables = _ctx(registry, "gromacs/benchMEM")
    assert variables["npme_flag"] == "-npme 1" and variables["ntomp"] == 16  # 56 cores per rank, capped
    (tmp_path / "md.log").write_text(GROMACS_LOG)
    metrics = hooks.parse(tmp_path, ctx)
    assert metrics["ns_per_day"] == pytest.approx(59.351)
    assert metrics["mdrun_wall_s"] == pytest.approx(58.227)
    assert all(ok for _, ok, _ in hooks.checks(metrics, tmp_path, ctx))
    (tmp_path / "md.log").write_text(GROMACS_LOG.replace("Mapping of GPU IDs", "No GPU"))
    failed = [n for n, ok, _ in hooks.checks(hooks.parse(tmp_path, ctx), tmp_path, ctx) if not ok]
    assert "gpu-tasks" in failed


def test_gromacs_reaction_field_has_no_pme_rank(registry):
    _, _, variables = _ctx(registry, "gromacs/ueabs-B")
    assert variables["npme_flag"] == ""


def test_warpx(registry, tmp_path):
    hooks, ctx, variables = _ctx(registry, "warpx/uniform-plasma")
    ctx.update(steps=5, warmup_steps=1)
    (tmp_path / "stdout.log").write_text(WARPX_LOG)
    metrics = hooks.parse(tmp_path, ctx)
    assert metrics["steps"] == 5 and metrics["timed_steps"] == 4
    assert metrics["step_time_s"] == pytest.approx(0.1)
    assert metrics["cell_updates_per_s"] == pytest.approx(256 ** 3 / 0.1)
    assert all(ok for _, ok, _ in hooks.checks(metrics, tmp_path, ctx))


def test_warpx_weak_grid(registry):
    _, _, v = _ctx(registry, "warpx/perftest-uniform-32ppc", devices=("8",), nodes=("2",))
    assert (v["nx"], v["ny"], v["nz"]) == (256, 128, 256)   # 16 devices: x2 per axis, then x
    with pytest.raises(ConfigError, match="power-of-two"):
        _ctx(registry, "warpx/perftest-uniform-32ppc", devices=("6",))


def test_heffte(registry, tmp_path):
    hooks, ctx, variables = _ctx(registry, "heffte/speed3d-c2c-512", devices=("4",))
    (tmp_path / "stdout.log").write_text(HEFFTE_LOG)
    metrics = hooks.parse(tmp_path, ctx)
    assert metrics["gflops"] == pytest.approx(1471.23) and metrics["backend"] == "onemkl"
    assert all(ok for _, ok, _ in hooks.checks(metrics, tmp_path, ctx))
    (tmp_path / "stdout.log").write_text(HEFFTE_LOG.replace("3.4e-15", "1e-3"))
    failed = [n for n, ok, _ in hooks.checks(hooks.parse(tmp_path, ctx), tmp_path, ctx) if not ok]
    assert failed == ["max-error"]


def test_heffte_weak_size(registry):
    _, _, v = _ctx(registry, "heffte/speed3d-c2c-weak", devices=("4",), nodes=("2",))
    assert v["nz"] == 256 * 8
