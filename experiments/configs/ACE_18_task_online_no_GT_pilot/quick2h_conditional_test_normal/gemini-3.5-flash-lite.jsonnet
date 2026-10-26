local project_home_path = std.extVar("APPWORLD_PROJECT_PATH");
local experiment_prompts_path = project_home_path + "/experiments/prompts";
local experiment_playbooks_path = project_home_path + "/experiments/playbooks";
local pilot_output_path = project_home_path + "/experiments/outputs/ACE_18_task_online_no_GT_pilot/quick2h_conditional_test_normal/gemini-3.5-flash-lite";

local model_config = {
    "name": "gemini-3.5-flash-lite",
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
    "use_cache": true,
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
            "fd1f8fa_1",
            "fd1f8fa_2",
            "fd1f8fa_3",
            "ccf4b82_1",
            "ccf4b82_2",
            "ccf4b82_3",
            "3b8fb7a_1",
            "3b8fb7a_2",
            "3b8fb7a_3",
            "f323bae_1",
            "f323bae_2",
            "f323bae_3",
            "3aa1a22_1",
            "3aa1a22_2",
            "3aa1a22_3"
        ],
    }
}
