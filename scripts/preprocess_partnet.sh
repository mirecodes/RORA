#!/usr/bin/env bash
# PartNet-Mobility URDF -> pipeline input mesh. Settings: cfgs/partnet_v0_preprocessing/partnet_v0_preprocessing_cfg.yml
#   bash scripts/preprocess_partnet.sh [voxel|manifold|all]   (default: voxel)
#   voxel    -> data/objects/<name>/mesh.ply        (pipeline input)
#   manifold -> data/objects/<name>/mesh_fused.ply
set -e
cd "$(dirname "$0")/.."
DIR=functions/partnet_v0_preprocessing

case "${1:-voxel}" in
  voxel)    python $DIR/voxel_remeshing.py ;;
  manifold) python $DIR/merge_manifold.py ;;
  all)      python $DIR/voxel_remeshing.py && python $DIR/merge_manifold.py ;;
  *)        echo "usage: $0 [voxel|manifold|all]" >&2; exit 1 ;;
esac
