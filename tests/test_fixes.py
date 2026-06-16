"""
针对性修复验证测试：覆盖本次修复的关键改动点
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import zoneinfo
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGIN_NAME = PLUGIN_DIR.name


def _import(mod_name):
    from importlib import import_module

    return import_module(f"{PLUGIN_NAME}.{mod_name}")


# ============================================================
# 1. Memory decay preserves JSONL format (阶段 1.1)
# ============================================================
class TestMemoryDecayPreservesJSONL:
    """Verify that decay rewrites preserve JSONL (one-JSON-per-line) format."""

    def test_decay_rewrite_is_jsonl(self):
        mod = _import("core.memory_manager")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            conv_file = tmpdir / "weighted_conversations.jsonl"

            # Write an initial JSONL file with entries spanning different ages.
            # _apply_memory_decay_sync uses days_threshold (default 30):
            #   - Low importance + old → decayed/removed
            #   - So we create one old+low entry and one recent entry.
            old_ts = "2020-01-01T00:00:00"  # way past 30 days
            recent_ts = datetime.now().isoformat()

            lines = [
                {
                    "user_id": "u1",
                    "message": "old stuff",
                    "importance_score": 0.1,
                    "user_message": "old msg",
                    "timestamp": old_ts,
                    "weight": 1.0,
                },
                {
                    "user_id": "u2",
                    "message": "recent",
                    "importance_score": 0.8,
                    "user_message": "recent msg",
                    "timestamp": recent_ts,
                    "weight": 1.0,
                },
            ]
            with open(conv_file, "w", encoding="utf-8") as f:
                for item in lines:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

            mm = mod.MemoryManager(tmpdir)
            # days_threshold=0 so the old entry exceeds the threshold
            result = mm._apply_memory_decay_sync(days_threshold=0)

            # Read back — file must still be valid JSONL
            with open(conv_file, encoding="utf-8") as f:
                kept = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    kept.append(json.loads(line))

            # The file must be valid JSONL (each line is a dict)
            assert all(isinstance(item, dict) for item in kept)

            # Must NOT be a single JSON array (the old bug)
            raw = conv_file.read_text(encoding="utf-8")
            assert not raw.strip().startswith("["), "File should be JSONL, not a JSON array"


# ============================================================
# 2. rotate_jsonl_if_needed utility (阶段 2.1)
# ============================================================
class TestRotateJSONL:
    """Verify the generic JSONL rotation utility."""

    def test_rotation_truncates_file(self):
        mod = _import("core.utils")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "test.jsonl"

            # Write 20 lines
            for i in range(20):
                with open(test_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"i": i}) + "\n")

            mod.rotate_jsonl_if_needed(test_file, max_lines=10, force=True)

            lines = test_file.read_text(encoding="utf-8").strip().split("\n")
            # max_lines=10 → keep max_lines//2 = 5 latest entries
            assert len(lines) == 5
            # Should keep the LATEST 5 entries (i=15..19)
            first = json.loads(lines[0])
            assert first["i"] == 15

    def test_no_rotation_when_under_limit(self):
        mod = _import("core.utils")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            test_file = tmpdir / "test.jsonl"

            with open(test_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"i": 1}) + "\n")

            mod.rotate_jsonl_if_needed(test_file, max_lines=10, force=False)

            lines = test_file.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1


# ============================================================
# 3. Emotion keyword precision (阶段 3.1)
# ============================================================
class TestEmotionKeywordPrecision:
    """Verify that refined keywords don't produce false matches."""

    def test_cow_milk_no_false_excited(self):
        """'牛奶' should NOT trigger EXCITED (previously '牛' substring match)."""
        mod = _import("emotions")
        result = mod.EmotionAnalyzer.analyze_emotion("今天喝了牛奶")
        assert result != mod.EmotionType.EXCITED

    def test_beef_no_false_excited(self):
        """'牛肉' should NOT trigger EXCITED."""
        mod = _import("emotions")
        result = mod.EmotionAnalyzer.analyze_emotion("中午吃牛肉面")
        assert result != mod.EmotionType.EXCITED

    def test_niubi_triggers_excited(self):
        """'牛逼' SHOULD still trigger EXCITED."""
        mod = _import("emotions")
        result = mod.EmotionAnalyzer.analyze_emotion("你好牛逼啊")
        assert result == mod.EmotionType.EXCITED

    def test_stick_no_false_happy(self):
        """'木棒' should NOT trigger HAPPY (previously '棒' substring match)."""
        mod = _import("emotions")
        result = mod.EmotionAnalyzer.analyze_emotion("我拿着一根木棒")
        assert result != mod.EmotionType.HAPPY

    def test_zhenbang_triggers_happy(self):
        """'真棒' SHOULD still trigger HAPPY."""
        mod = _import("emotions")
        result = mod.EmotionAnalyzer.analyze_emotion("你真棒！")
        assert result == mod.EmotionType.HAPPY


