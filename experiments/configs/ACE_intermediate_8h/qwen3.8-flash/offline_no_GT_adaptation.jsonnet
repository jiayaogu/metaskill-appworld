local common = import "common.libsonnet";
common.adaptation(
    "intermediate_8h_train",
    common.playbooks_path + "/offline_no_GT.txt",
)
