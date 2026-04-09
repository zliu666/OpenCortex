"""A2A Agent Card - Declares OpenCortex capabilities."""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class Capability:
    """Single capability declaration."""

    name: str
    type: str  # "tool", "resource", "feature"
    description: str
    parameters: Optional[dict] = None


@dataclass
class AgentCard:
    """A2A Agent Card - Describes an agent's capabilities."""

    # Identity
    name: str = "OpenCortex"
    version: str = "0.1.5"
    agent_id: str = "opencortex-0.1.5"
    description: str = "开源 AI 编程助手，支持多轮对话、工具调用、安全检查、子 Agent 管理"

    # Capabilities
    capabilities: List[Capability] = field(default_factory=list)

    # Supported models
    supported_models: List[str] = field(default_factory=lambda: [
        "glm-4-flash", "glm-4.7", "glm-5-turbo"
    ])

    # Configuration
    max_context_length: int = 128000
    supports_streaming: bool = True
    supports_cancel: bool = True
    supports_human_in_loop: bool = False  # Phase 2

    # Contact/Discovery
    base_url: Optional[str] = None
    documentation_url: str = "https://github.com/zliu666/opencortex"
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to A2A-compliant dict."""
        return {
            "name": self.name,
            "version": self.version,
            "agent_id": self.agent_id,
            "description": self.description,
            "capabilities": [
                {
                    "name": cap.name,
                    "type": cap.type,
                    "description": cap.description,
                    "parameters": cap.parameters
                }
                for cap in self.capabilities
            ],
            "supported_models": self.supported_models,
            "max_context_length": self.max_context_length,
            "supports_streaming": self.supports_streaming,
            "supports_cancel": self.supports_cancel,
            "supports_human_in_loop": self.supports_human_in_loop,
            "base_url": self.base_url,
            "documentation_url": self.documentation_url,
            "updated_at": self.updated_at.isoformat()
        }


# Default Agent Card for OpenCortex
DEFAULT_AGENT_CARD = AgentCard(
    capabilities=[
        Capability(
            name="multi_turn_conversation",
            type="feature",
            description="多轮对话，保持上下文"
        ),
        Capability(
            name="tool_calling",
            type="feature",
            description="工具调用（bash、read、write、search 等）"
        ),
        Capability(
            name="security_layer",
            type="feature",
            description="三级安全防线（Validator、Sanitizer、PrivilegeAssignor）"
        ),
        Capability(
            name="sub_agent",
            type="feature",
            description="子 Agent 管理（创建、监控、取消）"
        ),
        Capability(
            name="terminal_fission",
            type="feature",
            description="终端裂变，可视化子 Agent 输出"
        ),
        Capability(
            name="trajectory_tracking",
            type="feature",
            description="轨迹追踪，记录完整思考链"
        ),
        Capability(
            name="ftsmemory",
            type="feature",
            description="FTS5 全文搜索记忆"
        ),
        Capability(
            name="analytics",
            type="feature",
            description="会话洞察引擎（token 使用、模型性能）"
        ),
        Capability(
            name="bash",
            type="tool",
            description="执行 shell 命令",
            parameters={"max_output_lines": 500, "timeout_seconds": 120}
        ),
        Capability(
            name="read",
            type="tool",
            description="读取文件内容",
            parameters={"max_file_size_kb": 1024}
        ),
        Capability(
            name="write",
            type="tool",
            description="写入文件"
        ),
        Capability(
            name="edit",
            type="tool",
            description="编辑文件（精确替换）"
        )
    ],
    base_url="http://127.0.0.1:8765/a2a"
)
