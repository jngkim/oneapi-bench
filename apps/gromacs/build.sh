#!/bin/bash
# Build GROMACS (MPI, SYCL/DPC++, oneMKL). Settings come from app.toml [build.env].
set -euo pipefail

extra=()
if [ -n "${GMX_SIMD}" ]; then
  extra+=(-DGMX_SIMD="${GMX_SIMD}")
fi
if [ -n "${GMX_GPU_NB_NUM_CLUSTER_PER_CELL_X}" ]; then
  extra+=(-DGMX_GPU_NB_NUM_CLUSTER_PER_CELL_X="${GMX_GPU_NB_NUM_CLUSTER_PER_CELL_X}")
fi
if [ "${GMX_USE_HEFFTE}" = ON ]; then
  if [ -z "${HEFFTE_PREFIX:-}" ]; then
    echo "GMX_USE_HEFFTE=ON requires heFFTe built with the same toolchain: obench build heffte" >&2
    exit 1
  fi
  extra+=(-DGMX_USE_HEFFTE=ON -DHeffte_ROOT="${HEFFTE_PREFIX}")
fi

cmake -S "$OBENCH_SRC_DIR" -B "$OBENCH_BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OBENCH_PREFIX" \
  -DCMAKE_C_COMPILER=icx \
  -DCMAKE_CXX_COMPILER=icpx \
  -DGMX_MPI=ON \
  -DGMX_OPENMP=ON \
  -DGMX_GPU=SYCL \
  -DGMX_SYCL=DPCPP \
  -DGMX_FFT_LIBRARY=mkl \
  -DGMX_GPU_FFT_LIBRARY="${GMX_GPU_FFT_LIBRARY}" \
  -DGMX_GPU_NB_CLUSTER_SIZE="${GMX_GPU_NB_CLUSTER_SIZE}" \
  -DGMX_BUILD_OWN_FFTW=OFF \
  -DREGRESSIONTEST_DOWNLOAD=OFF \
  ${extra[@]+"${extra[@]}"} \
  $CMAKE_EXTRA
cmake --build "$OBENCH_BUILD_DIR" -j "$OBENCH_JOBS"
cmake --install "$OBENCH_BUILD_DIR"
