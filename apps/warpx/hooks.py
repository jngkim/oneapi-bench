"""WarpX: grid sizes per case, per-step timing parsing and validation."""

import re

from obench.config import ConfigError
from obench.hookutil import NUMBER, all_matches, check, last_match, read


def weak_cells(base, total_devices):
    """Grow the grid by doubling x, y, z in turn (as WarpX's former PerformanceTests did)."""
    cells = list(base)
    n, axis = total_devices, 0
    if n & (n - 1):
        raise ConfigError("weak-scaling WarpX workloads need a power-of-two device count, got %d"
                          % total_devices)
    while n > 1:
        cells[axis] *= 2
        n //= 2
        axis = (axis + 1) % 3
    return cells


def context(v):
    if str(v.get("cells_per_device", "")).strip():
        base = [int(x) for x in str(v["cells_per_device"]).split()]
        nx, ny, nz = weak_cells(base, v["total_devices"])
    else:
        nx, ny, nz = int(v["nx"]), int(v["ny"]), int(v["nz"])
    return {"nx": nx, "ny": ny, "nz": nz, "cells": nx * ny * nz}


def parse(rep_dir, ctx):
    out = read(rep_dir, "stdout.log")
    step_times = all_matches(r"This step = (%s) s" % NUMBER, out)
    warmup = int(ctx.get("warmup_steps", 0))
    timed = step_times[warmup:]
    mean = sum(timed) / len(timed) if timed else None
    cells = ctx.get("cells")
    return {
        "steps": len(step_times),
        "timed_steps": len(timed),
        "step_time_s": mean,
        "cell_updates_per_s": cells / mean if (mean and cells) else None,
        "total_time_s": last_match(r"Total Time\s*:\s*(%s)" % NUMBER, out),
        "sycl_devices": last_match(r"SYCL initialized with (\d+) device", out, cast=int),
        "mpi_processes": last_match(r"MPI initialized with (\d+) MPI processes", out, cast=int),
    }


def checks(metrics, rep_dir, ctx):
    out = read(rep_dir, "stdout.log")
    expected = int(ctx.get("steps", 0))
    return [
        check("sycl", "Initializing SYCL" in out and metrics["sycl_devices"],
              "AMReX initialized SYCL", "no SYCL initialization in output: not a GPU build?"),
        check("mpi", metrics["mpi_processes"] == ctx["ranks"], "%s MPI processes" % ctx["ranks"],
              "MPI processes %s != expected %s" % (metrics["mpi_processes"], ctx["ranks"])),
        check("steps", expected == 0 or metrics["steps"] == expected, "%d steps" % metrics["steps"],
              "ran %d of %d steps" % (metrics["steps"], expected)),
        check("timed-steps", metrics["timed_steps"] > 0, "%d timed steps" % metrics["timed_steps"],
              "no steps left after warmup_steps=%s" % ctx.get("warmup_steps")),
        check("finished", "Total Time" in out, "run completed", "no 'Total Time' line: run aborted?"),
    ]