# ============================================================
# 4. AsyncThinkingScheduler timezone parameterization (阶段 1.2)
# ============================================================
class TestSchedulerTimezone:
    """Verify that the scheduler accepts and applies a timezone parameter."""

    def test_timezone_parameter_accepted(self):
        mod = _import("core.async_thinking_scheduler")
        te = MagicMock()
        eb = MagicMock()
        sched = mod.AsyncThinkingScheduler(
            thought_engine=te,
            experience_bank=eb,
            timezone="America/New_York",
        )
        # ZoneInfo uses .key (not .zone) to expose the timezone name
        assert sched.scheduler.timezone.key == "America/New_York"

    def test_default_timezone_is_shanghai(self):
        mod = _import("core.async_thinking_scheduler")
        te = MagicMock()
        eb = MagicMock()
        sched = mod.AsyncThinkingScheduler(
            thought_engine=te,
            experience_bank=eb,
        )
        assert sched.scheduler.timezone.key == "Asia/Shanghai"


# ============================================================
# 5. ImageManager draw-success check (阶段 3.2)
# ============================================================
class TestDrawSuccessCheck:
    """Verify the DRAW_FAIL_PREFIX based success check."""

    def test_success_string_passes(self):
        mod = _import("managers.image_manager")
        assert mod.ImageManager.is_draw_success("图片已发送给用户") is True

    def test_fail_prefix_fails(self):
        mod = _import("managers.image_manager")
        prefix = mod.ImageManager.DRAW_FAIL_PREFIX
        assert mod.ImageManager.is_draw_success(f"{prefix}生成失败") is False

    def test_none_fails(self):
        mod = _import("managers.image_manager")
        assert mod.ImageManager.is_draw_success(None) is False

    def test_empty_string_fails(self):
        mod = _import("managers.image_manager")
        assert mod.ImageManager.is_draw_success("") is False


