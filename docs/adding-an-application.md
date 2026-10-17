# Adding an application

```bash
./obench new app lammps        # creates apps/lammps/{app.toml,build.sh,hooks.py,workloads/example.toml}
```

Then fill in the three files below (the LAMMPS values are illustrative). Use `apps/heffte/` as a compact example
and `apps/gromacs/` as a complete one.

## 1. `app.toml`

```toml
[app]
title = "LAMMPS"
description = "Classical molecular dynamics with Kokkos SYCL"
homepage = "https://www.lammps.org"
license = "GPL-2.0"
default_version = "22Jul2025"

[source]                       # either a tarball url or git + ref; {version} is replaced
git = "https://github.com/lammps/lammps.git"
ref = "stable_{version}"

[build]
check = ["bin/lmp"]            # must exist after the build, or the build fails
time_limit = "02:00:00"        # for `obench build --submit`

[build.env]                    # knobs exported to build.sh; sites and --set override them
KOKKOS_ARCH = "INTEL_PVC"
CMAKE_EXTRA = ""

[run]
executable = "bin/lmp"         # {exe} in workload commands

[run.env]                      # environment for every run of this application
SYCL_CACHE_PERSISTENT = "1"
```

## 2. `build.sh`

A plain bash script. obench runs it after the site toolchain is loaded (for
example `setvars.sh`), with these variables exported:

| Variable | Meaning |
|---|---|
| `OBENCH_SRC_DIR` | Unpacked source (downloaded by obench on the login node) |
| `OBENCH_BUILD_DIR` | Scratch build directory |
| `OBENCH_PREFIX` | Install prefix: `<install_root>/<app>/<version>-<toolchain tag>` |
| `OBENCH_JOBS` | Parallel build jobs |
| `OBENCH_VERSION`, `OBENCH_APP` | Names |
| `OBENCH_MPI_GPU_AWARE` | `ON`/`OFF` from the site |
| `OBENCH_GPU_MODE` | `gpu`/`tile` from the site |
| `<OTHER>_PREFIX` | Prefix of every other application already built with the same toolchain, e.g. `HEFFTE_PREFIX` |
| every `[build.env]` key | e.g. `KOKKOS_ARCH`, `CMAKE_EXTRA` |

Guidelines:

- Start with `set -euo pipefail`. Compile with `icx`/`icpx` and install into
  `$OBENCH_PREFIX`.
- Benchmark drivers that `cmake --install` does not install should be copied
  to `$OBENCH_PREFIX/bin` (as heFFTe does with `speed3d_*`).
- Give executables a stable name if the build encodes options in the file
  name (as WarpX does with `bin/warpx.3d`).
- Expose choices as `[build.env]` keys rather than editing the script per site.

## 3. `hooks.py`

```python
from obench.hookutil import NUMBER, check, last_match, read

def parse(rep_dir, ctx):                     # required
    log = read(rep_dir, "log.lammps", "stdout.log")
    return {"timesteps_per_s": last_match(r"Performance: .* (%s) timesteps/s" % NUMBER, log)}

def checks(metrics, rep_dir, ctx):           # optional but strongly recommended
    log = read(rep_dir, "log.lammps")
    return [check("kokkos-sycl", "Kokkos::SYCL" in log, "SYCL backend", "SYCL backend not active"),
            check("finished", "Total wall time" in log, "finished", "run did not finish")]

def context(v):                              # optional: extra placeholders per case
    return {"kokkos_flags": "-k on g %d -sf kk" % 1}
```

- `parse()` returns a dict of metrics. Missing values should be `None`, not
  exceptions.
- `checks()` returns `(name, ok, detail)` tuples. Prove three things: the work
  really ran on the GPU, it finished, and the answer is right (an error norm,
  energy drift, or expected step count). A check that fails makes the run
  `invalid` and prints the detail.
- `ctx` holds the case variables (`ranks`, `total_devices`, ...), the workload
  parameters, and `ctx["validate"]` from the workload file.

Add tests in `tests/test_apps.py` with a log excerpt from a real run. Then add
workloads (see [adding-a-workload.md](adding-a-workload.md)) and regenerate the
catalog with `./obench list --markdown > docs/workloads.md`.
