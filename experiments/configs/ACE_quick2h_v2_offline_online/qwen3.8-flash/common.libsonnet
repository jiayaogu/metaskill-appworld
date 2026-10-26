local base = import "../../ACE_quick2h_offline_online/qwen3.8-flash/common.libsonnet";
local project_home_path = std.extVar("APPWORLD_PROJECT_PATH");
local request_timeout = { timeout: 3600 };

{
    playbooks_path: project_home_path + "/experiments/playbooks/quick2h_v1train_v2test_20261026_retry1/qwen3.8-flash",

    adaptation(dataset, trained_playbook_file_path): base.adaptation(dataset, trained_playbook_file_path) {
        config+: {
            agent+: {
                generator_model_config+: request_timeout,
                reflector_model_config+: request_timeout,
                curator_model_config+: request_timeout,
            },
        },
    },

    evaluation(dataset, trained_playbook_file_path): base.evaluation(dataset, trained_playbook_file_path) {
        config+: {
            agent+: {
                generator_model_config+: request_timeout,
            },
        },
    },
}
