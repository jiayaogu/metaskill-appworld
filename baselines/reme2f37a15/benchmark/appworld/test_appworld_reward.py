"""Provider-free tests for cache-isolated AppWorld reward evaluation."""

import json
import types
import unittest
from unittest.mock import patch

import appworld_reward


class RewardTests(unittest.TestCase):
    def test_evaluate_reward_owns_and_resets_cache(self):
        tracker = types.SimpleNamespace(passes=[1, 2, 3], failures=[4])
        with (
            patch("appworld.apps.model_lib.CachedDBHandler.is_empty", return_value=True),
            patch("appworld.apps.model_lib.CachedDBHandler.reset") as reset,
            patch("appworld.evaluator.evaluate_task", return_value=(tracker, None)) as evaluate,
        ):
            result = appworld_reward.evaluate_reward("task", "experiment")
        self.assertEqual(result["reward"], 0.75)
        evaluate.assert_called_once_with(task_id="task", experiment_name="experiment", save_report=True)
        reset.assert_called_once_with()

    def test_isolated_reward_validates_subprocess_result(self):
        payload = {
            "task_id": "task",
            "experiment_name": "experiment",
            "passes": 9,
            "failures": 1,
            "reward": 0.9,
        }
        runner = unittest.mock.Mock(return_value=types.SimpleNamespace(stdout=json.dumps(payload) + "\n"))
        self.assertEqual(appworld_reward.isolated_reward("task", "experiment", runner=runner), 0.9)
        runner.assert_called_once()
        self.assertTrue(runner.call_args.kwargs["check"])
        self.assertTrue(runner.call_args.kwargs["capture_output"])

        payload["reward"] = 1.0
        runner.return_value = types.SimpleNamespace(stdout=json.dumps(payload) + "\n")
        with self.assertRaisesRegex(RuntimeError, "reward/counts"):
            appworld_reward.isolated_reward("task", "experiment", runner=runner)


if __name__ == "__main__":
    unittest.main()
