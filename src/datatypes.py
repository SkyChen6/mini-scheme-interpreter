"""mini-Scheme 的数据类型与值语义（spec §6、§8、§9）。

设计要点：

- **列表就是点对链**。不做"Python list 当列表"的偷懒写法，
  `(1 2 3)` 直接表示为 `Pair(1, Pair(2, Pair(3, NIL)))`，
  这样 `quote` 出来的数据与 `cons` 构造的数据天然是同一种东西（spec §11 的坑）。
- **符号不是字符串**。`Symbol` 虽然继承 `str`（方便比较名字），
  但字符串用独立的 `SchemeString` 类表示，从类型上就切断了
  `(equal? 'a "a")` 被判成相等这类事故。
- **布尔与数字要分清**。Python 里 `True == 1`、`bool` 是 `int` 的子类，
  所以 `is_number()` 一律显式排除布尔。

这些类型既被解析器用来构造程序，也被求值器用来表示运行时的值——两者共用一套结构，
是"代码即数据"这一 Scheme 特点的落地方式。
"""

from __future__ import annotations

from errors import EvalError


class Symbol(str):
    """符号（变量名、操作符名）。继承 str 只是为了比较名字方便。"""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        return f"Symbol({str.__repr__(self)})"


class SchemeString:
    """mini-Scheme 字符串。独立类型，按内容相等。"""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SchemeString) and self.value == other.value

    def __hash__(self) -> int:
        return hash((SchemeString, self.value))

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        return f"SchemeString({self.value!r})"


class Nil:
    """空表 `()`。全程序唯一实例，`eq?` 对它的同一性比较因此自然成立。"""

    __slots__ = ()
    _instance: "Nil | None" = None

    def __new__(cls) -> "Nil":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "()"


#: 空表的唯一实例，代码里统一用 NIL 而不是 Nil()
NIL = Nil()


class Pair:
    """点对（cons cell）：car 是第一项，cdr 是剩余部分。"""

    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr) -> None:
        self.car = car
        self.cdr = cdr

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        return f"Pair({self.car!r}, {self.cdr!r})"


class Procedure:
    """所有可调用对象的基类，用于 procedure? 与错误提示。"""

    __slots__ = ()


class BuiltinProcedure(Procedure):
    """内置过程：包一个 Python 函数。参数由求值器先求值好再传进来。"""

    __slots__ = ("name", "function")

    def __init__(self, name: str, function) -> None:
        self.name = name
        self.function = function

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        return f"BuiltinProcedure({self.name})"


class Closure(Procedure):
    """用户函数（lambda 的产物）。

    `environment` 保存**定义时**的环境而不是调用时的环境，这正是词法作用域与
    闭包的关键（spec §9）：`(define (make-adder n) (lambda (x) (+ x n)))` 里
    返回的 lambda 之所以还记得 n，就是靠它。
    """

    __slots__ = ("parameters", "body", "environment")

    def __init__(self, parameters, body, environment) -> None:
        self.parameters = tuple(parameters)
        self.body = tuple(body)
        self.environment = environment

    def __repr__(self) -> str:  # pragma: no cover - 仅供调试
        return f"Closure({self.parameters}, ...)"


# --------------------------------------------------------------------------
# 值的构造与判断（供求值器、内置库共用）
# --------------------------------------------------------------------------

def cons_list(items) -> "Pair | Nil":
    """把 Python 序列转成点对链：`[1, 2]` → `(1 2)`。"""
    result = NIL
    for item in reversed(list(items)):
        result = Pair(item, result)
    return result


def to_python_list(value) -> list:
    """把真列表展开成 Python list；不是真列表（点对结尾）时报错。"""
    items = []
    while isinstance(value, Pair):
        items.append(value.car)
        value = value.cdr
    if value is not NIL:
        raise EvalError("期望一个真列表，但遇到了点对结尾")
    return items


def is_proper_list(value) -> bool:
    """是否是"真列表"（以 NIL 收尾的点对链）。`(list? (cons 1 2))` → #f。"""
    while isinstance(value, Pair):
        value = value.cdr
    return value is NIL


def is_number(value) -> bool:
    """是否是数字。布尔要排除：Python 里 `True` 也是 `int`。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_truthy(value) -> bool:
    """mini-Scheme 的真假判断：**只有 #f 是假**（spec §9），0、()、"" 都是真。"""
    return value is not False
