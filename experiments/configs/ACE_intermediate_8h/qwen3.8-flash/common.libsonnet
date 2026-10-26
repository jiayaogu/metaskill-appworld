local project_home_path = std.extVar("APPWORLD_PROJECT_PATH");
local experiment_prompts_path = project_home_path + "/experiments/prompts";
local experiment_playbooks_path = project_home_path + "/experiments/playbooks";

local model_config = {
    "name": "qwen3.8-flash",
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

local common_agent_config = {
    "appworld_config": {
        "random_seed": 123,
    },
    "logger_config": {
        "color": true,
        "verbose": true,
    },
    "generator_prompt_file_path": experiment_prompts_path + "/appworld_react_generator_prompt.txt",
    "ignore_multiple_calls": true,
    "max_steps": 40,
    "max_cost_overall": 1000,
    "max_cost_per_task": 10,
    "log_lm_calls": true,
};

{
    playbooks_path: experiment_playbooks_path + "/intermediate_8h/qwen3.8-flash",

    adaptation(dataset, trained_playbook_file_path): {
        "type": "ace",
        "config": {
            "run_type": "ace-adaptation",
            "agent": common_agent_config + {
                "type": "ace_adaptation_react",
                "generator_model_config": model_config,
                "reflector_model_config": model_config,
                "curator_model_config": model_config,
                "reflector_prompt_file_path": experiment_prompts_path + "/appworld_react_reflector_no_gt_prompt.txt",
                "curator_prompt_file_path": experiment_prompts_path + "/appworld_react_curator_prompt.txt",
                "initial_playbook_file_path": experiment_playbooks_path + "/appworld_initial_playbook.txt",
                "trained_playbook_file_path": trained_playbook_file_path,
                "use_gt_code": false,
            },
            "dataset": dataset,
            "num_epochs": 1,
        },
    },

    evaluation(dataset, trained_playbook_file_path): {
        "type": "ace",
        "config": {
            "run_type": "ace-evaluation",
            "agent": common_agent_config + {
                "type": "ace_evaluation_react",
                "generator_model_config": model_config,
                "trained_playbook_file_path": trained_playbook_file_path,
            },
            "dataset": dataset,
        },
    },
}
