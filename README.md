# oneAPI HPC benchmarks

Build HPC applications with Intel oneAPI and benchmark them on SLURM clusters
with Intel GPUs. A single command-line tool, `obench`, handles the whole cycle:
building, downloading inputs, generating and submitting jobs, checking results
and producing scaling reports.

Applications included today:

| Application | What it stresses | Workloads |
|---|---|---|
| [GROMACS](apps/gromacs) 2026.4 | Molecular dynamics: GPU nonbonded/PME, domain decomposition | PRACE UEABS A/B/C, MPI-NAT benchMEM/RIB/PEP-h, HECBioSim suite, GROMACS rnase and water |
| [WarpX](apps/warpx) 26.10 | Particle-in-cell plasma: particle push/deposition, halo exchange | WarpX uniform plasma, laser-wakefield, WarpX performance test (Summit/Cori weak scaling) |
| [heFFTe](apps/heffte) 2.4.1 | Distributed 3D FFT: all-to-all communication, oneMKL DFT | speed3d C2C/R2C, heFFTe ICCS 2020 problem sizes, weak scaling |

See the [workload catalog](docs/workloads.md) for sizes, sources and notes.

## Requirements

- A SLURM cluster with Intel GPUs (e.g. Intel Data Center GPU Max), the
  oneAPI Base + HPC toolkits (icx/icpx, oneMKL, Intel MPI or MPICH) and CMake.
- Python 3.9 or newer. No extra Python packages are needed.
- Internet access on the login node, for sources and inputs.

## Quick start

```bash
git clone <this repository> && cd oneapi-hpc-benchmarks

# 1. Describe your cluster (GPUs per node, oneAPI setup, partition, account).
./obench new site mycluster          # creates sites/mycluster.toml; edit the TODO lines
export OBENCH_SITE=mycluster         # or pass --site mycluster to every command

# 2. Check the toolchain.
./obench validate
./obench doctor

# 3. Build an application with oneAPI (on the login node; --submit builds in a job).
./obench build gromacs

# 4. See what can be run, then run it.
./obench list
./obench show gromacs/benchMEM
./obench run gromacs/benchMEM --nodes 1 --devices 1,2,4,max --dry-run   # inspect the job scripts
./obench run gromacs/benchMEM --nodes 1 --devices 1,2,4,max

# 5. Follow the jobs and get the report.
./obench status
./obench report                      # writes report.md, results.csv, results.json
```

`report` prints a table like this one (the numbers here are illustrative):

```
| case  | nodes | devices | passed | mean  | min   | max   | CV   | speedup | efficiency |
|-------|-------|---------|--------|-------|-------|-------|------|---------|------------|
| n1-d1 | 1     | 1       | 3/3    | 101.2 | 100.8 | 101.9 | 0.5% | 1       | 100%       |
| n1-d8 | 1     | 8       | 3/3    | 401.7 | 398.0 | 405.1 | 0.9% | 3.97    | 50%        |
```

Only repetitions that **ran successfully and passed every check** count. A run
that exits with 0 but did not use the GPU, did not finish, or produced a wrong
answer (heFFTe error above tolerance, for example) is reported as `invalid`
along with the reason.

## Concepts

| Term | Meaning | Where it lives |
|---|---|---|
| **site** | One cluster: node layout, oneAPI setup, SLURM and MPI settings | `sites/<name>.toml` |
| **application** | How to fetch, build and validate one code | `apps/<app>/app.toml`, `build.sh`, `hooks.py` |
| **workload** | One benchmark problem: inputs, command, parameters, metric | `apps/<app>/workloads/<name>.toml` |
| **device** | What one MPI rank drives: a whole GPU, or a single tile when `gpu_mode = "tile"` | site `[node]` |
| **experiment** | One `obench run` of one workload; one job per (nodes, devices) **case** | `results/<id>/` |

Workload parameters can be changed without editing files:

```bash
./obench run gromacs/hecbiosim --set system=1400k --nodes 1,2,4
./obench run heffte/speed3d-c2c-512 --set precision=float --set options="-pencils -a2a"
./obench run warpx/uniform-plasma --env OBENCH_BIND_VERBOSE=1
```

## Commands

| Command | Purpose |
|---|---|
| `obench list [APP] [--markdown]` | List applications and workloads |
| `obench show APP/WORKLOAD` | Details, parameters and command of one workload |
| `obench validate` | Check every app, workload and site file and render all commands |
| `obench doctor` | Check compilers, MPI, oneMKL, CMake, GPUs and sbatch on this node |
| `obench build APP... [--submit] [--set K=V]` | Build with the site toolchain into a versioned prefix |
| `obench fetch APP/WORKLOAD... \| --all` | Download inputs and verify their checksums |
| `obench run APP/WORKLOAD... [--nodes] [--devices] [--reps] [--set] [--dry-run]` | Generate and submit jobs |
| `obench status [EXPERIMENT]` | Job states and completed repetitions |
| `obench report [EXPERIMENT]` | Parse, validate and summarize, with speedup and efficiency |
| `obench new app\|workload\|site NAME` | Create new files from templates |

`EXPERIMENT` defaults to `latest`. It also accepts an experiment directory or
part of an experiment id.

## Extending

- **New workload** for an existing application: `./obench new workload gromacs/my-system`,
  then fill in the TOML. No Python is needed. See [docs/adding-a-workload.md](docs/adding-a-workload.md).
- **New application**: `./obench new app lammps` creates `app.toml`, `build.sh`
  and `hooks.py`. See [docs/adding-an-application.md](docs/adding-an-application.md).
- **New cluster**: `./obench new site NAME`. See [docs/site-setup.md](docs/site-setup.md).

The design is described in [docs/architecture.md](docs/architecture.md).

## Status and caveats

- The harness is tested (`python -m pytest tests`) on a workstation, including
  end-to-end runs of generated job scripts with a toy application. **The
  GROMACS, WarpX and heFFTe builds and runs have not yet been executed on an
  Intel GPU cluster.** Every workload is therefore marked `unvalidated`.
  Promote one to `validated` after reviewing its results on real hardware.
- The parser tests use log excerpts built from the print statements in each
  application's source code. Replace them with logs from real runs once
  available.
- Workload inputs are pinned by SHA-256, except PRACE UEABS test case C
  (355 MB): `obench fetch` prints its checksum on first download.
- On workload selection: NERSC's NERSC-10 benchmark suite includes none of
  these three applications. The published workloads come from PRACE UEABS,
  MPI-NAT, HECBioSim, the heFFTe ICCS 2020 paper, and the WarpX developers'
  former performance suite, which was run at OLCF and NERSC.

## Repository layout

```
obench                 launcher (runs from a checkout, no installation needed)
src/obench/            the harness (pure Python standard library)
apps/<app>/            app.toml, build.sh, hooks.py, workloads/*.toml
sites/                 cluster profiles (example-pvc.toml, local.toml)
templates/             starting points used by `obench new`
docs/                  architecture, how-to guides, workload catalog
tests/                 unit and end-to-end tests
```
