#!/bin/bash
# Build WarpX (3D, MPI, SYCL) and provide a stable executable name bin/warpx.3d.
set -euo pipefail

extra=()
if [ -n "${AMREX_INTEL_ARCH}" ]; then
  extra+=(-DAMReX_INTEL_ARCH="${AMREX_INTEL_ARCH}")
fi
unset AMREX_INTEL_ARCH   # AMReX also reads it from the environment; pass it only via CMake

cmake -S "$OBENCH_SRC_DIR" -B "$OBENCH_BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OBENCH_PREFIX" \
  -DCMAKE_C_COMPILER=icx \
  -DCMAKE_CXX_COMPILER=icpx \
  -DWarpX_COMPUTE=SYCL \
  -DWarpX_DIMS="${WARPX_DIMS}" \
  -DWarpX_FFT="${WARPX_FFT}" \
  -DWarpX_MPI=ON \
  -DWarpX_OPENPMD="${WARPX_OPENPMD}" \
  -DWarpX_QED="${WARPX_QED}" \
  -DWarpX_PRECISION="${WARPX_PRECISION}" \
  -DWarpX_PYTHON=OFF \
  ${extra[@]+"${extra[@]}"} \
  $CMAKE_EXTRA
cmake --build "$OBENCH_BUILD_DIR" -j "$OBENCH_JOBS"
cmake --install "$OBENCH_BUILD_DIR"

# The installed binary carries the build options in its name, e.g.
# warpx.3d.MPI.SYCL.DP.PDP.FFT; link it to a fixed name for the workloads.
cd "$OBENCH_PREFIX/bin"
if [ ! -e warpx.3d ]; then
  binary=$(ls warpx.3d.* 2>/dev/null | head -1 || true)
  if [ -z "$binary" ]; then
    echo "no warpx.3d.* executable installed in $OBENCH_PREFIX/bin" >&2
    exit 1
  fi
  ln -s "$binary" warpx.3d
fi
