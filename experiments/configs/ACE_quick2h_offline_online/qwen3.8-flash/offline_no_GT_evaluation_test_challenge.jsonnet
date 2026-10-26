local common = import "common.libsonnet";
common.evaluation(
    "quick2h_test_challenge",
    common.playbooks_path + "/offline_no_GT.txt",
)
