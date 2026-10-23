"""Baseline bridges; each calls its original core task method."""

from __future__ import annotations

from pathlib import Path

from appworld_experiments.code.common.config import RunSpec


def make_adapter(spec: RunSpec):
    baselines_root = spec.appworld_root.parent.parent
    if spec.baseline == "ace":
        from .ace_adapter import ACEAdapter

        return ACEAdapter(spec.baseline_config, appworld_kwargs=spec.appworld_kwargs)
    if spec.baseline == "reasoningbank":
        from .reasoningbank_adapter import ReasoningBankAdapter

        source = baselines_root / "reasoning-bank" / "AppWorld" / "reasoningbank_appworld.py"
        if not source.is_file():
            raise FileNotFoundError(f"ReasoningBank core is absent: {source}")
        return ReasoningBankAdapter(
            spec.baseline_config,
            source=source,
            price_file=spec.pricing_registry_path,
            random_seed=int(spec.appworld_kwargs.get("random_seed", 123)),
        )
    if spec.baseline == "polyskill":
        from .polyskill_adapter import PolySkillAdapter

        source_root = baselines_root / "PolySkill"
        if not (source_root / "polyskill" / "appworld" / "runner.py").is_file():
            raise FileNotFoundError(f"PolySkill core is absent: {source_root}")
        return PolySkillAdapter(
            spec.baseline_config,
            source_root=source_root,
            pricing_registry_path=spec.pricing_registry_path,
        )
    if spec.baseline == "reme":
        from .reme_adapter import ReMeAdapter

        return ReMeAdapter(spec)
    raise ValueError(f"Unknown baseline: {spec.baseline}")
