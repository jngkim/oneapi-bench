#!/bin/bash
# Bind each MPI rank to one Intel GPU device, then exec the application.
#
#   srun ... gpu_bind.sh <application> [args...]
#
# Settings (exported by obench job scripts from the site file):
#   OBENCH_GPU_MODE          gpu  -> one device per GPU card (Level Zero COMPOSITE hierarchy)
#                            tile -> one device per GPU tile/stack (Level Zero FLAT hierarchy)
#   OBENCH_RANKS_PER_DEVICE  ranks sharing one device (default 1)
#   OBENCH_DEVICE_LIST       optional explicit device ids, e.g. "0,1,4,5"; rank i uses entry i
#   OBENCH_BIND_DISABLE=1    do not touch ZE_AFFINITY_MASK (application binds devices itself)
#   OBENCH_BIND_VERBOSE=1    print the mapping of each rank to stderr
set -u

local_rank=${SLURM_LOCALID:-${MPI_LOCALRANKID:-${PALS_LOCAL_RANKID:-${OMPI_COMM_WORLD_LOCAL_RANK:-${PMI_LOCAL_RANK:-0}}}}}

if [ "${OBENCH_BIND_DISABLE:-0}" != 1 ]; then
  case "${OBENCH_GPU_MODE:-gpu}" in
    tile) export ZE_FLAT_DEVICE_HIERARCHY=FLAT ;;
    gpu)  export ZE_FLAT_DEVICE_HIERARCHY=COMPOSITE ;;
    *) echo "gpu_bind.sh: unknown OBENCH_GPU_MODE '${OBENCH_GPU_MODE}'" >&2; exit 2 ;;
  esac
  slot=$(( local_rank / ${OBENCH_RANKS_PER_DEVICE:-1} ))
  if [ -n "${OBENCH_DEVICE_LIST:-}" ]; then
    IFS=, read -r -a devices <<< "${OBENCH_DEVICE_LIST}"
    if [ "$slot" -ge "${#devices[@]}" ]; then
      echo "gpu_bind.sh: local rank $local_rank needs device slot $slot but OBENCH_DEVICE_LIST has ${#devices[@]} entries" >&2
      exit 2
    fi
    device=${devices[$slot]}
  else
    device=$slot
  fi
  export ZE_AFFINITY_MASK=$device
fi

if [ "${OBENCH_BIND_VERBOSE:-0}" = 1 ]; then
  echo "gpu_bind.sh: host=$(hostname) local_rank=$local_rank ZE_FLAT_DEVICE_HIERARCHY=${ZE_FLAT_DEVICE_HIERARCHY:-unset} ZE_AFFINITY_MASK=${ZE_AFFINITY_MASK:-unset}" >&2
fi

exec "$@"
