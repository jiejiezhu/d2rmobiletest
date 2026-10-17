#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TASK_ROOT="$PWD"
mkdir -p .tools
SPIRV_COMMIT=$(python -c 'import json; print(json.load(open("build-config.json"))["spirv_commit"])')
HACTOOL_COMMIT=$(python -c 'import json; print(json.load(open("build-config.json"))["hactool_commit"])')
if [[ ! -x .tools/bin/spirv-cross || ! -x .tools/bin/hactool ]]; then
  TOOL_BUILD=$(mktemp -d)
  trap 'rm -rf "$TOOL_BUILD"' EXIT
  git clone --quiet https://github.com/KhronosGroup/SPIRV-Cross.git "$TOOL_BUILD/spirv"
  git -C "$TOOL_BUILD/spirv" checkout --quiet "$SPIRV_COMMIT"
  cmake -S "$TOOL_BUILD/spirv" -B "$TOOL_BUILD/spirv/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++ -DSPIRV_CROSS_ENABLE_TESTS=OFF
  cmake --build "$TOOL_BUILD/spirv/build" --target spirv-cross -j 2
  mkdir -p .tools/bin
  cp "$TOOL_BUILD/spirv/build/spirv-cross" .tools/bin/
  git clone --quiet https://github.com/SciresM/hactool.git "$TOOL_BUILD/hactool"
  git -C "$TOOL_BUILD/hactool" checkout --quiet "$HACTOOL_COMMIT"
  cp "$TOOL_BUILD/hactool/config.mk.template" "$TOOL_BUILD/hactool/config.mk"
  make -C "$TOOL_BUILD/hactool" -j 2 CC=clang
  cp "$TOOL_BUILD/hactool/hactool" .tools/bin/
fi
export PATH="$TASK_ROOT/.tools/bin:$PATH"
if [[ "${SOURCE_BUILD:-0}" != 1 ]]; then python scripts/ci.py shell; fi
mkdir -p "$DM_ROOT/build/gfx/dmsh_xlate"
dotnet publish upstream/dm/gfx/tools/dmsh_xlate -c Release \
  -o "$DM_ROOT/build/gfx/dmsh_xlate" -v quiet
"$DM_ROOT/build/gfx/dmsh_xlate/dmsh_xlate" --source-sha
python upstream/dm/gfx/tools/nometal_run.py upstream/dm/gfx/tools/dmsh_chain.py --update-lock
python upstream/dm/gfx/tools/nometal_run.py upstream/dm/gfx/tools/dmsh_chain.py --check-tools
