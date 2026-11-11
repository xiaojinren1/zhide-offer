"""社群内容：面经卡、内推卡、JD 评价卡。

边界（与 AGENTS.md 一致）：

- 对外只出现匿名马甲，账号与马甲的映射只在服务端；
- 公开列表一律在 SQL 里限定 `status = 'public'`，未审核内容对他人不可见；
- 入库前脱敏，审核退回必须写理由；
- 管理员的审核、删除走同一套角色判断（数据库 `user_roles`）。
"""

from . import cards, redact

__all__ = ["cards", "redact"]
