"""Select reproducible one-third AppWorld scenario samples with low topic TV.

Run from the workspace root with its Python environment:
    .venv/bin/python ace-appworld/experiments/code/sample_intermediate_1of3.py

This uses only task instructions and intrinsic task metadata. It never reads
baseline outcomes or evaluator success. The output directory contains three
task-ID manifests and a JSON distribution audit.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


SPLITS = ("train", "test_normal", "test_challenge")
TOPIC_PATTERNS = OrderedDict(
    [
        ("Amazon", r"\bamazon\b"),
        ("Gmail", r"\bgmail\b"),
        ("Todoist", r"\btodoist\b"),
        ("Splitwise", r"\bsplitwise\b"),
        ("Spotify", r"\bspotify\b"),
        ("Venmo", r"\bvenmo\b"),
        ("Simple Note", r"\bsimple[ _-]?note\b"),
        ("Phone", r"\bphone\b|\b(text|voice) messages?\b"),
        ("File system", r"\bfile system\b|~/"),
    ]
)
TOPICS = tuple(TOPIC_PATTERNS) + ("Other",)
UNSEEN_APPS = frozenset(("Amazon", "Gmail", "Todoist", "Splitwise"))


@dataclass(frozen=True)
class Family:
    family_id: str
    task_ids: tuple[str, str, str]
    instructions: tuple[str, str, str]
    topic_vector: np.ndarray
    difficulty: tuple[int, int, int]
    num_apps: tuple[int, int, int]
    hits: frozenset[str]

    @property
    def document(self) -> str:
        return " ".join(self.instructions)


def load_split(data_root: Path, split: str) -> list[Family]:
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for task_id in (data_root / "datasets" / f"{split}.txt").read_text().splitlines():
        if task_id.strip():
            groups.setdefault(task_id.rsplit("_", 1)[0], []).append(task_id)

    families = []
    for family_id, task_ids in groups.items():
        expected = tuple(f"{family_id}_{variant}" for variant in (1, 2, 3))
        if sorted(task_ids) != list(expected):
            raise ValueError(f"{split}: incomplete or duplicate family {family_id}")
        instructions = []
        difficulties = []
        app_counts = []
        topic_vector = np.zeros(len(TOPICS), dtype=float)
        all_hits: set[str] = set()
        for task_id in expected:
            task_dir = data_root / "tasks" / task_id
            instruction = json.loads((task_dir / "specs.json").read_text())["instruction"]
            metadata = json.loads((task_dir / "ground_truth" / "metadata.json").read_text())
            hits = [
                topic
                for topic, pattern in TOPIC_PATTERNS.items()
                if re.search(pattern, instruction, re.IGNORECASE)
            ] or ["Other"]
            all_hits.update(hits)
            for topic in hits:
                topic_vector[TOPICS.index(topic)] += 1 / (3 * len(hits))
            instructions.append(instruction)
            difficulties.append(int(metadata["difficulty"]))
            app_counts.append(int(metadata["num_apps"]))
        families.append(
            Family(
                family_id,
                expected,
                tuple(instructions),
                topic_vector,
                tuple(difficulties),
                tuple(app_counts),
                frozenset(all_hits),
            )
        )
    return families


def tv(p: np.ndarray, q: np.ndarray) -> float:
    return float(np.abs(p - q).sum() / 2)


def one_hot_variant_values(families: list[Family], field: str, categories: list[int]) -> np.ndarray:
    return np.asarray(
        [[sum(value == category for value in getattr(family, field)) / 3 for category in categories]
         for family in families],
        dtype=float,
    )


def make_features(families: dict[str, list[Family]]) -> tuple[dict, dict]:
    all_families = [family for split in SPLITS for family in families[split]]
    all_documents = [family.document for family in all_families]
    tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    document_vectors = tfidf.fit_transform(all_documents)
    train_count = len(families["train"])
    difficulty_categories = sorted({v for family in all_families for v in family.difficulty})
    app_count_categories = sorted({v for family in all_families for v in family.num_apps})
    features = {}
    novelty_cutoffs = {}
    start = 0
    for split in SPLITS:
        records = families[split]
        count = len(records)
        matrices = {
            "topic": np.stack([family.topic_vector for family in records]),
            "difficulty": one_hot_variant_values(records, "difficulty", difficulty_categories),
            "app_count": one_hot_variant_values(records, "num_apps", app_count_categories),
        }
        if split != "train":
            similarity = cosine_similarity(
                document_vectors[start:start + count], document_vectors[:train_count]
            ).max(axis=1)
            cuts = np.quantile(similarity, (0.25, 0.75))
            bins = np.digitize(similarity, cuts)
            matrices["novelty_bin"] = np.eye(3)[bins]
            novelty_cutoffs[split] = cuts.tolist()
        features[split] = matrices
        start += count
    return features, {
        "difficulty_categories": difficulty_categories,
        "app_count_categories": app_count_categories,
        "novelty_similarity_cutoffs": novelty_cutoffs,
        "tfidf": {"stop_words": "english", "ngram_range": [1, 2], "sublinear_tf": True},
    }


def evaluate(
    selection: dict[str, np.ndarray],
    families: dict[str, list[Family]],
    features: dict,
    full: dict,
    source_shifts: dict,
) -> tuple[tuple[float, float, float, float], dict] | None:
    normal_hits = set().union(*(families["test_normal"][i].hits for i in selection["test_normal"]))
    challenge_hits = set().union(*(families["test_challenge"][i].hits for i in selection["test_challenge"]))
    if not ({"Todoist", "Splitwise"} & normal_hits):
        return None
    if not {"Amazon", "Gmail"}.issubset(challenge_hits):
        return None

    sample = {
        split: {name: matrix[selection[split]].mean(axis=0) for name, matrix in features[split].items()}
        for split in SPLITS
    }
    within = {
        split: {name: tv(vector, full[split][name]) for name, vector in sample[split].items()}
        for split in SPLITS
    }
    shifts = {
        test: tv(sample["train"]["topic"], sample[test]["topic"])
        for test in SPLITS[1:]
    }
    if shifts["test_challenge"] <= shifts["test_normal"]:
        return None
    errors = {test: abs(shifts[test] - source_shifts[test]) for test in SPLITS[1:]}
    primary = [within[split]["topic"] for split in SPLITS] + list(errors.values())
    auxiliary = [within[split]["difficulty"] for split in SPLITS]
    auxiliary += [within[split]["app_count"] for split in SPLITS]
    auxiliary += [within[test]["novelty_bin"] for test in SPLITS[1:]]
    # Ignore floating-point noise when discrete subsets have equal metrics.
    rank = tuple(round(float(value), 12) for value in
                 (max(primary), sum(primary), max(auxiliary), sum(auxiliary)))
    return rank, {"within_split_tv": within, "sample_shifts": shifts, "shift_errors": errors, "sample": sample}


def sample(
    families: dict[str, list[Family]],
    features: dict,
    counts: dict[str, int],
    seed: int,
    proposals: int,
) -> tuple[dict[str, np.ndarray], tuple, dict]:
    full = {split: {name: matrix.mean(axis=0) for name, matrix in features[split].items()} for split in SPLITS}
    source_shifts = {
        test: tv(full["train"]["topic"], full[test]["topic"])
        for test in SPLITS[1:]
    }
    rng = np.random.default_rng(seed)
    best_selection = None
    best_result = None
    best_rank = (math.inf,) * 4
    current = None
    current_rank = None
    current_result = None
    for step in range(proposals):
        if current is None or step % 5000 == 0:
            # Restarts and occasional jumps avoid relying on one local basin.
            current = {
                split: np.sort(rng.choice(len(families[split]), counts[split], replace=False))
                for split in SPLITS
            }
            assessed = evaluate(current, families, features, full, source_shifts)
            if assessed is None:
                current = None
                continue
            current_rank, current_result = assessed
        split = SPLITS[int(rng.integers(0, 3))]
        outgoing = int(rng.choice(current[split]))
        incoming = int(rng.integers(0, len(families[split])))
        if incoming in current[split]:
            continue
        trial = {name: indices.copy() for name, indices in current.items()}
        trial[split][trial[split] == outgoing] = incoming
        assessed = evaluate(trial, families, features, full, source_shifts)
        if assessed is None:
            continue
        rank, result = assessed
        if rank < best_rank:
            best_rank, best_result = rank, result
            best_selection = {name: np.sort(indices.copy()) for name, indices in trial.items()}
        # The scalar acceptance rule explores nearby alternatives; final
        # selection always uses the documented lexicographic rank.
        current_energy = current_rank[0] + 0.05 * current_rank[1] + 0.01 * current_rank[2]
        trial_energy = rank[0] + 0.05 * rank[1] + 0.01 * rank[2]
        temperature = 0.01 * (1 - (step % 5000) / 5000) + 0.0001
        if trial_energy <= current_energy or rng.random() < math.exp((current_energy - trial_energy) / temperature):
            current, current_rank, current_result = trial, rank, result
    if best_selection is None:
        raise RuntimeError("No feasible sample found; inspect hard coverage constraints.")

    # Search every one-for-one replacement around the best stochastic result.
    # Equal topic/shift ranks can then improve on metadata and novelty TV.
    for _ in range(12):
        neighbor = None
        neighbor_result = None
        neighbor_rank = best_rank
        for split in SPLITS:
            selected = set(int(i) for i in best_selection[split])
            for outgoing in selected:
                for incoming in range(len(families[split])):
                    if incoming in selected:
                        continue
                    trial = {name: indices.copy() for name, indices in best_selection.items()}
                    trial[split][trial[split] == outgoing] = incoming
                    assessed = evaluate(trial, families, features, full, source_shifts)
                    if assessed is not None and assessed[0] < neighbor_rank:
                        neighbor_rank, neighbor_result = assessed
                        neighbor = {name: np.sort(indices.copy()) for name, indices in trial.items()}
        if neighbor is None:
            break
        best_selection, best_rank, best_result = neighbor, neighbor_rank, neighbor_result
    return best_selection, best_rank, {
        **best_result,
        "full": full,
        "source_shifts": source_shifts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    project_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--data-root", type=Path, default=project_root / "data")
    parser.add_argument("--output-dir", type=Path, default=project_root / "experiments" / "samples" / "intermediate_1of3")
    parser.add_argument("--seed", type=int, default=20261015)
    parser.add_argument("--proposals", type=int, default=600000)
    args = parser.parse_args()

    families = {split: load_split(args.data_root, split) for split in SPLITS}
    ids = [family.family_id for split in SPLITS for family in families[split]]
    if len(ids) != len(set(ids)):
        raise ValueError("A family occurs in more than one source split.")
    counts = {split: round(len(families[split]) / 3) for split in SPLITS}
    features, settings = make_features(families)
    chosen, rank, audit = sample(families, features, counts, args.seed, args.proposals)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected_ids = {}
    for split in SPLITS:
        selected = [families[split][i] for i in chosen[split]]
        selected_ids[split] = [family.family_id for family in selected]
        task_ids = [task_id for family in selected for task_id in family.task_ids]
        assert len(task_ids) == 3 * counts[split]
        (args.output_dir / f"{split}.txt").write_text("\n".join(task_ids) + "\n")

    prevalence = {}
    for split in SPLITS:
        selected = [families[split][i] for i in chosen[split]]
        prevalence[split] = {
            "full_unseen_app_families": sum(bool(family.hits & UNSEEN_APPS) for family in families[split]),
            "sample_unseen_app_families": sum(bool(family.hits & UNSEEN_APPS) for family in selected),
            "full_by_app": {app: sum(app in family.hits for family in families[split]) for app in sorted(UNSEEN_APPS)},
            "sample_by_app": {app: sum(app in family.hits for family in selected) for app in sorted(UNSEEN_APPS)},
        }
    report = {
        "source_scenario_counts": {split: len(families[split]) for split in SPLITS},
        "sample_scenario_counts": counts,
        "selected_family_ids": selected_ids,
        "seed": args.seed,
        "proposals": args.proposals,
        "ranking": [float(x) for x in rank],
        "settings": settings,
        "full_topic_probability": {split: dict(zip(TOPICS, audit["full"][split]["topic"].tolist())) for split in SPLITS},
        "sample_topic_probability": {split: dict(zip(TOPICS, audit["sample"][split]["topic"].tolist())) for split in SPLITS},
        "within_split_tv": audit["within_split_tv"],
        "source_train_to_test_topic_tv": audit["source_shifts"],
        "sample_train_to_test_topic_tv": audit["sample_shifts"],
        "absolute_train_to_test_tv_error": audit["shift_errors"],
        "test_only_app_prevalence": prevalence,
    }
    (args.output_dir / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in (
        "sample_scenario_counts", "within_split_tv", "source_train_to_test_topic_tv",
        "sample_train_to_test_topic_tv", "absolute_train_to_test_tv_error", "ranking"
    )}, indent=2))


if __name__ == "__main__":
    main()
