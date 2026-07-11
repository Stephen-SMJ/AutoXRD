"""Built-in agent definitions — AgentDefinition dataclass + system prompts.

Corresponds to:
  TS: tools/AgentTool/built-in/exploreAgent.ts
  TS: features/coordinator.py (get_worker_system_prompt)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    """Describes a built-in agent type for use in AgentTool dispatch and description rendering."""
    agent_type: str          # used as subagent_type value, e.g. "worker", "Explore"
    when_to_use: str         # shown in AgentTool description
    tools_description: str   # shown in AgentTool description, e.g. "All tools" or "Read, Glob, Grep, Bash"


EXPLORE_SYSTEM_PROMPT = """\
You are a file search specialist for a coding assistant. You excel at thoroughly \
navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
- Modifying existing files (no Edit operations)
- Deleting files (no rm or deletion)
- Moving or copying files (no mv or cp)
- Creating temporary files anywhere, including /tmp
- Using redirect operators (>, >>, |) or heredocs to write to files
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code. You do NOT have \
access to file editing tools — attempting to edit files will fail.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use Read when you know the specific file path you need to read
- Use Bash ONLY for read-only operations (ls, git status, git log, git diff, find, cat, head, tail)
- NEVER use Bash for: mkdir, touch, rm, cp, mv, git add, git commit, pip install, \
or any file creation/modification
- Adapt your search approach based on the thoroughness level specified by the caller \
("quick", "medium", or "very thorough")
- Communicate your final report directly as a regular message — do NOT attempt to create files

NOTE: You are meant to be a fast agent that returns output as quickly as possible. \
Make efficient use of the tools at your disposal. Wherever possible, spawn multiple \
parallel tool calls for grepping and reading files.

Complete the user's search request efficiently and report your findings clearly.\
"""


BUILTIN_AGENT_DEFINITIONS: list[AgentDefinition] = [
    AgentDefinition(
        agent_type="worker",
        when_to_use=(
            "General-purpose agent for researching complex questions, searching for code, "
            "and executing multi-step tasks. When you are searching for a keyword or file "
            "and are not confident that you will find the right match in the first few tries "
            "use this agent to perform the search for you."
        ),
        tools_description="All tools",
    ),
    AgentDefinition(
        agent_type="Explore",
        when_to_use=(
            "Fast agent specialized for exploring codebases. Use this when you need to quickly "
            "find files by patterns (eg. \"src/components/**/*.tsx\"), search code for keywords "
            "(eg. \"API endpoints\"), or answer questions about the codebase (eg. \"how do API "
            "endpoints work?\"). When calling this agent, specify the desired thoroughness level: "
            "\"quick\" for basic searches, \"medium\" for moderate exploration, or \"very thorough\" "
            "for comprehensive analysis across multiple locations and naming conventions."
        ),
        tools_description="Read, Glob, Grep, Bash (read-only)",
    ),
]
