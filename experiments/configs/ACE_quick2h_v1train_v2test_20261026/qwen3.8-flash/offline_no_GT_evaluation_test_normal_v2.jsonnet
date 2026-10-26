local common = import "common.libsonnet";
common.evaluation(
    "quick2h_test_normal_v2",
    common.playbooks_path + "/offline_no_GT.txt",
)
