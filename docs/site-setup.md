# Setting up a site

A site file describes one cluster. Create it from the commented template, then
check it:

```bash
./obench new site mycluster
$EDITOR sites/mycluster.toml
./obench validate --site mycluster
./obench doctor --site mycluster                 # on the login node
srun -N1 --pty ./obench doctor --site mycluster  # on a compute node: also lists GPUs
```

`sites/example-pvc.toml` is a complete example for nodes with four Intel Data
Center GPU Max 1550 cards. `sites/local.toml` runs jobs directly with bash.

## Sections

### `[node]`: what one node has

| Key | Meaning |
|---|---|
| `gpus_per_node` | Physical GPU cards |
| `tiles_per_gpu` | Tiles (stacks) per card: 2 for Max 1550, 1 for Max 1100 and most others |
| `gpu_mode` | `tile`: one MPI rank per tile; `gpu`: one rank per card (see below) |
| `cores_per_node` | Physical CPU cores, shared evenly between the ranks of a node |

### GPU mode: tiles or whole GPUs

`gpu_bind.sh` runs in front of every rank. It selects the rank's device from its
node-local rank (`SLURM_LOCALID`, `MPI_LOCALRANKID`, `PALS_LOCAL_RANKID`, ...):

| `gpu_mode` | Level Zero setting | Devices per node (4 x Max 1550) | Rank 3 sees |
|---|---|---|---|
| `tile` | `ZE_FLAT_DEVICE_HIERARCHY=FLAT` | 8 | `ZE_AFFINITY_MASK=3` (card 1, tile 1) |
| `gpu` | `ZE_FLAT_DEVICE_HIERARCHY=COMPOSITE` | 4 | `ZE_AFFINITY_MASK=3` (card 3, both tiles) |

Overrides, set with `--env` or in `[env]`:

- `OBENCH_DEVICE_LIST=0,1,4,5` uses specific devices.
- `OBENCH_BIND_DISABLE=1` leaves the selection to the application.
- `OBENCH_BIND_VERBOSE=1` prints each rank's mapping to stderr.

### `[toolchain]`

`setup` lists shell lines run at the start of every build and job. They must
make `icx`, `icpx`, MPI, oneMKL (`MKLROOT`) and CMake available:

```toml
setup = ["module load oneapi/2025.2 cmake/3.30"]
# or
setup = ["source /opt/intel/oneapi/setvars.sh --force > /dev/null"]
```

`tag` names the toolchain in install paths. Changing the oneAPI version and
tag therefore keeps the old builds for comparison.

### `[slurm]`

`partition`, `account`, `qos` and `constraint` become `#SBATCH` lines when not
empty. `directives` adds further lines verbatim, e.g.
`["--exclusive", "--gpus-per-node=4"]`.

### `[mpi]`

| Key | Meaning |
|---|---|
| `launcher` | `srun` (default), `mpiexec` (Intel MPI / MPICH Hydra), `none`, or a template such as `"srun --mpi=pmi2 -n {ranks} --ntasks-per-node={ranks_per_node} -c {cpus_per_rank} --cpu-bind=cores"` |
| `gpu_aware` | `true` if MPI can send GPU buffers directly. Builds use it (heFFTe), runs pass it on (WarpX `amrex.use_gpu_aware_mpi`) |
| `env` | MPI environment, e.g. `I_MPI_OFFLOAD = "1"` (Intel MPI GPU buffers) or `MPIR_CVAR_ENABLE_GPU = "1"` (MPICH) |

With Intel MPI under `srun` you may need
`I_MPI_PMI_LIBRARY = "/usr/lib64/libpmi2.so"` and `--mpi=pmi2`. Use
`obench doctor` and a small `--dry-run` job to confirm.

### `[paths]`

| Key | Default | Notes |
|---|---|---|
| `install_root` | `~/obench/install` | Builds, `<app>/<version>-<tag>` |
| `build_root` | `~/obench/build` | Sources and build trees (can be large) |
| `data_root` | `~/obench/data` | Inputs; **must be readable from compute nodes** |
| `results_root` | `results` | Relative paths are inside the repository |

### `[apps.<app>]`: per-application settings for this site

```toml
[apps.gromacs]
version = "2026.4"
build_env = { GMX_SIMD = "AVX_512", GMX_USE_HEFFTE = "ON" }
run_env = { GMX_GPU_PME_DECOMPOSITION = "1" }

[apps.warpx]
build_env = { AMREX_INTEL_ARCH = "pvc" }    # ahead-of-time compilation for PVC
```

## Interactive use

Inside an allocation (`salloc -N 2 ...`), pass `--scheduler local` to
`obench run` to run the jobs immediately in the current allocation, one after
another.
