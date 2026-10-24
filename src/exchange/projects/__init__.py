"""Project homes (Roadmap phase 7): git-tracked folders of plain files for one project each.

A project home holds the project's identity, goals, records (compiled game data, one Markdown file
each, typed by the signature prefix of its editor ID) and claims (dated work and ideas), plus a
coverage rules file. Files are the source of truth; this package reads, validates and creates
them, and takes git checkpoints. See ``docs/PROJECT_HOME.md`` for the formats and
``docs/GAME_DATA_MODEL.md`` for the design.
"""

from exchange.projects.home import ProjectHome, find_home, init_home, resolve_project
from exchange.projects.validate import Finding, Gap, Report, validate_home

__all__ = ["Finding", "Gap", "ProjectHome", "Report", "find_home", "init_home", "resolve_project",
           "validate_home"]
