"""公开信源适配器。

加一个新源不改代码：往 `feed_sources` 写一条记录，`kind` 选 `rss` 或 `html_list`，
参数放 `config_json`。详见 `docs/plan-jobs-knowledge-community.md` 与 AGENTS.md 的抓取约定。
"""

from . import base, html_list, rss

__all__ = ["base", "html_list", "rss"]
