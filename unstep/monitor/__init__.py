"""A team of specialist watchers that run side by side over the same radio events.

Each watcher owns one part of the tower's work, keeps its own timers and notices, and posts what it sees as plain
rows for the console's "Agents at work" feed. They are fixed rules, not language models: they answer in
microseconds, never wait on each other, and one failing does not stop the others. An Elastic agent can be asked to
explain a row afterwards, off this path. See docs/20-agent-map.md section 8.
"""

from unstep.monitor.team import Team, default_team  # noqa: F401
