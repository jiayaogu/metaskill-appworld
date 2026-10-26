"""Build a difficulty-aware, outcome-blind quick2h train revision.

Run from the workspace root:
    .venv/bin/python ace-appworld/experiments/code/sample_quick2h_train_v2.py

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
SAMPLE_ROOT = PROJECT_ROOT / "experiments/samples/quick2h_train_v2"
DATASET_PATH = DATA_ROOT / "datasets/quick2h_train_v2.txt"
OLD_DATASET_PATH = DATA_ROOT / "datasets/quick2h_train.txt"
NORMAL_V2_PATH = DATA_ROOT / "datasets/quick2h_test_normal_v2.txt"
CHALLENGE_V2_PATH = DATA_ROOT / "datasets/quick2h_test_challenge_v2.txt"
COMPLEXITY_FIELDS = ("num_apis", "num_api_calls", "num_solution_code_lines")
PRIMARY_FIELDS = (
    "topic",
    "difficulty",
    "app_count",
    "normal_shift_error",
    "challenge_shift_error",
)
SECONDARY_FIELDS = COMPLEXITY_FIELDS


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
    train = families["train"]
    train_features = features["train"]
    index = {family.family_id: i for i, family in enumerate(train)}
    old = family_ids(OLD_DATASET_PATH)
    normal_v2 = family_ids(NORMAL_V2_PATH)
    challenge_v2 = family_ids(CHALLENGE_V2_PATH)
    if len(old) != 5 or len(normal_v2) != 7 or len(challenge_v2) != 6:
        raise ValueError("Expected 5 old train, 7 normal-v2, and 6 challenge-v2 families")
    if not set(old).issubset(index):
        raise ValueError("Original quick2h train sample is not part of full train")

    metadata = {
        family.family_id: [
            json.loads(
                (DATA_ROOT / "tasks" / task / "ground_truth/metadata.json").read_text()
            )
            for task in family.task_ids
        ]
        for family in train
    }
    complexity_cutoffs = {}
    for field in COMPLEXITY_FIELDS:
        values = np.array(
            [[item[field] for item in metadata[family.family_id]] for family in train]
        )
        cuts = np.quantile(values, (0.25, 0.75))
        complexity_cutoffs[field] = cuts.tolist()
        train_features[field] = np.eye(3)[np.digitize(values, cuts)].mean(axis=1)

    full = {name: matrix.mean(axis=0) for name, matrix in train_features.items()}
    normal_index = {
        family.family_id: i for i, family in enumerate(families["test_normal"])
    }
    challenge_index = {
        family.family_id: i for i, family in enumerate(families["test_challenge"])
    }
    sampled_normal = mean_rows(
        features["test_normal"]["topic"],
        [normal_index[family] for family in normal_v2],
    )
    sampled_challenge = mean_rows(
        features["test_challenge"]["topic"],
        [challenge_index[family] for family in challenge_v2],
    )
    full_normal = features["test_normal"]["topic"].mean(axis=0)
    full_challenge = features["test_challenge"]["topic"].mean(axis=0)
    full_normal_shift = tv(full["topic"], full_normal)
    full_challenge_shift = tv(full["topic"], full_challenge)
    old_indices = [index[family] for family in old]
    old_sample = {
        name: mean_rows(matrix, old_indices) for name, matrix in train_features.items()
    }
    old_distances = {name: tv(old_sample[name], full[name]) for name in train_features}
    old_normal_shift = tv(old_sample["topic"], sampled_normal)
    old_challenge_shift = tv(old_sample["topic"], sampled_challenge)
    pool = [family.family_id for family in train if family.family_id not in old]
    best = None
    feasible = 0

    # Normal-v2 plus challenge-v2 already contain 39 tasks, so train must stay
    # at five complete families to keep the full suite at 54 tasks. Preserve
    # the exact full-train D1/D2/D3 proportions available at this size: 2/2/1.
    for dropped in (None, *old):
        retained = [family for family in old if family != dropped]
        for added in itertools.combinations(pool, 5 - len(retained)):
            selected = set((*retained, *added))
            labels = sorted(train[index[family]].difficulty[0] for family in selected)
            if labels != [1, 1, 2, 2, 3]:
                continue
            feasible += 1
            indices = [
                index[family.family_id] for family in train if family.family_id in selected
            ]
            sampled = {
                name: mean_rows(matrix, indices) for name, matrix in train_features.items()
            }
            distances = {name: tv(sampled[name], full[name]) for name in train_features}
            normal_shift = tv(sampled["topic"], sampled_normal)
            challenge_shift = tv(sampled["topic"], sampled_challenge)
            distances["normal_shift_error"] = abs(normal_shift - full_normal_shift)
            distances["challenge_shift_error"] = abs(
                challenge_shift - full_challenge_shift
            )
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
            family_order = tuple(train[i].family_id for i in indices)
            key = (rank, family_order)
            if best is None or key < best[0]:
                best = (
                    key,
                    family_order,
                    sampled,
                    distances,
                    normal_shift,
                    challenge_shift,
                )

    if best is None:
        raise RuntimeError("No feasible sample found")
    (_, family_order, sampled, distances, normal_shift, challenge_shift) = best
    task_ids = [
        f"{family}_{variant}" for family in family_order for variant in (1, 2, 3)
    ]
    if len(task_ids) != 15 or len(set(task_ids)) != 15:
        raise AssertionError("Expected five complete, unique families")
    manifest = "\n".join(task_ids) + "\n"
    SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)
    (SAMPLE_ROOT / "train.txt").write_text(manifest)
    DATASET_PATH.write_text(manifest)

    audit = {
        "design": (
            "outcome-blind quick2h train v2; normal v2 and challenge v2 fixed"
        ),
        "source_split": "train",
        "full_train_families": len(train),
        "old_families": old,
        "selected_families_in_full_split_order": list(family_order),
        "retained": [family for family in old if family in family_order],
        "removed": [family for family in old if family not in family_order],
        "added": [family for family in family_order if family not in old],
        "family_difficulty": {
            family: train[index[family]].difficulty[0] for family in family_order
        },
        "counts": {
            "train_v2": 15,
            "test_normal_v2": 21,
            "test_challenge_v2": 18,
            "total": 54,
        },
        "estimated_minutes_at_2_2_per_task": 54 * 2.2,
        "selection": {
            "candidate_rule": (
                "retain >=4/5 old families; 5 total; D1/D2/D3=2/2/1; "
                "normal v2 and challenge v2 fixed"
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
        "full_train_topic_probability": full["topic"].tolist(),
        "sample_train_topic_probability": sampled["topic"].tolist(),
        "full_train_difficulty_probability": full["difficulty"].tolist(),
        "sample_train_difficulty_probability": sampled["difficulty"].tolist(),
        "full_train_app_count_probability": full["app_count"].tolist(),
        "sample_train_app_count_probability": sampled["app_count"].tolist(),
        "old_within_train_tv": old_distances,
        "within_train_tv": {name: distances[name] for name in train_features},
        "full_train_to_normal_topic_tv": full_normal_shift,
        "old_train_to_normal_v2_topic_tv": old_normal_shift,
        "old_train_to_normal_shift_error": abs(old_normal_shift - full_normal_shift),
        "train_v2_to_normal_v2_topic_tv": normal_shift,
        "train_to_normal_shift_error": distances["normal_shift_error"],
        "full_train_to_challenge_topic_tv": full_challenge_shift,
        "old_train_to_challenge_v2_topic_tv": old_challenge_shift,
        "old_train_to_challenge_shift_error": abs(
            old_challenge_shift - full_challenge_shift
        ),
        "train_v2_to_challenge_v2_topic_tv": challenge_shift,
        "train_to_challenge_shift_error": distances["challenge_shift_error"],
    }
    (SAMPLE_ROOT / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(f"Selected {family_order}")
    print(f"Removed {audit['removed']}; added {audit['added']}")
    print(f"Feasible candidates: {feasible}; rank: {best[0][0]}")
    print(f"TVs: {distances}")
    print(f"Wrote {DATASET_PATH} and {SAMPLE_ROOT}")


if __name__ == "__main__":
    main()
