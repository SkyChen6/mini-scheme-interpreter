"""内置过程库（spec §5）。

分工很明确：**求值器负责"什么时候调用"**（先求值操作符和全部实参），
**这里只负责"怎么算"**：检查类型、算结果、返回。

约定：

- 返回 `None` 表示"无值"（`display` / `newline`），入口据此决定不打印那一行；
- 类型不对、除以零之类的问题统一抛 `EvalError`，交给入口转成一行错误信息；
- 按 spec §5 的分类分成若干组，最后一并装进全局环境。

几处容易踩的坑（spec §11）都做了处理：整数相除得整数商且向零截断、`eq?` 对复合数据比
同一性、`equal?` 先比类型再比值、只有 `#f` 是假。
"""

from __future__ import annotations

import sys

from datatypes import (
    BuiltinProcedure,
    NIL,
    Pair,
    Procedure,
    SchemeString,
    Symbol,
    cons_list,
    is_number,
    is_proper_list,
    is_truthy,
    to_python_list,
)
from environment import Environment
from errors import EvalError
from printer import display as display_text
from printer import write as write_text


def create_global_environment(output=None) -> Environment:
    """造一个装好全部内置过程的全局环境（spec §2：每个进程从空环境起步）。

    `output` 是 `display` / `newline` 往哪写，默认标准输出；测试时可以传一个
    StringIO 进来把输出抓走。
    """
    stream = sys.stdout if output is None else output

    environment = Environment()
    groups = (
        _arithmetic(),
        _comparison(),
        _list_procedures(),
        _type_predicates(),
        _equality(),
        _output_procedures(stream),
    )
    for group in groups:
        for name, function in group.items():
            environment.define(Symbol(name), BuiltinProcedure(name, function))
    return environment


# --------------------------------------------------------------------------
# 类型检查的小工具
# --------------------------------------------------------------------------

def _require_number(value, who: str):
    """要求一个数字（布尔不算数字：Python 里 True 也是 int）。"""
    if not is_number(value):
        raise EvalError(f"{who}: 需要数字，得到 {write_text(value)}")
    return value


def _require_pair(value, who: str) -> Pair:
    if not isinstance(value, Pair):
        raise EvalError(f"{who}: 需要点对，得到 {write_text(value)}")
    return value


