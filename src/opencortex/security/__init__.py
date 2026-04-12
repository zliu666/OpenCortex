"""AgentSys-inspired security layer for OpenCortex.

Four-layer defense:
1. ToolClassifier — rule-based tool categorization (EXTERNAL / INTERNAL / COMMAND)
2. Validator — checks if tool calls are safe and necessary
3. Sanitizer — removes injected instructions from tool return values
4. PrivilegeAssignor — classifies tools as Query (read) or Command (write)

Plus sub-agent isolation:
5. SubAgentDispatcher — isolates EXTERNAL tool results
6. IntentInjector — injects intent parameters for Tool-as-Solver protocol

SecurityLayer is enabled by default with all components active.
"""

from opencortex.security.dispatcher import SubAgentDispatcher, DispatchResult
from opencortex.security.intent import IntentInjector
from opencortex.security.security_layer import SecurityLayer, SecurityCheckResult
from opencortex.security.tool_classifier import ToolCategory, ToolClassifier

__all__ = [
    "SecurityLayer",
    "SecurityCheckResult",
    "ToolClassifier",
    "ToolCategory",
    "SubAgentDispatcher",
    "DispatchResult",
    "IntentInjector",
]
