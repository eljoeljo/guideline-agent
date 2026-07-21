"""ADK entrypoint for the Intake Agent.

This module exposes `root_agent` so the `adk` CLI can discover and run the
local agent via `adk run agent`.
"""
from .intake_agent import create_agent

# Expose a root_agent instance for the ADK CLI.
# The ADK runtime will import this module to find the agent definition.
root_agent = create_agent()
