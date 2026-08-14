"""Minutes persistence.

Writes the AIM-produced Markdown minutes to a local .md file. A stub hook
is kept for archiving into the personal knowledge base (out of scope for
this iteration).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger("meeting.persistence")


class KnowledgeBaseSink:
    """Stub for archiving archived minutes into the personal KB."""

    def archive(self, markdown: str, meta: dict):
        logger.info("knowledge-base archive stubbed (not implemented)")


class MeetingStore:
    """Owns the on-disk minutes file and delegates KB archiving."""

    def __init__(self, out_dir: str, title: str | None = None,
                 kb: KnowledgeBaseSink | None = None):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.kb = kb or KnowledgeBaseSink()
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.title = title or f"会议纪要_{now}"
        self.path = os.path.join(out_dir, f"{self.title}.md")
        self._body = ""

    def save(self, markdown: str, first: bool = False):
        """Overwrite the output file with the latest minutes and archive."""
        self._body = markdown
        content = f"# {self.title}\n\n" + markdown.strip() + "\n"
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("minutes written: %s", self.path)
        self.kb.archive(self._body, {"path": self.path, "title": self.title})
        return self.path
