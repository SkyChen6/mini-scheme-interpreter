"""打印：值 → 文本（spec §8）。

两种模式，区别只在对字符串的处理：

- `write`：顶层求值结果的打印方式。字符串**带引号**，并且把换行/制表符等
  打印成 `\\n` `\\t` 转义形式，保证输出是"可读回来的"。
- `display`：`display` 过程用的方式。字符串**不带引号**，内容原样输出。

列表的点对链在这里还原成 Scheme 的写法：正规链打 `(1 2 3)`，
链尾不是空表则打点对 `(1 . 2)`。
"""

from __future__ import annotations

from datatypes import NIL, Pair, Procedure, SchemeString, Symbol

_BOOLEAN_TEXT = {True: "#t", False: "#f"}
_PROCEDURE_TEXT = "#<procedure>"

_ESCAPE_TABLE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def write(value) -> str:
    """机器可读形式：顶层结果、错误信息里用它。"""
    return _to_text(value, human=False)


def display(value) -> str:
    """人读形式：`display` 过程用它。"""
    return _to_text(value, human=True)


def _to_text(value, human: bool) -> str:
    # 注意顺序：布尔必须排在数字前面，因为 Python 里 bool 是 int 的子类
    if value is True or value is False:
        return _BOOLEAN_TEXT[value]
    if isinstance(value, Symbol):
        return str(value)
    if isinstance(value, SchemeString):
        return value.value if human else _quote_string(value.value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_float(value)
    if value is NIL:
        return "()"
    if isinstance(value, Pair):
        return _pair_text(value, human)
    if isinstance(value, Procedure):
        return _PROCEDURE_TEXT
    return repr(value)          # 兜底：不该出现的值时至少不炸


def _pair_text(pair: Pair, human: bool) -> str:
    """把点对链写成 `(a b c)` 或 `(a b . c)`。"""
    parts = []
    node = pair
    while isinstance(node, Pair):
        parts.append(_to_text(node.car, human))
        node = node.cdr
    if node is NIL:
        return "(" + " ".join(parts) + ")"
    return "(" + " ".join(parts) + " . " + _to_text(node, human) + ")"


def _quote_string(text: str) -> str:
    """给字符串加引号，并转义控制字符。"""
    out = ['"']
    for char in text:
        out.append(_ESCAPE_TABLE.get(char, char))
    out.append('"')
    return "".join(out)


def _format_float(value: float) -> str:
    """浮点按 Python 的默认短表示打印：0.5、2.0、-3.25。"""
    if value != value:                      # NaN
        return "+nan.0"
    if value == float("inf"):
        return "+inf.0"
    if value == float("-inf"):
        return "-inf.0"
    return repr(value)
