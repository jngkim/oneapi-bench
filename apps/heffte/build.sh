#!/bin/bash
# Build heFFTe with the oneAPI (oneMKL DFT on SYCL GPUs) backend and install the
# speed3d benchmark drivers into $OBENCH_PREFIX/bin.
set -euo pipefail

: "${MKLROOT:?MKLROOT is not set; load oneMKL in the site [toolchain] setup}"
gpu_aware=(-DHeffte_ENABLE_GPU_AWARE_MPI=ON)
if [ "$OBENCH_MPI_GPU_AWARE" != ON ]; then
  gpu_aware=(-DHeffte_DISABLE_GPU_AWARE_MPI=ON)
fi

cmake -S "$OBENCH_SRC_DIR" -B "$OBENCH_BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OBENCH_PREFIX" \
  -DCMAKE_C_COMPILER=icx \
  -DCMAKE_CXX_COMPILER=icpx \
  -DBUILD_SHARED_LIBS=OFF \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DHeffte_ENABLE_ONEAPI=ON \
  -DHeffte_ONEMKL_ROOT="$MKLROOT" \
  -DHeffte_ENABLE_MKL="${HEFFTE_ENABLE_MKL}" \
  -DHeffte_ENABLE_TESTING=ON \
  "${gpu_aware[@]}" \
  $CMAKE_EXTRA
cmake --build "$OBENCH_BUILD_DIR" -j "$OBENCH_JOBS"
cmake --install "$OBENCH_BUILD_DIR"

mkdir -p "$OBENCH_PREFIX/bin"
for exe in speed3d_c2c speed3d_r2c speed3d_r2r convolution; do
  if [ -x "$OBENCH_BUILD_DIR/benchmarks/$exe" ]; then
    cp "$OBENCH_BUILD_DIR/benchmarks/$exe" "$OBENCH_PREFIX/bin/"
  fi
done
