"""AgentSys-inspired security layer for OpenCortex.

Three-layer defense:
1. Validator — checks if tool calls are safe and necessary
2. Sanitizer — removes injected instructions from tool return values
3. PrivilegeAssignor — classifies tools as Query (read) or Command (write)

All components default to OFF. Enable via SecuritySettings.
"""

from opencortex.security.security_layer import SecurityLayer

__all__ = ["SecurityLayer"]
