"""
AstrBot core monkey-patches.
Isolated here so they can be audited, version-checked, and removed cleanly
when upstream fixes land.
"""

from astrbot.api import logger


def _check_upstream_fix(toolset_cls) -> bool:
    """Check if the upstream ToolSet.openai_schema already handles description=None.

    Inspect the default schema output to see if description is safely
    defaulted (not None) when a tool has no description.
    Returns True if the upstream fix is detected (patch not needed).
    """
    try:
        from astrbot.core.agent.tool import Tool

        # Create a minimal tool with description=None to test
        test_tool = Tool(
            name="__patch_test__",
            description=None,
            parameters=None,
        )
        test_instance = toolset_cls(tools=[test_tool])
        schema = test_instance.openai_schema(omit_empty_parameter_field=True)

        if schema and schema[0]["function"].get("description") is not None:
            logger.info(
                "[MonkeyPatch] Upstream already handles description=None, patch not needed"
            )
            return True
    except Exception:
        pass
    return False


def apply_toolset_patch() -> bool:
    """Patch ToolSet.openai_schema to handle description=None.

    Instead of replacing the entire method, this wraps the original and
    post-processes any schema entries where description is still None,
    substituting the tool name. This is less invasive than a full override
    and will gracefully degrade if upstream fixes the bug.

    Returns:
        True if the patch was applied successfully, False otherwise.
    """
    try:
        from astrbot.core.agent.tool import ToolSet
    except ImportError:
        logger.debug("[MonkeyPatch] ToolSet not found, skipping patch")
        return False

    # Check if upstream already fixed the issue
    if _check_upstream_fix(ToolSet):
        return True

    try:
        _original_method = ToolSet.openai_schema

        def _wrapped_openai_schema(self, omit_empty_parameter_field=False):
            result = _original_method(self, omit_empty_parameter_field)
            # Post-process: fix any None descriptions without replacing the method
            for entry in result:
                func = entry.get("function", {})
                if func.get("description") is None:
                    func["description"] = func.get("name", "unknown")
            return result

        ToolSet.openai_schema = _wrapped_openai_schema
        logger.info(
            "[MonkeyPatch] ToolSet.openai_schema wrapped (description=None post-process fix)"
        )
        return True

    except Exception as e:
        logger.warning(f"[MonkeyPatch] ToolSet patch failed: {e}")
        return False
