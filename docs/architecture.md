# Architecture

## Goals

1. **Usable by non-experts.** Running a published benchmark on a new cluster
   needs one site file and a handful of commands. Errors say what to do next.
2. **Easy to extend.** Applications, workloads and clusters are added as files
   that follow templates. The core does not change.
3. **Trustworthy results.** Each number can be traced to its inputs, build and
   environment. Runs that did not demonstrably do the intended work are rejected.
4. **Portable to HPC systems.** Only the Python 3.9+ standard library and bash
   are required, because login nodes often have old Python versions and no
   pip access.

## Building blocks

```
             sites/<site>.toml                 apps/<app>/app.toml + build.sh
                    |                                     |
                    v                                     v
   obench build ----+-----------------------------> install/<app>/<version>-<toolchain>/
                    |                                     |  obench-build.json (manifest)
                    |                                     |
   obench fetch ----+--> data/<app>/<workload>/  <--- apps/<app>/workloads/<w>.toml [[inputs]]
                    |                                     |
   obench run  -----+---> results/<experiment>/           |
                            experiment.json   <-----------+  (everything, resolved)
                            gpu_bind.sh
                            n<N>-d<D>/job.sh  --sbatch-->  rep<k>/stdout.log, md.log, status.json
                                                                 |
   obench report ---- apps/<app>/hooks.py parse() + checks() ----+
                            results.csv  results.json  report.md
```

| Module | Responsibility |
|---|---|
| `config.py` | TOML loading, schemas with defaults, typo detection, discovery (`Registry`) |
| `_toml.py` | Fallback TOML reader for Python versions older than 3.11 without `tomli` |
| `template.py` | `{placeholder}` substitution and safe `=arithmetic` in parameters |
| `fetch.py` | Source and input downloads, SHA-256 verification, safe extraction |
| `build.py` | Generate the build wrapper, run it locally or with sbatch, write the manifest |
| `run.py` | Expand the (nodes x devices) matrix, render commands, write job scripts |
| `slurm.py` | `#SBATCH` headers, MPI launcher presets, submission, `sacct` state |
| `gpu_bind.sh` | Per-rank Intel GPU selection (`ZE_AFFINITY_MASK`, FLAT/COMPOSITE hierarchy) |
| `collect.py` | Parse, validate, aggregate, compute speedup/efficiency, render reports |
| `hookutil.py` | Small helpers for application hooks |
| `scaffold.py` | `obench new` from `templates/` |
| `cli.py` | Commands and messages |

## Extension points

| You want to... | You write... | Python needed? |
|---|---|---|
| Benchmark a new problem with an existing application | one `workloads/<name>.toml` | no |
| Change a problem size, precision or solver flag | `--set name=value` or `[params]` | no |
| Support a new cluster | one `sites/<name>.toml` | no |
| Use a different MPI launcher | `mpi.launcher` preset or template string | no |
| Add an application | `app.toml`, `build.sh`, `hooks.py` (`parse`, optional `checks`, `context`) | a few lines |

Application hooks are the only code an extender writes. `parse()` turns output
files into metrics. `checks()` decides whether a run is valid. `context()`
derives command-line values from the case. Examples are the GROMACS PME-rank
flag and the WarpX weak-scaling grid.

## Configuration precedence

Later entries win.

- **Run environment:** site `[env]` < site `[mpi.env]` < app `[run.env]` <
  site `[apps.<app>.run_env]` < workload `[run.env]` < `obench run --env`.
- **Build settings:** app `[build.env]` < site `[apps.<app>.build_env]` < `obench build --set`.
- **Version:** app `default_version` < site `[apps.<app>] version` < `--version`.
- **Workload parameters:** `[params]` < `obench run --set`. Unknown names are
  rejected. Parameters may refer to each other and to case variables in any
  order. A value starting with `=` is evaluated as arithmetic.

## Experiments, cases and repetitions

`obench run` creates `results/<timestamp>_<app>_<workload>_<site>[_label]/`.
Each (nodes, devices per node) combination is a case and becomes one job. Inside
the job the measurement is repeated `repetitions` times on the same nodes, so
variability between repetitions is not mixed up with node placement. The job
time limit is `repetitions x time_limit + 10 min`.

Devices are what a rank drives. In `gpu_mode = "tile"` each tile of a
multi-tile GPU is a device (Level Zero FLAT hierarchy), so a node with 4
Max 1550 GPUs has 8 devices. In `gpu_mode = "gpu"` each card is a device
(COMPOSITE hierarchy). Ranks per node = devices x `ranks_per_device`. CPU cores
are shared evenly between ranks.

## Provenance

`experiment.json` records:

- the fully resolved site, application and workload configuration;
- the build manifest (version, toolchain, compiler, build settings, source directory);
- the obench git revision and command-line overrides;
- the exact command of every case.

Each case directory also captures `env.txt`, `nodes.txt` and `sycl-ls.txt`
from the compute node. An experiment directory can be archived and re-analysed
on its own.

## Validation gates

A repetition is `passed` only when all of the following hold:

1. the job wrote `status.json` and the prepare and run stages exited with 0;
2. the application's `parse()` found the workload's primary metric;
3. `sycl-ls` on the node listed a GPU, when it was available;
4. every application `checks()` entry passed. Examples:
   - GROMACS: `Finished mdrun`, GPU task assignment, and PME on the GPU when requested;
   - WarpX: SYCL initialized, expected MPI rank and step counts, `Total Time` printed;
   - heFFTe: `onemkl` backend, expected rank count, and the FFT round-trip error within tolerance.

Other outcomes are `failed` (non-zero exit), `invalid` (a check failed),
`parse-error` (hook exception) and `missing` (not run yet). `report` exits
non-zero when any repetition is `failed`, `invalid` or `parse-error`.

## Relation to other tools

[ReFrame](https://reframe-hpc.readthedocs.io), [Ramble](https://github.com/GoogleCloudPlatform/ramble)
and [Benchpark](https://github.com/LLNL/benchpark) are more general frameworks.
They build on Python test classes or on Spack. This repository is deliberately
smaller: plain cmake builds against the site's oneAPI installation, declarative
TOML workloads, and no dependencies. If the suite grows into many applications
with complex dependency trees, the `build.sh` scripts can be replaced by Spack
environments without changing workloads or reports.
