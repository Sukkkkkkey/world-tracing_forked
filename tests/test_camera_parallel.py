
from scripts.run_camera_parallel_evaluation import partition_candidates


def test_parallel_shards_keep_all_configurations_of_an_asset_together():
    candidates = [dict(sample_id=sample, method="wt_trellis2", config_id=config, stage=stage, seed=42)
                  for sample in ("a", "b", "c") for config in ("defaults-v1", "shared-wt-v1")
                  for stage in ("decoded", "glb")]
    shards = partition_candidates(candidates, 2)
    assert [len(row) for row in shards] == [8, 4]
    assert {row["sample_id"] for row in shards[0]}.isdisjoint({row["sample_id"] for row in shards[1]})
    assert sum(map(len, shards)) == len(candidates)
