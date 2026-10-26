"""Build a difficulty-aware, outcome-blind quick2h challenge-test revision.

Run from the workspace root:
    .venv/bin/python ace-appworld/experiments/code/sample_quick2h_challenge_v2.py

The search reads task instructions and intrinsic ground-truth metadata. It
never reads experiment outputs, evaluator reports, or baseline successes.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

from sample_intermediate_1of3 import TOPICS, load_split, make_features, tv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
SAMPLE_ROOT = PROJECT_ROOT / "experiments/samples/quick2h_challenge_v2"
DATASET_PATH = DATA_ROOT / "datasets/quick2h_test_challenge_v2.txt"
OLD_DATASET_PATH = DATA_ROOT / "datasets/quick2h_test_challenge.txt"
TRAIN_SAMPLE_PATH = DATA_ROOT / "datasets/quick2h_train.txt"
NORMAL_V2_PATH = DATA_ROOT / "datasets/quick2h_test_normal_v2.txt"
COMPLEXITY_FIELDS = ("num_apis", "num_api_calls", "num_solution_code_lines")
PRIMARY_FIELDS = ("topic", "difficulty", "app_count", "shift_error")
SECONDARY_FIELDS = ("novelty_bin", *COMPLEXITY_FIELDS)


def family_ids(path: Path) -> list[str]:
    tasks = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    groups = list(dict.fromkeys(task.rsplit("_", 1)[0] for task in tasks))
    if tasks != [f"{family}_{variant}" for family in groups for variant in (1, 2, 3)]:
        raise ValueError(f"Expected consecutive complete scenario families in {path}")
    return groups


def mean_rows(matrix: np.ndarray, indices: list[int]) -> np.ndarray:
    return matrix[indices].mean(axis=0)


def main() -> None:
    families = {
        split: load_split(DATA_ROOT, split)
        for split in ("train", "test_normal", "test_challenge")
    }
    features, settings = make_features(families)
    challenge = families["test_challenge"]
    challenge_features = features["test_challenge"]
    index = {family.family_id: i for i, family in enumerate(challenge)}
    old = family_ids(OLD_DATASET_PATH)
    train_sample = family_ids(TRAIN_SAMPLE_PATH)
    normal_v2 = family_ids(NORMAL_V2_PATH)
    if len(old) != 5 or len(train_sample) != 5 or len(normal_v2) != 7:
        raise ValueError("Expected 5 old challenge, 5 train, and 7 normal-v2 families")
    if not set(old).issubset(index):
        raise ValueError("Original quick2h challenge sample is not part of full test_challenge")

    metadata = {
        family.family_id: [
            json.loads(
                (DATA_ROOT / "tasks" / task / "ground_truth/metadata.json").read_text()
            )
            for task in family.task_ids
        ]
        for family in challenge
    }
    complexity_cutoffs = {}
    for field in COMPLEXITY_FIELDS:
        values = np.array(
            [[item[field] for item in metadata[family.family_id]] for family in challenge]
        )
        cuts = np.quantile(values, (0.25, 0.75))
        complexity_cutoffs[field] = cuts.tolist()
        challenge_features[field] = np.eye(3)[np.digitize(values, cuts)].mean(axis=1)

    full = {name: matrix.mean(axis=0) for name, matrix in challenge_features.items()}
    full_train = features["train"]["topic"].mean(axis=0)
    train_index = {family.family_id: i for i, family in enumerate(families["train"])}
    sampled_train = mean_rows(
        features["train"]["topic"], [train_index[family] for family in train_sample]
    )
    full_shift = tv(full_train, full["topic"])
    old_indices = [index[family] for family in old]
    old_sample = {
        name: mean_rows(matrix, old_indices) for name, matrix in challenge_features.items()
    }
    old_distances = {name: tv(old_sample[name], full[name]) for name in challenge_features}
    old_shift = tv(sampled_train, old_sample["topic"])
    pool = [family.family_id for family in challenge if family.family_id not in old]
    best = None
    feasible = 0

    # With train=5 families and normal-v2=7, six challenge families are the
    # largest complete-family sample within the nominal two-hour/54-task
    # budget. Their nearest feasible D1/D2/D3 counts are 1/2/3.
    for dropped in (None, *old):
        retained = [family for family in old if family != dropped]
        for added in itertools.combinations(pool, 6 - len(retained)):
            selected = set((*retained, *added))
            labels = sorted(challenge[index[family]].difficulty[0] for family in selected)
            if labels != [1, 2, 2, 3, 3, 3]:
                continue
            hits = set().union(*(challenge[index[family]].hits for family in selected))
            if not {"Amazon", "Gmail"}.issubset(hits):
                continue
            feasible += 1
            indices = [
                index[family.family_id]
                for family in challenge
                if family.family_id in selected
            ]
            sampled = {
                name: mean_rows(matrix, indices)
                for name, matrix in challenge_features.items()
            }
            distances = {
                name: tv(sampled[name], full[name]) for name in challenge_features
            }
            sampled_shift = tv(sampled_train, sampled["topic"])
            distances["shift_error"] = abs(sampled_shift - full_shift)
            primary = [distances[field] for field in PRIMARY_FIELDS]
            secondary = [distances[field] for field in SECONDARY_FIELDS]
            rank = tuple(
                round(value, 10)
                for value in (
                    max(primary),
                    sum(primary),
                    max(secondary),
                    sum(secondary),
                )
            )
            family_order = tuple(challenge[i].family_id for i in indices)
            key = (rank, family_order)
            if best is None or key < best[0]:
                best = (key, family_order, sampled, distances, sampled_shift)

    if best is None:
        raise RuntimeError("No feasible sample found")
    (_, family_order, sampled, distances, sampled_shift) = best
    task_ids = [
        f"{family}_{variant}" for family in family_order for variant in (1, 2, 3)
    ]
    if len(task_ids) != 18 or len(set(task_ids)) != 18:
        raise AssertionError("Expected six complete, unique families")
    manifest = "\n".join(task_ids) + "\n"
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    (SAMPLE_ROOT / "test_challenge.txt").write_text(manifest)
    DATASET_PATH.write_text(manifest)

    audit = {
        "design": (
            "outcome-blind quick2h challenge v2; quick2h train and normal v2 unchanged"
        ),
        "source_split": "test_challenge",
        "full_challenge_families": len(challenge),
        "old_families": old,
        "selected_families_in_full_split_order": list(family_order),
        "retained": [family for family in old if family in family_order],
        "removed": [family for family in old if family not in family_order],
        "added": [family for family in family_order if family not in old],
        "family_difficulty": {
            family: challenge[index[family]].difficulty[0] for family in family_order
        },
        "counts": {
            "train": 15,
            "test_normal_v2": 21,
            "test_challenge_v2": 18,
            "total": 54,
        },
        "estimated_minutes_at_2_2_per_task": 54 * 2.2,
        "selection": {
            "candidate_rule": (
                "retain >=4/5 old families; 6 total; D1/D2/D3=1/2/3; "
                "include Amazon and Gmail"
            ),
            "feasible_candidates": feasible,
            "rank": [
                "max primary TV",
                "sum primary TV",
                "max secondary TV",
                "sum secondary TV",
                "source-order family IDs",
            ],
            "primary": list(PRIMARY_FIELDS),
            "secondary": list(SECONDARY_FIELDS),
            "outcome_files_read": False,
        },
        "representation": {
            **settings,
            "complexity_quartile_cutoffs": complexity_cutoffs,
        },
        "topics": list(TOPICS),
        "full_challenge_topic_probability": full["topic"].tolist(),
        "sample_challenge_topic_probability": sampled["topic"].tolist(),
        "full_challenge_difficulty_probability": full["difficulty"].tolist(),
        "sample_challenge_difficulty_probability": sampled["difficulty"].tolist(),
        "full_challenge_app_count_probability": full["app_count"].tolist(),
        "sample_challenge_app_count_probability": sampled["app_count"].tolist(),
        "old_within_challenge_tv": old_distances,
        "within_challenge_tv": {
            name: distances[name] for name in challenge_features
        },
        "full_train_to_challenge_topic_tv": full_shift,
        "old_quick2h_train_to_challenge_topic_tv": old_shift,
        "old_train_to_challenge_shift_error": abs(old_shift - full_shift),
        "quick2h_train_to_v2_challenge_topic_tv": sampled_shift,
        "train_to_challenge_shift_error": distances["shift_error"],
    }
    (SAMPLE_ROOT / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(f"Selected {family_order}")
    print(f"Removed {audit['removed']}; added {audit['added']}")
    print(f"Feasible candidates: {feasible}; rank: {best[0][0]}")
    print(f"TVs: {distances}")
    print(f"Wrote {DATASET_PATH} and {SAMPLE_ROOT}")


if __name__ == "__main__":
    main()
