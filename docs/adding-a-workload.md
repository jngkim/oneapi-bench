# Adding a workload

A workload is one TOML file in `apps/<app>/workloads/`. The file name is the
workload name: `apps/gromacs/workloads/my-system.toml` is `gromacs/my-system`.

```bash
./obench new workload gromacs/my-system     # copy of templates/workload.toml
$EDITOR apps/gromacs/workloads/my-system.toml
./obench validate                           # schema + renders every command
./obench fetch gromacs/my-system            # prints the sha256 to pin
./obench run gromacs/my-system --dry-run    # look at n1-d1/job.sh
```

Copying a similar existing workload is often quickest. For example,
`gromacs/benchMEM` downloads a ready `.tpr`, while `gromacs/rnase-dodec` runs
`gmx grompp` first.

## Sections

### `[workload]`: what it is and where it comes from

| Key | Required | Meaning |
|---|---|---|
| `title` | yes | One line, shown by `obench list` |
| `kind` | yes | `bundled` (from the application developers), `published` (benchmark suite or paper), `custom` (defined here) |
| `publisher` | | Who defined it, e.g. `PRACE UEABS 2.2`, `NERSC` |
| `reference` | | URL of the definition. Cite the source so others can check fidelity |
| `size` | | `tiny`, `small`, `medium` (default), `large`, `xlarge` |
| `scaling` | | `strong` (fixed problem), `weak` (problem grows with devices), `throughput` |
| `status` | | `draft`, `unvalidated` (default), `validated` (results reviewed on real hardware) |
| `description`, `notes`, `tags` | | Free text. Notes appear in the catalog |

### `[[inputs]]`: files to download (optional, repeatable)

| Key | Meaning |
|---|---|
| `url` | Download location (or use `path` for a file kept in `apps/<app>/`) |
| `sha256` | Expected checksum. Leave empty at first; `obench fetch` prints the value |
| `filename` | Local name, when the URL has none (e.g. `https://www.mpinat.mpg.de/benchMEM`) |
| `extract` | Unpack tar/zip archives (default `true`) |

Inputs go to `<data_root>/<app>/<workload>/`, which commands see as
`{input_dir}`. `data_root` must be on a file system that compute nodes can read.

### `[run]`: how to run it

| Key | Default | Meaning |
|---|---|---|
| `command` | required | Command run by every MPI rank, after the launcher and the GPU binding wrapper |
| `nodes` | `[1]` | Default node counts (`--nodes` overrides) |
| `devices_per_node` | `["max"]` | Default devices per node. `"max"` means all devices of the site |
| `ranks_per_device` | `1` | MPI ranks sharing one device |
| `threads_per_rank` | `0` | `0` = the node's cores divided evenly between ranks (`OMP_NUM_THREADS`) |
| `min_devices`, `max_devices` | `1`, `0` | Skip cases outside this range (`0` = no maximum) |
| `repetitions` | `3` | Measurements per case, all within one job |
| `time_limit` | `00:30:00` | Per repetition. The job requests `repetitions x time_limit + 10 min` |
| `prepare` | `[]` | Commands run once per repetition, without MPI, before `command` (e.g. `gmx grompp`) |
| `env` | `{}` | Extra environment variables |

Commands run in the repetition directory, so relative output files such as
`md.log` land next to `stdout.log`.

### `[params]`: values users may change

Every entry becomes a `{placeholder}` and can be overridden with
`obench run ... --set name=value`. A misspelled name is rejected.

```toml
[params]
nx = 512
nz = "=256 * {total_devices}"     # '=' means arithmetic after substitution
input = "{input_dir}/{system}.tpr" # parameters may use each other, in any order
system = "465k"
```

Arithmetic supports numbers, `+ - * / // % **`, parentheses, and `min`, `max`,
`int` and `round`.

### `[metrics]`

| Key | Meaning |
|---|---|
| `primary` | Metric used in reports. Must be a key returned by the application's `hooks.parse()` |
| `higher_is_better` | `true` for rates (ns/day, GFlop/s); `false` for times |
| `unit` | Shown in reports |

For weak scaling, prefer a total-throughput metric such as cell-updates/s or
GFlop/s. Efficiency is then `(metric / baseline) / (devices / baseline devices)`,
the same as for strong scaling. With a time metric (`higher_is_better = false`),
weak-scaling efficiency is `baseline time / time`.

### `[validate]`

Thresholds passed to the application's `checks()` as `ctx["validate"]`. For
example, heFFTe reads `backend`. Which keys exist depends on the application;
see its `hooks.py`.

## Placeholders available to `command`, `prepare` and `[params]`

| Placeholder | Value |
|---|---|
| `{exe}` | `<prefix>/<app.toml run.executable>` |
| `{prefix}` | Install prefix of the application build |
| `{src_dir}` | Source tree of the build (example inputs of the application) |
| `{input_dir}` | Downloaded inputs of this workload |
| `{app_dir}` | `apps/<app>/` in this repository |
| `{nodes}`, `{devices_per_node}`, `{total_devices}` | Size of the case |
| `{ranks}`, `{ranks_per_node}`, `{ranks_per_device}` | MPI layout |
| `{cpus_per_rank}`, `{threads_per_rank}` | CPU layout |
| `{gpus_per_node}`, `{tiles_per_gpu}`, `{gpu_mode}` | Site node description |
| `{mpi_gpu_aware}` | `1` if the site declares GPU-aware MPI, else `0` |
| `{app}`, `{workload}`, `{version}`, `{site}`, `{toolchain}` | Names |

Applications add their own placeholders through `hooks.context()`. Examples
are `{npme_flag}` and `{ntomp}` for GROMACS, and `{nx}`, `{ny}`, `{nz}` and
`{cells}` for WarpX. `obench show` and `obench validate` reveal unknown
placeholders before anything is submitted.

## Fidelity checklist for published workloads

- Use the publisher's input files unchanged, and pin their checksum.
- Follow the publisher's run rules (step counts, `-maxh`, warm-up exclusion)
  by default. Put deviations needed for GPUs in `notes`.
- Say in `notes` when a paper's numbers came from another machine. Reproduce
  the problem, not the claim.
- Move `status` to `validated` only after checking the physics or numerics
  output of a real run (energies, FFT error, step counts) and the GPU usage
  shown in the logs.
