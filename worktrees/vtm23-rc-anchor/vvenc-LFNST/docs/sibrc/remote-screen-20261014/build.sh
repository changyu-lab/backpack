#!/bin/bash
set -e
cd /data/vtmrc-vvenc-tune-20261014
cmake -S vvenc -B build -DCMAKE_BUILD_TYPE=Release -DVVENC_ENABLE_LINK_TIME_OPT=OFF -DCMAKE_CXX_FLAGS=-Wno-error=misleading-indentation
cmake --build build --target vvencFFapp -j 24
cmake -S metrics360 -B metrics-build -DCMAKE_BUILD_TYPE=Release
cmake --build metrics-build -j 16
python3 -m pip install --user psutil
find vvenc/bin build -type f -name vvencFFapp
