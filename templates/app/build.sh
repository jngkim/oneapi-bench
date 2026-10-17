#!/bin/bash
# Build @APP@ with the oneAPI toolchain. obench runs this after loading the site
# toolchain and exporting:
#   OBENCH_SRC_DIR    unpacked source        OBENCH_BUILD_DIR  scratch build directory
#   OBENCH_PREFIX     install prefix         OBENCH_JOBS       parallel jobs
#   OBENCH_VERSION    application version    OBENCH_MPI_GPU_AWARE  ON/OFF from the site
# plus every key of [build.env] in app.toml.
set -euo pipefail

cmake -S "$OBENCH_SRC_DIR" -B "$OBENCH_BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OBENCH_PREFIX" \
  -DCMAKE_C_COMPILER=icx \
  -DCMAKE_CXX_COMPILER=icpx \
  $CMAKE_EXTRA
cmake --build "$OBENCH_BUILD_DIR" -j "$OBENCH_JOBS"
cmake --install "$OBENCH_BUILD_DIR"
