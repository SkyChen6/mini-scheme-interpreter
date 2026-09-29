"""词法分析：程序文本 → token 列表（spec §3）。

职责单一：只把一段文本切成最小的"零件"，顺便把数字/布尔/字符串解析成真正的值、
把其它单词包成 `Symbol`。**不判断括号是否配对**，也不构造嵌套结构——那是语法分析的事。

词法层面要处理的东西（对应 spec §3 的零件表）：

- 注释：`;` 到行尾整段丢掉；
- 空白：空格、换行、制表符都只是分隔符；
- 数字：整数（浮点字面量也顺手支持，spec 里标为"可选"）；
- 布尔：只有 `#t` / `#f` 两种写法；
- 字符串：双引号包住，支持 `\\n` `\\t` `\\"` `\\\\` 转义；
- 引用简写 `'`、括号 `(` `)`、点对中间的点 `.` 各自成为独立的 token。

产出的 token 列表末尾**总是**追加一个 EOF，这样语法分析器只需往后看一个 token
就能判断"表达式不完整"，不用到处写越界检查。
"""

from __future__ import annotations

import re

from datatypes import SchemeString, Symbol
from errors import LexError

# --- token 种类 -----------------------------------------------------------
LPAREN = "LPAREN"    # (
RPAREN = "RPAREN"    # )
QUOTE = "QUOTE"      # ' 引用简写
DOT = "DOT"          # 点对中间的点，如 (1 . 2)
ATOM = "ATOM"        # 值已解析好的原子：数字 / 布尔 / 字符串 / 符号
EOF = "EOF"          # 输入结束

_PARENS = {"(": LPAREN, ")": RPAREN, "'": QUOTE}

_WHITESPACE = " \t\r\n\f\v"
_COMMENT = ";"
_QUOTE_CHAR = '"'
_DOT = "."

#: 扫原子时一遇到这些字符就停下
_ATOM_BREAKS = set(_WHITESPACE) | set("()'\";")

#: 用正则而不是 int()/float() 判断，避免 `int("1_0") == 10` 这类 Python 特性
_INTEGER_PATTERN = re.compile(r"^[+-]?[0-9]+$")
_FLOAT_PATTERN = re.compile(r"^[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?$")

_ESCAPE_TABLE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class Token:
    """一个词法单元：种类 + 值 + 位置（位置用来在报错时指路）。"""

    __slots__ = ("kind", "value", "line", "column")

    def __init__(self, kind, value, line, column):
        self.kind = kind
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):  # pragma: no cover - 仅供调试
        return f"Token({self.kind}, {self.value!r}, line={self.line}, col={self.column})"


def tokenize(source):
    """把源码文本切成 token 列表（末尾带一个 EOF）。"""
    tokens = []
    index = 0
    line = 1
    column = 1
    length = len(source)

    while index < length:
        char = source[index]

        if char == "\n":
            index += 1
            line += 1
            column = 1
        elif char in _WHITESPACE:
            index += 1
            column += 1
        elif char == _COMMENT:
            while index < length and source[index] != "\n":
                index += 1
        elif char in _PARENS:
            tokens.append(Token(_PARENS[char], None, line, column))
            index += 1
            column += 1
        elif char == _QUOTE_CHAR:
            start_line, start_column = line, column
            value, index, line, column = _read_string(source, index, line, column)
            # 记的是字符串**起始**位置，报错时更直观
            tokens.append(Token(ATOM, value, start_line, start_column))
        else:
            start_line, start_column = line, column
            start = index
            while index < length and source[index] not in _ATOM_BREAKS:
                index += 1
            text = source[start:index]
            column += index - start
            if text == _DOT:
                tokens.append(Token(DOT, None, start_line, start_column))
            else:
                tokens.append(Token(ATOM, _atom_value(text), start_line, start_column))

    tokens.append(Token(EOF, None, line, column))
    return tokens


def _atom_value(text):
    """把一个原子文本解析成真正的值：布尔 → 数字 → 符号。"""
    if text == "#t":
        return True
    if text == "#f":
        return False
    if _INTEGER_PATTERN.match(text):
        return int(text)
    if _FLOAT_PATTERN.match(text):
        return float(text)
    # 其余一律当符号：foo、x1、+、... 大小写敏感（spec §3）
    return Symbol(text)


def _read_string(source, index, line, column):
    """从开引号处读一个字符串，返回 (值, 新的 index/line/column)。

    起始位置单独记下来，好在"没闭合"时指出是哪一行。
    """
    start_line, start_column = line, column
    index += 1          # 跳过开头的双引号
    column += 1
    chars = []
    length = len(source)

    while index < length:
        char = source[index]
        if char == "\\":
            index += 1
            column += 1
            if index >= length:
                break
            escape = source[index]
            # 认识的转义按表替换，不认识的保留字符本身（宽容处理）
            chars.append(_ESCAPE_TABLE.get(escape, escape))
            index += 1
            column += 1
        elif char == _QUOTE_CHAR:
            index += 1
            column += 1
            return SchemeString("".join(chars)), index, line, column
        elif char == "\n":
            chars.append(char)
            index += 1
            line += 1
            column = 1
        else:
            chars.append(char)
            index += 1
            column += 1

    raise LexError(f"第 {start_line} 行 {start_column} 列：字符串缺少收尾的双引号")
