"""AgentSys-inspired security layer for OpenCortex.

Four-layer defense:
1. ToolClassifier — rule-based tool categorization (EXTERNAL / INTERNAL / COMMAND)
2. Validator — checks if tool calls are safe and necessary
3. Sanitizer — removes injected instructions from tool return values
4. PrivilegeAssignor — classifies tools as Query (read) or Command (write)

SecurityLayer is enabled by default with all components active.
"""

from opencortex.security.tool_classifier import ToolCategory, ToolClassifier
from opencortex.security.security_layer import SecurityLayer

__all__ = ["SecurityLayer", "ToolClassifier", "ToolCategory"]
