"""Cache-isolated official AppWorld reward evaluation.

AppWorld's evaluator mutates process-global database/cache state. Calling it
inside a still-open world can therefore change the state later API calls see.
Formal execution evaluates the on-disk state in a short-lived subprocess at
the same before/after points used by the original agent.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def evaluate_reward(task_id: str, experiment_name: str) -> dict:
    """Evaluate one persisted task state in this otherwise-clean process."""

    from appworld.apps.model_lib import CachedDBHandler
    from appworld.evaluator import evaluate_task

    if not CachedDBHandler.is_empty():
        raise RuntimeError("Isolated AppWorld evaluator started with a nonempty DB cache")
    try:
        tracker, _ = evaluate_task(
            task_id=task_id,
            experiment_name=experiment_name,
            save_report=True,
        )
        passes = len(tracker.passes)
        failures = len(tracker.failures)
        if passes + failures <= 0:
            raise RuntimeError("Official AppWorld evaluator returned no tests")
        return {
            "task_id": task_id,
            "experiment_name": experiment_name,
            "passes": passes,
            "failures": failures,
            "reward": passes / (passes + failures),
        }
    finally:
        CachedDBHandler.reset()


def isolated_reward(task_id: str, experiment_name: str, *, runner=subprocess.run) -> float:
    """Return the official reward without touching the caller's DB cache."""

    completed = runner(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--task-id",
            task_id,
            "--experiment-name",
            experiment_name,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Isolated AppWorld evaluator returned no result")
    payload = json.loads(lines[-1])
    if (
        payload.get("task_id") != task_id
        or payload.get("experiment_name") != experiment_name
        or type(payload.get("passes")) is not int
        or type(payload.get("failures")) is not int
        or not isinstance(payload.get("reward"), (int, float))
        or payload["passes"] + payload["failures"] <= 0
    ):
        raise RuntimeError("Isolated AppWorld evaluator returned an invalid result")
    expected = payload["passes"] / (payload["passes"] + payload["failures"])
    if float(payload["reward"]) != expected:
        raise RuntimeError("Isolated AppWorld evaluator reward/counts disagree")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--experiment-name", required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate_reward(args.task_id, args.experiment_name), sort_keys=True))


if __name__ == "__main__":
    main()
