local common = import "common.libsonnet";
common.evaluation(
    "intermediate_8h_test_normal",
    common.playbooks_path + "/offline_no_GT.txt",
)
