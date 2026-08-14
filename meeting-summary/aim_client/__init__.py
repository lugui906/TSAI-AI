"""AIM interaction layer.

Business layer talks to the AIM core exclusively via the `aim` CLI:
  aim newrun <payload>  -> start a new conversation
  aim run <payload>     -> continue the current conversation
All inference / model calls / context management are handled by AIM.
This package never imports any LLM / model libraries.
"""