# ============================================================
# 6. PsychologyEngine exact match priority (阶段 3.3)
# ============================================================
class TestPsychologyExactMatch:
    """Verify exact-match-first logic in update_emotion_phase."""

    def test_exact_match_preferred_over_substring(self):
        mod = _import("core.psychology_engine")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            engine = mod.PsychologyEngine(tmpdir)

            # Write lifecycle entries: one "happy" and one "unhappy"
            lifecycle_file = tmpdir / "emotion_lifecycle.jsonl"
            entries = [
                {"event": "unhappy", "phase": "feeling", "timestamp": datetime.now().isoformat()},
                {"event": "happy", "phase": "feeling", "timestamp": datetime.now().isoformat()},
            ]
            with open(lifecycle_file, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

            # Update "happy" — should match the exact "happy" entry, NOT "unhappy"
            engine.update_emotion_phase("happy", "digestion")

            # Read back
            with open(lifecycle_file, encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]

            happy_rec = [r for r in records if r.get("event") == "happy"][0]
            unhappy_rec = [r for r in records if r.get("event") == "unhappy"][0]

            assert happy_rec["phase"] == "digestion"
            assert unhappy_rec["phase"] == "feeling"  # Should NOT be changed


# ============================================================
# 7. PersonalityEvolution dirty flag (阶段 4.4)
# ============================================================
class TestPersonalityEvolutionDirtyFlush:
    """Verify record_behavior defers save, and flush persists."""

    def test_record_behavior_marks_dirty(self):
        mod = _import("core.personality_evolution")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            mgr = mod.PersonalityEvolutionManager(tmpdir)
            sa = mgr.self_awareness

            initial_total = sa.behavior_stats["total_interactions"]
            sa.record_behavior("conversation", "好奇的东西")
            assert sa._dirty is True
            assert sa.behavior_stats["total_interactions"] == initial_total + 1

    def test_flush_persists_to_disk(self):
        mod = _import("core.personality_evolution")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            mgr = mod.PersonalityEvolutionManager(tmpdir)
            sa = mgr.self_awareness

            sa.record_behavior("conversation", "友善地回答问题")
            sa.flush_dirty()
            assert sa._dirty is False

            # Reload from disk — SelfAwarenessSystem's data_dir is
            # PersonalityEvolutionManager.data_dir / "self_awareness"
            sa_data_dir = tmpdir / "self_awareness"
            sa2 = mod.SelfAwarenessSystem(sa_data_dir)
            assert sa2.behavior_stats["total_interactions"] == sa.behavior_stats["total_interactions"]


# ============================================================
# 8. ExperienceBank threading lock (阶段 2.6)
# ============================================================
class TestExperienceBankWriteLock:
    """Verify the write lock is present and functional."""

    def test_write_lock_attribute_exists(self):
        mod = _import("core.experience_bank")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            bank = mod.ExperienceBank(tmpdir)
            assert hasattr(bank, "_write_lock")
            assert isinstance(bank._write_lock, type(threading.Lock()))


# ============================================================
# 9. SystemPromptInjector structure (阶段 4.1)
# ============================================================
class TestSystemPromptInjector:
    """Verify the injector class structure via lightweight inspection.

    The module imports astrbot.api.provider.ProviderRequest which is
    unavailable in the plugin's test environment.  We therefore patch
    the import to avoid the ImportError and inspect the class dict
    for expected method names.
    """

    @pytest.fixture(autouse=True)
    def _patch_astrbot_imports(self):
        """Stub out astrbot.api dependencies that can't resolve in test."""
        fake_provider_mod = type(sys)("astrbot.api.provider")
        fake_provider_mod.ProviderRequest = type("ProviderRequest", (), {})

        fake_event_mod = type(sys)("astrbot.api.event")
        fake_event_mod.AstrMessageEvent = type("AstrMessageEvent", (), {})

        already = {
            "astrbot.api.provider": fake_provider_mod,
            "astrbot.api.event": fake_event_mod,
        }
        originals = {}
        for mod_path, fake in already.items():
            if mod_path in sys.modules:
                originals[mod_path] = sys.modules[mod_path]
            sys.modules[mod_path] = fake

        yield

        for mod_path in already:
            if mod_path in originals:
                sys.modules[mod_path] = originals[mod_path]
            else:
                sys.modules.pop(mod_path, None)

    def test_injector_has_all_segments(self):
        mod = _import("managers.prompt_injector")
        expected_methods = [
            "inject_time_info",
            "inject_message_timestamps",
            "inject_life_story_context",
            "inject_memory_recall",
            "inject_emotion_context",
            "inject_life_simulation",
            "inject_personality_hint",
            "inject_experience",
            "inject_all",
        ]
        for name in expected_methods:
            assert hasattr(mod.SystemPromptInjector, name), f"Missing method: {name}"

    def test_append_prompt_helper(self):
        mod = _import("managers.prompt_injector")
        req = MagicMock()
        req.system_prompt = "existing"
        mod.SystemPromptInjector._append_prompt(req, "\n[new]")
        assert req.system_prompt == "existing\n[new]"

    def test_prepend_prompt_helper(self):
        mod = _import("managers.prompt_injector")
        req = MagicMock()
        req.system_prompt = "existing"
        mod.SystemPromptInjector._prepend_prompt(req, "[time]")
        assert req.system_prompt == "[time]\nexisting"