# OpenCortex 🧠

> Modular AI Agent Framework — Built on OpenHarness, hardened with AgentSys security, enhanced with Hermes capabilities.

## Overview

OpenCortex is a production-grade AI Agent framework that combines the best of three open-source projects:

- **[OpenHarness](https://github.com/hkudslab/open-harness)** — Clean, modular agent skeleton (core engine, 43+ tools, permission system)
- **[AgentSys](https://github.com/agentdojo/agentsys)** — Three-layer security defense (Validator, Sanitizer, Privilege Assignor)
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** — Advanced features (multi-channel gateway, skill auto-learning, enhanced memory)

## Architecture

```
┌─────────────────────────────────────────────┐
│           UI Layer (Zellij Terminal)         │
├─────────────────────────────────────────────┤
│        Multi-Channel Gateway                 │
│     (Feishu / Telegram / Web / ...)         │
├─────────────────────────────────────────────┤
│           Agent Core (ReAct Loop)            │
├──────────┬──────────┬───────────┬───────────┤
│  Tools   │ Security │  Memory   │  Skills   │
│  (43+)   │ (AgentSys)│ (Hermes) │ (Hermes)  │
├──────────┴──────────┴───────────┴───────────┤
│        Services (Cron / LSP / Plugins)       │
└─────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/opencortex.git
cd opencortex

# Setup virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run
opencortex
```

## Roadmap

- [x] Phase 1: Fork OpenHarness core, Zellij terminal integration
- [ ] Phase 2: AgentSys security layer integration
- [ ] Phase 3: Hermes feature migration (gateway, skills, memory)
- [ ] Phase 4: Polish, testing, documentation

## License

MIT
