"""知识层：术语归一与范例检索。

- `terms`：同义写法归一（JD 的「数据仓库建模」与经历里的「数仓建模」算同一个说法）；
- `examples`：写法范例检索，语料以 `data/knowledge/examples.json` 作为种子导入资料层，
  之后索引与检索交给 `documents` + FTS，不再固定读一个 JSON 文件。

两者的共同约束：结果必须可复算、可解释。不做 embedding、不把判断交给模型——
生成阶段的防幻觉校验依赖这些判定，判定自由了整条链路就不可复核。
"""
from . import examples, terms

__all__ = ["examples", "terms"]
