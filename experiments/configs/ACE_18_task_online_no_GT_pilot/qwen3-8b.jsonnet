local project_home_path = std.extVar("APPWORLD_PROJECT_PATH");
local experiment_prompts_path = project_home_path + "/experiments/prompts";
local experiment_playbooks_path = project_home_path + "/experiments/playbooks";
local pilot_output_path = project_home_path + "/experiments/outputs/ACE_18_task_online_no_GT_pilot/qwen3-8b";

local model_config = {
    "name": "qwen3-8b",
    "provider": "openai",
    "completion_method": "openai",
    "base_url": "https://az.gptplus5.com/v1",
    "temperature": 0,
    "seed": 100,
    "stop": ["<|endoftext|>", "<|eot_id|>", "<|start_header_id|>"],
    "logprobs": false,
    "top_logprobs": null,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "n": 1,
    "response_format": {"type": "text"},
    "retry_after_n_seconds": 10,
    "use_cache": false,
    "max_retries": 50,
};

{
    "type": "ace",
    "config": {
        "run_type": "ace-adaptation",
        "agent": {
            "type": "ace_adaptation_react",
            "generator_model_config": model_config,
            "reflector_model_config": model_config,
            "curator_model_config": model_config,
            "appworld_config": {
                "random_seed": 123,
            },
            "logger_config": {
                "color": true,
                "verbose": true,
            },
            "generator_prompt_file_path": experiment_prompts_path + "/appworld_react_generator_prompt.txt",
            "reflector_prompt_file_path": experiment_prompts_path + "/appworld_react_reflector_no_gt_prompt.txt",
            "curator_prompt_file_path": experiment_prompts_path + "/appworld_react_curator_prompt.txt",
            "initial_playbook_file_path": experiment_playbooks_path + "/appworld_initial_playbook.txt",
            "trained_playbook_file_path": pilot_output_path + "/trained_playbook.txt",
            "ignore_multiple_calls": true,
            "max_steps": 40,
            "max_cost_overall": 1000,
            "max_cost_per_task": 10,
            "log_lm_calls": true,
        },
        "task_ids": [
            "07b42fd_1",
            "07b42fd_2",
            "07b42fd_3",
            "e3d6c94_1",
            "e3d6c94_2",
            "e3d6c94_3",
            "76f2c72_1",
            "76f2c72_2",
            "76f2c72_3",
            "2a163ab_1",
            "2a163ab_2",
            "2a163ab_3",
            "3c13f5a_1",
            "3c13f5a_2",
            "3c13f5a_3",
            "d0b1f43_1",
            "d0b1f43_2",
            "d0b1f43_3"
],
    }
}