def _require_integer(value, who: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvalError(f"{who}: 需要整数，得到 {write_text(value)}")
    return value


def _truncating_divide(left, right, who: str):
    """整数相除得整数商，且负数商**向零截断**：`(/ -7 2)` → -3（spec §5）。"""
    if right == 0:
        raise EvalError(f"{who}: 除以零")
    if isinstance(left, int) and isinstance(right, int):
        magnitude = abs(left) // abs(right)
        return magnitude if (left < 0) == (right < 0) else -magnitude
    return left / right


# --------------------------------------------------------------------------
# 算术（spec §5）
# --------------------------------------------------------------------------

def _add(*arguments):
    total = 0
    for value in arguments:
        total = total + _require_number(value, "+")
    return total


def _subtract(*arguments):
    if not arguments:
        raise EvalError("-: 至少需要一个参数")
    numbers = [_require_number(value, "-") for value in arguments]
    if len(numbers) == 1:               # 单参数取反：(- 5) → -5
        return -numbers[0]
    result = numbers[0]
    for value in numbers[1:]:
        result = result - value
    return result


def _multiply(*arguments):
    result = 1
    for value in arguments:
        result = result * _require_number(value, "*")
    return result


def _divide(*arguments):
    if not arguments:
        raise EvalError("/: 至少需要一个参数")
    numbers = [_require_number(value, "/") for value in arguments]
    if len(numbers) == 1:               # 单参数求倒数，结果是浮点：(/ 2) → 0.5
        if numbers[0] == 0:
            raise EvalError("/: 除以零")
        return 1 / numbers[0]
    result = numbers[0]
    for value in numbers[1:]:
        result = _truncating_divide(result, value, "/")
    return result


def _modulo(*arguments):
    numbers = [_require_integer(value, "modulo") for value in arguments]
    if not numbers:
        raise EvalError("modulo: 至少需要一个参数")
    result = numbers[0]
    for value in numbers[1:]:
        if value == 0:
            raise EvalError("modulo: 除以零")
        result = result % value          # Python 的 % 与 Scheme modulo 符号规则一致
    return result


def _quotient(*arguments):
    numbers = [_require_integer(value, "quotient") for value in arguments]
    if not numbers:
        raise EvalError("quotient: 至少需要一个参数")
    result = numbers[0]
    for value in numbers[1:]:
        result = _truncating_divide(result, value, "quotient")
    return result


def _expt(base, exponent):
    left = _require_number(base, "expt")
    right = _require_number(exponent, "expt")
    return left ** right


def _absolute(value):
    return abs(_require_number(value, "abs"))


def _arithmetic():
    return {
        "+": _add,
        "-": _subtract,
        "*": _multiply,
        "/": _divide,
        "modulo": _modulo,
        "quotient": _quotient,
        "expt": _expt,
        "abs": _absolute,
    }


# --------------------------------------------------------------------------
# 比较与布尔（spec §5）
# --------------------------------------------------------------------------

def _make_chain(name, compare):
    """链式比较：相邻两两都要成立才为真，`(< 2 3 4)` → #t。

    按 spec §5 支持数字与符号（符号比名字）；符号个数少于两个时直接为真。
    """

    def chain(*arguments):
        for left, right in zip(arguments, arguments[1:]):
            if is_number(left) and is_number(right):
                holds = compare(left, right)
            elif isinstance(left, Symbol) and isinstance(right, Symbol):
                holds = compare(str(left), str(right))
            else:
                raise EvalError(
                    f"{name}: 只能比较数字或符号，得到 "
                    f"{write_text(left)} 与 {write_text(right)}"
                )
            if not holds:
                return False
        return True

    return chain


def _not(value):
    """取反。注意 `(not 0)` → #f：只有 #f 是假（spec §5）。"""
    return not is_truthy(value)


def _comparison():
    return {
        "=": _make_chain("=", lambda a, b: a == b),
        "<": _make_chain("<", lambda a, b: a < b),
        ">": _make_chain(">", lambda a, b: a > b),
        "<=": _make_chain("<=", lambda a, b: a <= b),
        ">=": _make_chain(">=", lambda a, b: a >= b),
        "not": _not,
    }


# --------------------------------------------------------------------------
# 列表（spec §5、§6）
# --------------------------------------------------------------------------

def _cons(head, tail):
    """构造点对：`(cons 1 2)` → `(1 . 2)`，`(cons 1 '(2 3))` → `(1 2 3)`。"""
    return Pair(head, tail)


def _car(pair):
    return _require_pair(pair, "car").car


def _cdr(pair):
    return _require_pair(pair, "cdr").cdr


def _list(*arguments):
    return cons_list(arguments)


def _length(value):
    count = 0
    node = value
    while isinstance(node, Pair):
        count += 1
        node = node.cdr
    if node is not NIL:
        raise EvalError(f"length: 需要真列表，得到 {write_text(value)}")
    return count


def _append(*lists):
    """拼接若干列表。最后一个参数不必是列表（Scheme 语义），`(append)` → ()。"""
    if not lists:
        return NIL
    result = lists[-1]
    for value in reversed(lists[:-1]):
        for item in reversed(to_python_list(value)):
            result = Pair(item, result)
    return result


def _list_procedures():
    return {
        "cons": _cons,
        "car": _car,
        "cdr": _cdr,
        "list": _list,
        "length": _length,
        "append": _append,
        "null?": lambda value: value is NIL,
        "pair?": lambda value: isinstance(value, Pair),
        "list?": is_proper_list,
    }


# --------------------------------------------------------------------------
# 类型谓词（spec §5）
# --------------------------------------------------------------------------

def _even(value):
    number = _require_integer(value, "even?")
    return number % 2 == 0


def _odd(value):
    number = _require_integer(value, "odd?")
    return number % 2 != 0


def _type_predicates():
    return {
        "number?": is_number,
        "boolean?": lambda value: isinstance(value, bool),
        "symbol?": lambda value: isinstance(value, Symbol),
        "string?": lambda value: isinstance(value, SchemeString),
        "procedure?": lambda value: isinstance(value, Procedure),
        "zero?": lambda value: _require_number(value, "zero?") == 0,
        "even?": _even,
        "odd?": _odd,
    }


# --------------------------------------------------------------------------
# 相等性（spec §5、§11）
# --------------------------------------------------------------------------

def _eq(left, right):
    """`eq?`：符号、数字、布尔、字符串按值；列表等复合数据按**同一性**。

    `(eq? '() '())` → #t（空表是唯一实例），`(eq? '(1) '(1))` → #f（两串不同的点对）。
    """
    if isinstance(left, Symbol) or isinstance(right, Symbol):
        return isinstance(left, Symbol) and isinstance(right, Symbol) and str(left) == str(right)
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return type(left) is type(right) and left == right
    if isinstance(left, SchemeString) and isinstance(right, SchemeString):
        return left.value == right.value
    return left is right


def _equal(left, right):
    """`equal?`：结构相等，逐层比较。

    每一层都**先比类型再比值**，避免 Python 的 `True == 1`、
    符号是字符串子类导致 `'a == "a"` 这类误判（spec §11）。
    """
    if isinstance(left, Symbol) or isinstance(right, Symbol):
        return isinstance(left, Symbol) and isinstance(right, Symbol) and str(left) == str(right)
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return type(left) is type(right) and left == right
    if isinstance(left, SchemeString) or isinstance(right, SchemeString):
        return (
            isinstance(left, SchemeString)
            and isinstance(right, SchemeString)
            and left.value == right.value
        )
    if isinstance(left, Pair) or isinstance(right, Pair):
        if not (isinstance(left, Pair) and isinstance(right, Pair)):
            return False
        return _equal(left.car, right.car) and _equal(left.cdr, right.cdr)
    return left is right          # 空表与过程：同一性比较


def _equality():
    return {"eq?": _eq, "equal?": _equal}


# --------------------------------------------------------------------------
# 输出（spec §5、§2）
# --------------------------------------------------------------------------

def _output_procedures(stream):
    """`display` / `newline` 都返回 None，表示"无值"，顶层不打印结果行。"""

    def display(value):
        stream.write(display_text(value))
        return None

    def newline():
        stream.write("\n")
        return None

    return {"display": display, "newline": newline}
