"""岗位、资料、投递与社群的统一数据层。

设计边界（见 docs/plan-jobs-knowledge-community.md）：

- **一层存所有资料**：岗位 JD、用户上传的 JD、面试复盘、技术笔记同表，
  用 `kind` 与 `source` 区分，避免"岗位表 + 资料表"各写一遍检索。
- **公共岗位池用 `user_id = NULL`**：信源采集来的岗位是全站共享内容，
  不按用户复制一份；唯一索引用 `COALESCE(user_id, '')` 保证池内也去重。
- **FTS5 独立表，不用外部内容表**：分块写入与重建都由 `store.upsert_chunks()`
  显式同步，不依赖触发器；触发器一旦写错会静默丢索引，排查成本更高。
"""

from . import dedupe, normalize, schema, store, text

__all__ = ["dedupe", "normalize", "schema", "store", "text"]
