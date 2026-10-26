local common = import "common.libsonnet";
common.adaptation(
    "quick2h_train",
    common.playbooks_path + "/offline_no_GT.txt",
)
