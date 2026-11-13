"""公开信源适配器。

加一个新源不改代码：往 `feed_sources` 写一条记录，`kind` 选 `rss` 或 `html_list`，
参数放 `config_json`。抓取约定见 AGENTS.md。
"""

from . import base, html_list, rss

__all__ = ["base", "html_list", "rss"]
