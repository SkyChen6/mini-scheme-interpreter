"""环境：变量绑定表 + 指向外层环境的指针（spec §9）。

一个环境就是"一层作用域"。查找变量时先在当前层找，找不到就顺着 parent 往外找，
一直找到全局环境；都没有就报"未绑定的变量"。

这个"链"结构是**词法作用域**的全部秘密：

- `lambda` 求值时把当时的环境存进闭包，调用时新建的环境以它为 parent，
  于是函数体里看到的永远是定义处的变量，而不是调用处的；
- `define` 把名字绑进**当前**这层，所以顶层 define 互相可见；
- `let` 新建一层环境，绑定不会泄漏到外面。
"""

from __future__ import annotations

from errors import EvalError


class Environment:
    """一层作用域。`parent` 为 None 表示全局环境。"""

    __slots__ = ("_bindings", "parent")

    def __init__(self, parent: "Environment | None" = None) -> None:
        #: 名字（Symbol）→ 值
        self._bindings = {}
        self.parent = parent

    def define(self, name, value) -> None:
        """在当前这层绑定名字。同名会被覆盖（Scheme 的 define 语义）。"""
        self._bindings[name] = value

    def lookup(self, name):
        """顺着环境链查找名字的值，找不到报错。"""
        environment = self
        while environment is not None:
            bindings = environment._bindings
            if name in bindings:
                return bindings[name]
            environment = environment.parent
        raise EvalError(f"未绑定的变量：{name}")

    def __contains__(self, name) -> bool:
        environment = self
        while environment is not None:
            if name in environment._bindings:
                return True
            environment = environment.parent
        return False

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        kind = "global" if self.parent is None else "local"
        return f"<Environment {kind} {sorted(self._bindings)}>"
