"""
AstrBot core monkey-patches.
Isolated here so they can be audited, version-checked, and removed cleanly
when upstream fixes land.
"""

from astrbot.api import logger


def apply_toolset_patch() -> bool:
    """Patch ToolSet.openai_schema to handle description=None.

    AstrBot's ToolSet.openai_schema can produce a schema with
    description=None, which triggers a 400 error from the OpenAI API.
    This patch substitutes the tool name when description is missing.

    Returns:
        True if the patch was applied successfully, False otherwise.
    """
    try:
        from astrbot.core.agent.tool import ToolSet

        _original = ToolSet.openai_schema

        def _fixed_openai_schema(self, omit_empty_parameter_field=False):
            result = []
            for tool in self.tools:
                func_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or tool.name,
                    },
                }
                if tool.parameters is not None:
                    if (
                        tool.parameters and tool.parameters.get("properties")
                    ) or not omit_empty_parameter_field:
                        func_def["function"]["parameters"] = tool.parameters
                result.append(func_def)
            return result

        ToolSet.openai_schema = _fixed_openai_schema
        logger.info(
            "[MonkeyPatch] ToolSet.openai_schema patched (description=None fix)"
        )
        return True

    except ImportError:
        logger.debug("[MonkeyPatch] ToolSet not found, skipping patch")
        return False
    except Exception as e:
        logger.warning(f"[MonkeyPatch] ToolSet patch failed: {e}")
        return False
