# flake8: noqa: E402, E501
# pylint: disable=E0611
"""A minimal ReAct Agent for AppWorld tasks."""
import os
import re
import time
import json
import datetime
from pathlib import Path
from typing import List, Any


import ray
import requests
from tqdm import tqdm
from loguru import logger
from openai import OpenAI
from jinja2 import Template
from dotenv import load_dotenv

from prompt import NEW_PROMPT_TEMPLATE
from appworld import AppWorld, load_task_ids
from appworld_reward import isolated_reward
from execution_audit import MemoryClient, audit_scope, checked_response, provider_http_client

os.environ.setdefault("APPWORLD_ROOT", ".")

load_dotenv("../../.env")


@ray.remote
class AppworldReactAgent:
    """A minimal ReAct Agent for AppWorld tasks."""

    def __init__(
        self,
        index: int,
        task_ids: List[str],
        experiment_name: str,
        model_name: str = "qwen3.8-flash",
        temperature: float = 0.9,
        max_interactions: int = 30,
        max_response_size: int = 129024,
        num_trials: int = 1,
        use_memory: bool = False,
        memory_base_url: str = "http://0.0.0.0:8002/",
        use_memory_addition: bool = False,
        use_memory_deletion: bool = False,
        delete_freq: int = 10,
        freq_threshold: int = 5,
        utility_threshold: float = 0.5,
        audit_identity: dict | None = None,
        audit_token: str = "",
    ):

        self.index: int = index
        self.task_ids: List[str] = task_ids
        self.experiment_name: str = experiment_name
        self.model_name: str = model_name
        self.temperature: float = temperature
        self.max_interactions: int = max_interactions
        self.max_response_size: int = max_response_size
        self.num_trials: int = num_trials
        self.use_memory: bool = use_memory
        self.use_memory_addition: bool = use_memory_addition if use_memory else False
        self.use_memory_deletion: bool = use_memory_deletion if use_memory else False
        self.delete_freq: int = delete_freq
        self.freq_threshold: int = freq_threshold
        self.utility_threshold: float = utility_threshold

        self.audit_identity = audit_identity
        self._audit_log_sink = None
        self.memory_client = MemoryClient(memory_base_url, audit_identity, audit_token) if audit_identity else None
        self.llm_client = OpenAI(http_client=provider_http_client()) if audit_identity else OpenAI()
        self.memory_base_url: str = memory_base_url

        self.history: List[List[List[dict]]] = [[] for _ in range(num_trials)]
        self.retrieved_memory_list: List[List[List[Any]]] = [[] for _ in range(num_trials)]

        for run_id in range(num_trials):
            for _ in range(len(task_ids)):
                self.retrieved_memory_list[run_id].append([])
                self.history[run_id].append([])

    def call_llm(self, messages: list) -> str:
        """Call the LLM to generate a response to the messages."""
        for i in range(100):
            try:
                response = self.llm_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=self.temperature,
                    extra_body={"enable_thinking": False},
                    seed=0,
                )

                return response.choices[0].message.content

            except Exception as e:
                if type(e).__name__ == "LLMLoggingError":
                    raise
                logger.exception(f"encounter error with {e.args}")
                time.sleep(1 + i * 10)

        raise RuntimeError("Executor provider retries exhausted; task incomplete")

    def prompt_messages(self, run_id, task_index, previous_memories: None, world: AppWorld):
        """Prompt the messages to the LLM."""
        if self.audit_identity and self._audit_log_sink is None:
            log_path = Path(self.audit_identity["run_directory"]) / "tasks" / world.task_id / "logs/loggger.log"
            self._audit_log_sink = logger.add(str(log_path))
        app_descriptions = json.dumps(
            [{"name": k, "description": v} for (k, v) in world.task.app_descriptions.items()],
            indent=1,
        )
        dictionary = {"supervisor": world.task.supervisor, "app_descriptions": app_descriptions}
        sys_prompt = Template(NEW_PROMPT_TEMPLATE.lstrip()).render(dictionary)
        query = world.task.instruction
        if self.use_memory:
            if len(previous_memories) == 0:
                response = self.get_memory(world.task.instruction)
                if response and "memory_list" in response["metadata"]:
                    self.retrieved_memory_list[run_id][task_index] = response["metadata"]["memory_list"]
                    task_memory = re.sub(r"\bMemory\s*(\d+)\s*[:]", r"Experience \1:", response["answer"])
                    logger.info(f"loaded task_memory: {task_memory}")
                    query = (
                        "Task:\n"
                        + query
                        + "\n\nSome Related Experience to help you to complete the task:\n"
                        + task_memory
                    )
            else:
                formatted_memories = []
                for i, memory in enumerate(previous_memories, 1):
                    condition = memory["when_to_use"]
                    memory_content = memory["content"]
                    memory_text = f"Experience {i}:\n When to use: {condition}\n Content: {memory_content}\n"
                    formatted_memories.append(memory_text)
                query = (
                    "Task:\n"
                    + query
                    + "\n\nSome Related Experience to help you to complete the task:\n"
                    + "\n".join(formatted_memories)
                )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": query},
        ]
        self.history[run_id][task_index] = messages

    @staticmethod
    def get_reward(world) -> float:
        """Get the official reward without polluting the open world's DB cache."""
        return isolated_reward(world.task_id, world.experiment_name)

    def extract_code_and_fix_content(
        self,
        text: str,
        ignore_multiple_calls=True,
    ) -> tuple[str, str]:
        """Extract the code and fix the content."""
        full_code_regex = r"```python\n(.*?)```"
        partial_code_regex = r".*```python\n(.*)"

        original_text = text
        output_code = ""
        match_end = 0
        # Handle multiple calls
        for re_match in re.finditer(full_code_regex, original_text, flags=re.DOTALL):
            code = re_match.group(1).strip()
            if ignore_multiple_calls:
                text = original_text[: re_match.end()]
                return code, text
            output_code += code + "\n"
            match_end = re_match.end()
        # check for partial code match at end (no terminating ```)  following the last match
        partial_match = re.match(
            partial_code_regex,
            original_text[match_end:],
            flags=re.DOTALL,
        )
        if partial_match:
            output_code += partial_match.group(1).strip()
            # terminated due to stop condition. Add stop condition to output.
            if not text.endswith("\n"):
                text = text + "\n"
            text = text + "```"
        if len(output_code) == 0:
            return text, text
        else:
            return output_code, text

    def execute(self):
        """Bind audit state after Ray deserialization and close the owned client."""
        try:
            if self.audit_identity:
                if len(self.task_ids) != 1 or self.num_trials != 1:
                    raise ValueError("Audited execution requires one task and one trial")
                with audit_scope(self.audit_identity):
                    result = self._execute()
                    if self.audit_identity.get("errors"):
                        raise RuntimeError("Provider failure occurred; run incomplete")
                    return result
            return self._execute()
        finally:
            self.llm_client.close()
            if self._audit_log_sink is not None:
                logger.remove(self._audit_log_sink)

    def _execute(self):
        """Execute the Appworld tasks."""
        result = []
        counter = 0
        for task_index, task_id in enumerate(tqdm(self.task_ids, desc=f"run_index={self.index}")):
            t_result = None
            previous_memories = []
            # Run each task num_trials times
            for run_id in range(self.num_trials):
                start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with AppWorld(task_id=task_id, experiment_name=f"{self.experiment_name}_run_{run_id}") as world:
                    before_score = self.get_reward(world)
                    for i in range(self.max_interactions):
                        if i == 0:
                            self.prompt_messages(
                                run_id=run_id,
                                task_index=task_index,
                                previous_memories=previous_memories,
                                world=world,
                            )
                        code_msg = self.call_llm(self.history[run_id][task_index])
                        code, _ = self.extract_code_and_fix_content(code_msg)
                        self.history[run_id][task_index].append({"role": "assistant", "content": code})

                        output = world.execute(code)
                        # if len(output) > self.max_response_size:
                        #     # logger.warning(f"output exceed max size={len(output)}")
                        #     output = output[: self.max_response_size]
                        self.history[run_id][task_index].append(
                            {"role": "user", "content": "Output:\n```\n" + output + "```\n\n"},
                        )

                        if world.task_completed():
                            break

                    after_score = self.get_reward(world)
                    uplift_score = after_score - before_score

                    if self.use_memory:
                        if self.use_memory_addition:
                            new_traj_list = [
                                self.get_traj_from_task_history(task_id, self.history[run_id][task_index], after_score),
                            ]
                            previous_memories = self.summary_memory(new_traj_list)
                            if after_score == 1:
                                self.add_memory(previous_memories)

                        # update the freq & utility attributes of retrieved memories
                        update_utility: bool = after_score == 1
                        self.update_memory_information(self.retrieved_memory_list[run_id][task_index], update_utility)

                    counter += 1
                    if self.use_memory_deletion:  # and counter % self.delete_freq == 0:
                        self.delete_memory()

                    t_result = {
                        "task_id": world.task_id,
                        "run_id": run_id,
                        "experiment_name": self.experiment_name,
                        "task_completed": world.task_completed(),
                        "before_score": before_score,
                        "after_score": after_score,
                        "uplift_score": uplift_score,
                        "task_history": self.history[run_id][task_index],
                        "task_start_time": start_time,
                    }
                    if after_score == 1:
                        break
            result.append(t_result)

        return result

    def handle_api_response(self, response: requests.Response):
        """Handle API response with proper error checking"""
        return checked_response(response)

    def _memory_call(self, endpoint, payload):
        if self.memory_client:
            return self.memory_client.call(endpoint, payload)
        response = requests.post(url=f"{self.memory_base_url}{endpoint}", json=payload, timeout=1800)
        return self.handle_api_response(response)

    def get_memory(self, query: str):
        """Retrieve relevant task memories based on a query"""
        result = self._memory_call("retrieve_task_memory", {
                "query": query,
                "enable_llm_rerank": False,
                "enable_score_filter": False,
                "top_k": 5,
                "enable_llm_rewrite": False,
            })
        if not isinstance(result.get("metadata", {}).get("memory_list"), list):
            raise RuntimeError("Retrieval response lacks memory_list")

        logger.info(f"query: {query}, response: {result}")
        return result

    def get_traj_from_task_history(self, task_id: str, task_history: list, reward: float):
        """Get the trajectory from the task history."""
        pattern = r"\n\nSome Related Experience to help you to complete the task:.*"
        task_history[1]["content"] = re.sub(pattern, "", task_history[1]["content"], flags=re.DOTALL)
        return {
            "task_id": task_id,
            "messages": task_history,
            "score": reward,
        }

    def summary_memory(self, trajectories):
        """Generate a summary of conversation messages and create task memories"""

        result = self._memory_call("summary_task_memory", {
                "trajectories": trajectories,
                "success_threshold": 1.0,
                "enable_soft_comparison": True,
                "validation_threshold": 0.5,
            })
        if not isinstance(result.get("metadata", {}).get("memory_list", []), list):
            raise RuntimeError("Summary response lacks memory_list")

        # Extract memory list from response
        memory_list = result.get("metadata", {}).get("memory_list", [])
        print(f"Task memory list created: {len(memory_list)} memories")
        return memory_list

    def add_memory(self, memory_list):
        """Add the memory to the memory pool."""
        self._memory_call("add_task_memory", {
                "memory_list": memory_list,
            })

    def update_memory_information(self, memory_list, update_utility: bool = False):
        """Update the memory information."""
        self._memory_call("record_task_memory", {
                "memory_list": memory_list,
                "update_utility": update_utility,
            })

    def delete_memory(self):
        """Delete the memory from the memory pool."""
        self._memory_call("delete_task_memory", {
                "freq_threshold": self.freq_threshold,
                "utility_threshold": self.utility_threshold,
            })


def main():
    """Main function to run the Appworld React Agent."""
    dataset_name = "train"
    task_ids = load_task_ids(dataset_name)
    agent = AppworldReactAgent(index=0, task_ids=task_ids[0:1], experiment_name=dataset_name, num_trials=1)
    result = agent.execute()
    logger.info(f"result={json.dumps(result)}")


if __name__ == "__main__":
    main()
