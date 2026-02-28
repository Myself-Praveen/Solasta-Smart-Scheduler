"""
Solasta — Tool Registry

Central registry for all tools available to the Executor Agent.
Tools are strongly typed, well-documented, and sandboxed.
The registry enables dynamic tool binding per step.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tool Registry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


class ToolExecutionError(Exception):
    """Structured tool failure propagated to the Executor."""

    def __init__(self, message: str, payload: Dict[str, Any]):
        super().__init__(message)
        self.payload = payload


def register_tool(
    name: str,
    description: str,
    handler: Callable,
    parameters: Optional[Dict[str, str]] = None,
) -> None:
    """Register a tool in the global registry."""
    _TOOL_REGISTRY[name] = {
        "name": name,
        "description": description,
        "handler": handler,
        "parameters": parameters or {},
    }
    logger.debug("tool_registered", name=name)


def get_tool_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Look up a tool by name."""
    return _TOOL_REGISTRY.get(name)


def get_all_tools() -> Dict[str, Dict[str, Any]]:
    """Return all registered tools."""
    return dict(_TOOL_REGISTRY)


def list_tool_names() -> List[str]:
    """Return all registered tool names."""
    return list(_TOOL_REGISTRY.keys())


async def execute_tool(name: str, params: Dict[str, Any]) -> Any:
    """Execute a registered tool by name with the given parameters."""
    tool = _TOOL_REGISTRY.get(name)
    if not tool:
        raise ValueError(f"Tool '{name}' not found in registry. Available: {list_tool_names()}")

    handler = tool["handler"]
    logger.info("tool_executing", name=name, params=list(params.keys()))

    try:
        import asyncio
        import traceback
        
        async def run():
            if asyncio.iscoroutinefunction(handler):
                return await handler(**params)
            else:
                return handler(**params)
        
        # Phase 13: Tool Execution Boundary (Hard timeout limit)
        TOOL_TIMEOUT = 15.0 
        result = await asyncio.wait_for(run(), timeout=TOOL_TIMEOUT)
        
        logger.info("tool_executed", name=name, success=True)
        return result
    except asyncio.TimeoutError:
        error_msg = f"Tool '{name}' timed out after {TOOL_TIMEOUT} seconds"
        logger.error("tool_execution_timeout", name=name, error=error_msg)

        payload = {
            "error_code": "TOOL_TIMEOUT",
            "component": f"Tool_{name}",
            "trace": error_msg,
            "agent_recovery_action": "Switch to alternative tool or replan",
        }
        raise ToolExecutionError(error_msg, payload)
    except Exception as e:
        logger.error("tool_execution_error", name=name, error=str(e))

        payload = {
            "error_code": "TOOL_EXECUTION_ERROR",
            "component": f"Tool_{name}",
            "trace": "".join(traceback.format_exception(type(e), e, e.__traceback__)),
            "agent_recovery_action": "Replanner must generate alternative action.",
        }
        raise ToolExecutionError(str(e), payload)
