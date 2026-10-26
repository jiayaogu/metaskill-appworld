local common = import "common.libsonnet";
common.evaluation("quick2h_test_challenge_v2", std.extVar("APPWORLD_PROJECT_PATH") + "/experiments/playbooks/quick2h_offline_online/qwen3.8-flash/offline_no_GT.txt")
