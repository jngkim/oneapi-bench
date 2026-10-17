"""heFFTe speed3d: parse the performance summary and validate the FFT error."""

import re

from obench.hookutil import NUMBER, check, last_match, read, threshold


def parse(rep_dir, ctx):
    out = read(rep_dir, "stdout.log")
    backend = re.search(r"^Backend:\s+(\S+)", out, re.MULTILINE)
    error = last_match(r"^Max error:\s+(%s)" % NUMBER, out)
    return {
        "backend": backend.group(1) if backend else None,
        "mpi_ranks": last_match(r"^MPI ranks:\s+(\d+)", out, cast=int),
        # Time of one forward + one backward pair divided by two (see speed3d.h).
        "time_per_run_s": last_match(r"^Time per run:\s+(%s)" % NUMBER, out),
        "gflops": last_match(r"^Performance:\s+(%s)\s+GFlops/s" % NUMBER, out),
        "memory_mb_per_rank": last_match(r"^Memory usage:\s+(\d+)MB/rank", out, cast=int),
        "tolerance": last_match(r"^Tolerance:\s+(%s)" % NUMBER, out),
        "max_error": error,
    }


def checks(metrics, rep_dir, ctx):
    want_backend = threshold(ctx, "backend", "onemkl")
    result = [
        check("backend", metrics["backend"] == want_backend, "backend %s" % want_backend,
              "backend is %s, expected %s (GPU backend not used?)" % (metrics["backend"], want_backend)),
        check("ranks", metrics["mpi_ranks"] == ctx["ranks"], "%s MPI ranks" % ctx["ranks"],
              "speed3d reports %s ranks, expected %s" % (metrics["mpi_ranks"], ctx["ranks"])),
    ]
    if metrics["max_error"] is None:
        result.append(("max-error", False, "no 'Max error' line (was -no-error used?)"))
    else:
        tol = metrics["tolerance"] if metrics["tolerance"] is not None else threshold(ctx, "max_error", 1e-10)
        result.append(check("max-error", metrics["max_error"] <= tol,
                            "max error %.2e <= %.2e" % (metrics["max_error"], tol),
                            "max error %.2e exceeds tolerance %.2e" % (metrics["max_error"], tol)))
    return result
