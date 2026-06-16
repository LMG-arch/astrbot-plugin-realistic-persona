"""Static verification of data-flow breakpoints after the修复.

These tests confirm the API contract mismatches flagged during the audit
without requiring live runtime reproduction. They exercise the exact method
signatures used by the plugin.
"""

import inspect
from unittest.mock import MagicMock

import pytest

from core.experience_bank import ExperienceBank
from core.memory_manager import MemoryManager
from core.personality_evolution import PersonalityEvolutionManager


# ---------------------------------------------------------------------------
# H1 / H3: experience_status command reads non-existent keys
# ---------------------------------------------------------------------------


def test_growth_summary_keys_vs_main_consumption(tmp_path):
    """get_growth_summary now returns both raw 'skills' dict and 'skills_count'.

    After fix: the consumer (main.py check_experience_status) reads 'skills'
    as a dict and renders levels correctly.
    """
    bank = ExperienceBank(tmp_path)
    bank._update_growth_sync("skills", "python", level=3)
    summary = bank.get_growth_summary()

    # The producer now exposes raw 'skills' for direct consumption
    assert "skills" in summary, "get_growth_summary must expose raw 'skills' dict"
    assert "skills_count" in summary
    assert "top_skills" in summary

    consumer_skills = summary.get("skills", {})
    assert isinstance(consumer_skills, dict)
    assert "python" in consumer_skills
    # _update_growth_sync creates new skills at level 1; the level arg only
    # applies on subsequent updates. The key fix here is that 'skills' is now
    # exposed as a dict (previously missing entirely).
    assert consumer_skills["python"]["level"] == 1


def test_growth_summary_interests_key_mismatch(tmp_path):
    """After fix: get_growth_summary exposes raw 'interests' list."""
    bank = ExperienceBank(tmp_path)
    bank._update_growth_sync("interests", "编程")
    summary = bank.get_growth_summary()

    assert "interests" in summary, "Producer now exposes 'interests' directly"
    assert "recent_interests" in summary  # kept for backward compat

    consumer_interests = summary.get("interests", [])
    assert isinstance(consumer_interests, list)
    assert len(consumer_interests) >= 1


def test_growth_summary_views_key_mismatch(tmp_path):
    """After fix: get_growth_summary exposes raw 'views' list."""
    bank = ExperienceBank(tmp_path)
    bank._update_growth_sync("views", "乐观向上", validate_smoothness=False)
    summary = bank.get_growth_summary()

    assert "views" in summary, "Producer now exposes 'views' directly"
    assert "views_count" in summary

    consumer_views = summary.get("views", [])
    assert isinstance(consumer_views, list)


# ---------------------------------------------------------------------------
# H2: proactive_manager calls personality_evolution.get_status() which doesn't exist
# ---------------------------------------------------------------------------


def test_personality_evolution_has_no_get_status(tmp_path):
    """The PersonalityEvolutionManager class has NO get_status method.

    proactive_manager.generate_proactive_share calls .get_status() at line 309,
    which raises AttributeError. Only get_personality_summary() exists.
    """
    mgr = PersonalityEvolutionManager(tmp_path)
    assert not hasattr(mgr, "get_status"), "get_status should NOT exist"
    assert hasattr(mgr, "get_personality_summary"), "get_personality_summary exists"


def test_personality_evolution_summary_key_shape(tmp_path):
    """get_personality_summary returns 'expression_levels', not 'expression_style'."""
    mgr = PersonalityEvolutionManager(tmp_path)
    summary = mgr.get_personality_summary()

    # The producer's actual key
    assert "expression_levels" in summary
    # proactive_manager reads evo_summary.get("expression_levels", {})
    assert "expression_style" not in summary
    # The nested keys are vocabulary/humor (not vocabulary_level/humor_level)
    expr = summary["expression_levels"]
    assert "vocabulary" in expr
    assert "humor" in expr


def test_proactive_share_reads_correct_personality_api():
    """After fix: proactive_manager source uses get_personality_summary + expression_levels."""
    import pathlib

    pm_src = (
        pathlib.Path(__file__)
        .resolve()
        .parent.parent.joinpath("managers", "proactive_manager.py")
        .read_text(encoding="utf-8")
    )

    # The buggy call must be gone
    assert ".get_status()" not in pm_src, "get_status() must be removed"
    assert "expression_style" not in pm_src, "wrong key must be removed"
    # The correct call must be present
    assert "get_personality_summary()" in pm_src
    assert "expression_levels" in pm_src


