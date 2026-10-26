local base = import "../../ACE_quick2h_offline_online/qwen3.8-flash/common.libsonnet";
local project_home_path = std.extVar("APPWORLD_PROJECT_PATH");

base {
    playbooks_path: project_home_path + "/experiments/playbooks/quick2h_v1train_v2test_20261026/qwen3.8-flash",
}
