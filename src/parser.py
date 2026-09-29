"""语法分析：token 列表 → 表达式（spec §3、§4.1）。

解析产物**直接复用**运行时数据结构（`Pair` / `Symbol` / 数字…），不做中间语法树，
所以 `'(1 2 3)` 与 `(list 1 2 3)` 最终得到同一种点对链——这正是 Scheme
"代码即数据"的体现，也让 `quote` 的实现退化成"原样返回"。

这里额外做两件改写工作：

1. 引用简写 `'x` 改写成 `(quote x)`（含 `'(1 2 3)`、`'()`）；
2. 点对写法 `(1 . 2)` 按 §6 组装成链尾。

括号不配对、`.` 位置不对之类的结构错误在这一层报 ParseError。
"""

from __future__ import annotations

from datatypes import NIL, Pair, Symbol, cons_list
from errors import ParseError
from lexer import ATOM, DOT, EOF, LPAREN, QUOTE, RPAREN

#: quote 改写时用的符号，模块内共用一份
_QUOTE_SYMBOL = Symbol("quote")


def parse_program(tokens):
    """把一个程序的 token 列表解析成顶层表达式列表。"""
    return _Parser(tokens).parse_all()


def _position(token):
    return f"第 {token.line} 行 {token.column} 列"


class _Parser:
    """递归下降解析器：只处理"括号"这一种嵌套结构，因此非常简单。"""

    __slots__ = ("_tokens", "_index")

    def __init__(self, tokens):
        self._tokens = tokens
        self._index = 0

    # --- 读 token 的小工具 ------------------------------------------------
    def _peek(self):
        return self._tokens[self._index]

    def _advance(self):
        """吃掉当前 token 并返回它；EOF 不会被吃掉，避免越界。"""
        token = self._tokens[self._index]
        if token.kind != EOF:
            self._index += 1
        return token

    def _at_end(self):
        return self._peek().kind == EOF

    # --- 语法规则 ---------------------------------------------------------
    def parse_all(self):
        """程序 = 若干顶层表达式，读到 EOF 为止。"""
        expressions = []
        while not self._at_end():
            expressions.append(self.parse_expression())
        return expressions

    def parse_expression(self):
        """一个表达式：括号列表 / 引用简写 / 原子。"""
        token = self._peek()
        if token.kind == EOF:
            raise ParseError(f"{_position(token)}：表达式不完整")
        if token.kind == RPAREN:
            raise ParseError(f"{_position(token)}：多余的 ')'")
        if token.kind == LPAREN:
            return self.parse_list()
        if token.kind == QUOTE:
            self._advance()
            # 'x 等价于 (quote x)
            return cons_list([_QUOTE_SYMBOL, self.parse_expression()])
        if token.kind == DOT:
            raise ParseError(f"{_position(token)}：'.' 只能出现在列表中间")
        self._advance()
        return token.value

    def parse_list(self):
        """`( ... )`：元素可以很多，可以有点对结尾 `(1 . 2)`，也可以是空表。"""
        open_token = self._advance()        # 吃掉 '('
        items = []
        tail = NIL

        while True:
            token = self._peek()
            if token.kind == EOF:
                raise ParseError(f"{_position(open_token)}：这个 '(' 没有闭合")
            if token.kind == RPAREN:
                self._advance()
                break
            if token.kind == DOT:
                if not items:
                    raise ParseError(f"{_position(token)}：'.' 前面没有元素")
                self._advance()
                tail = self.parse_expression()
                if self._peek().kind != RPAREN:
                    raise ParseError(f"{_position(token)}：点对结尾后面只能跟 ')'")
                self._advance()
                break
            items.append(self.parse_expression())

        return _with_tail(items, tail)


def _with_tail(items, tail):
    """把点对写法收拢成链：`(1 2 . 3)` → (1 . (2 . 3))。"""
    result = tail
    for item in reversed(items):
        result = Pair(item, result)
    return result
