#!/usr/bin/env bash
# Reproduce the independently versioned upstream checkouts; no global Git changes.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dependencies
while read -r name revision; do
    case "$name" in
        TRELLIS.2) url=https://github.com/microsoft/TRELLIS.2.git ;;
        CuMesh) url=https://github.com/JeffreyXiang/CuMesh.git ;;
        FlexGEMM) url=https://github.com/JeffreyXiang/FlexGEMM.git ;;
        nvdiffrast) url=https://github.com/NVlabs/nvdiffrast.git ;;
        nvdiffrec) url=https://github.com/JeffreyXiang/nvdiffrec.git ;;
        utils3d) url=https://github.com/EasternJournalist/utils3d.git ;;
        *) echo "Unknown dependency: $name" >&2; exit 1 ;;
    esac
    checkout="dependencies/$name"
    if [ ! -e "$checkout" ]; then
        git init "$checkout"
        git -C "$checkout" remote add origin "$url"
        git -C "$checkout" fetch --depth 1 origin "$revision"
        git -C "$checkout" checkout --detach FETCH_HEAD
    fi
    if [ ! -d "$checkout/.git" ]; then
        echo "Existing dependency directory is not a Git checkout: $checkout" >&2
        exit 1
    fi
    if [ "$(git -C "$checkout" rev-parse HEAD)" != "$revision" ]; then
        if [ -n "$(git -C "$checkout" status --porcelain)" ]; then
            echo "Refusing to change revision of modified checkout: $checkout" >&2
            exit 1
        fi
        echo "Existing checkout revision differs from dependencies.lock: $checkout" >&2
        exit 1
    fi
    git -c url.https://github.com/eigen-mirror/eigen.insteadOf=https://gitlab.com/libeigen/eigen \
        -C "$checkout" submodule update --init --recursive
done < dependencies.lock
patch_file=../../scripts/patches/flexgemm-cache.patch
if git -C dependencies/FlexGEMM apply --check "$patch_file" 2>/dev/null; then
    git -C dependencies/FlexGEMM apply "$patch_file"
else
    git -C dependencies/FlexGEMM apply --reverse --check "$patch_file"
fi