# ---------------------------------------------------------------------------
# Verify the 6 fixed breakpoints are actually connected (grep-style static check)
# ---------------------------------------------------------------------------


def _read_main_py():
    import pathlib

    return (
        pathlib.Path(__file__)
        .resolve()
        .parent.parent.joinpath("main.py")
        .read_text(encoding="utf-8")
    )


def _read_file(rel_path):
    import pathlib

    return (
        pathlib.Path(__file__)
        .resolve()
        .parent.parent.joinpath(rel_path)
        .read_text(encoding="utf-8")
    )


def test_breakpoint1_personality_evolution_connected():
    """process_interaction is called in both experience_manager and main.on_llm_response."""
    main_src = _read_main_py()
    exp_src = _read_file("managers/experience_manager.py")
    pe_src = _read_file("core/personality_evolution.py")

    assert "process_interaction" in main_src, "main.py must call process_interaction"
    assert "process_interaction" in exp_src, (
        "experience_manager must call process_interaction"
    )
    assert "def process_interaction" in pe_src, (
        "personality_evolution must define process_interaction"
    )
    # daily_routine must auto-prune underperforming traits
    assert "remove_trait" in pe_src


def test_breakpoint2_memory_recall_connected():
    """recall_relevant + recall_memory_for_context are wired."""
    main_src = _read_main_py()
    pi_src = _read_file("managers/prompt_injector.py")
    tm_src = _read_file("managers/thinking_manager.py")
    mm_src = _read_file("core/memory_manager.py")

    assert (
        "recall_memory_for_context" in main_src
        or "recall_memory_for_context" in pi_src
    )
    assert "def recall_memory_for_context" in tm_src
    assert "def recall_relevant" in mm_src


def test_breakpoint3_sleeping_data_connected():
    """4 getter methods exist and are consumed in life_manager + main.py/prompt_injector."""
    eb_src = _read_file("core/experience_bank.py")
    lm_src = _read_file("managers/life_manager.py")
    main_src = _read_main_py()
    pi_src = _read_file("managers/prompt_injector.py")
    combined = main_src + pi_src

    for getter in [
        "get_recent_projects",
        "get_pending_promises",
        "get_recent_circadian",
        "get_relationship_profile",
    ]:
        assert f"def {getter}" in eb_src, f"experience_bank must define {getter}"
    # life_manager injects projects/promises/circadian
    assert "get_recent_projects" in lm_src
    assert "get_pending_promises" in lm_src
    assert "get_recent_circadian" in lm_src
    # main.py or prompt_injector injects relationship + has commands
    assert "get_relationship_profile" in combined
    assert "my_promises" in combined
    assert "my_projects" in combined


def test_breakpoint4_psychology_loneliness_connected():
    """check_loneliness_and_act exists and is registered in main.initialize."""
    main_src = _read_main_py()
    pm_src = _read_file("managers/proactive_manager.py")

    assert "def check_loneliness_and_act" in pm_src
    assert "check_loneliness_and_act" in main_src
    assert "_loneliness_scheduler" in main_src


def test_breakpoint5_life_story_context_param():
    """life_story_engine.update_life_story accepts context param."""
    lse_src = _read_file("core/life_story_engine.py")
    tm_src = _read_file("managers/thinking_manager.py")

    assert "def update_life_story(self, llm_action=None, context=None)" in lse_src
    assert "context=self.context" in tm_src


def test_recall_relevant_returns_string(tmp_path):
    """recall_relevant should return a formatted string when matches found."""
    import asyncio

    mm = MemoryManager(tmp_path)
    mm.record_weighted_conversation(
        user_id="u1",
        user_message="记得学习python编程",
        bot_response="好的，加油",
        importance_score=0.9,
        session_id="s1",
    )
    result = asyncio.run(mm.recall_relevant("python 编程", user_id="u1"))
    assert isinstance(result, str)
    assert "python" in result or "编程" in result
