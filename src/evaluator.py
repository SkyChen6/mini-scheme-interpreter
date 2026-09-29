"""求值器：表达式 → 值（解释器的心脏）。

整个解释器的核心是两个**互相递归**的方法：

- `evaluate(expr, env)`：符号就去环境里查值；数字/布尔/字符串/空表原样返回；
  括号表达式先看是不是特殊形式（spec §4），不是就当函数调用——**先求值操作符和全部
  实参**，再交给 `apply`。
- `apply(procedure, arguments)`：内置过程直接调用；用户函数则新建一层环境把实参绑到
  参数名上（外层指向函数**定义时**的环境，这就是闭包），再回到 `evaluate` 求值函数体。

求值遇到函数调用就调 apply，apply 执行函数体又调回 evaluate——这个循环转起来，
解释器就成立了。

特殊形式由 `_HANDLERS` 表统一登记，每种形式一个方法，各自实现 spec §4 规定的求值顺序：

| 形式 | 求值顺序要点 |
|---|---|
| `quote` | 什么都不求值，原样返回 |
| `if` | 只求值测试和命中的那个分支 |
| `cond` | 自上而下逐个测试，命中后按 begin 求值 |
| `and` / `or` | 短路，能定结果就停 |
| `define` | 先求值右侧，再绑定；函数简写要造闭包 |
| `lambda` | 函数体不求值，连同当前环境打包成闭包 |
| `let` | 绑定表达式先在**外层**环境求值（并行绑定） |
| `begin` | 从左到右依次求值，返回最后一个 |
"""

from __future__ import annotations

from datatypes import (
    BuiltinProcedure,
    Closure,
    Pair,
    Symbol,
    is_truthy,
    to_python_list,
)
from environment import Environment
from errors import EvalError
from printer import write as write_text


class Evaluator:
    """一个无状态的求值器：环境由调用方传进来，方便多文件共享同一个全局环境。"""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        #: 特殊形式表。只有这些名字会被当作语法规则，其余一律按函数调用处理。
        self._handlers = {
            "quote": self._eval_quote,
            "if": self._eval_if,
            "cond": self._eval_cond,
            "and": self._eval_and,
            "or": self._eval_or,
            "define": self._eval_define,
            "lambda": self._eval_lambda,
            "let": self._eval_let,
            "begin": self._eval_begin,
        }

    # ------------------------------------------------------------------
    # 心脏 A：evaluate
    # ------------------------------------------------------------------
    def evaluate(self, expression, environment):
        """求值一个表达式，返回它的值。"""
        if isinstance(expression, Symbol):
            return environment.lookup(expression)
        if isinstance(expression, Pair):
            return self._evaluate_combination(expression, environment)
        # 自求值：数字、布尔、字符串、空表
        return expression

    def _evaluate_combination(self, expression, environment):
        """括号表达式：特殊形式，或者函数调用。"""
        head = expression.car
        if isinstance(head, Symbol):
            handler = self._handlers.get(str(head))
            if handler is not None:
                return handler(expression.cdr, environment)

        # 函数调用：先求值操作符，再从左到右求值全部实参（应用序，spec §9）
        procedure = self.evaluate(head, environment)
        arguments = [
            self.evaluate(argument, environment)
            for argument in to_python_list(expression.cdr)
        ]
        return self.apply(procedure, arguments)

    # ------------------------------------------------------------------
    # 心脏 B：apply
    # ------------------------------------------------------------------
    def apply(self, procedure, arguments):
        """调用一个过程。"""
        if isinstance(procedure, BuiltinProcedure):
            return procedure.function(*arguments)
        if isinstance(procedure, Closure):
            return self._apply_closure(procedure, arguments)
        raise EvalError(
            f"{write_text(procedure)} 不是过程，无法调用"
            f"（提示：mini-Scheme 是前缀语序，函数名写在括号最前面）"
        )

    def _apply_closure(self, closure: Closure, arguments):
        """调用用户函数：新建一层环境绑定实参，再求值函数体。"""
        parameters = closure.parameters
        if len(arguments) != len(parameters):
            raise EvalError(
                f"参数个数不符：期望 {len(parameters)} 个，实际给了 {len(arguments)} 个"
            )
        # 外层指向**定义时**的环境 → 词法作用域 + 闭包
        local = Environment(parent=closure.environment)
        for name, value in zip(parameters, arguments):
            local.define(name, value)
        return self._evaluate_sequence(closure.body, local)

    def _evaluate_sequence(self, expressions, environment):
        """begin 语义：依次求值，返回最后一个的结果；空序列返回 None（不打印）。"""
        result = None
        for expression in expressions:
            result = self.evaluate(expression, environment)
        return result

    # ------------------------------------------------------------------
    # 特殊形式（spec §4）
    # ------------------------------------------------------------------
    def _eval_quote(self, operands, environment):
        """`(quote 数据)`：原样返回，一个字符都不求值。"""
        return self._single_operand(operands, "quote")

    def _eval_if(self, operands, environment):
        """`(if 测试 真分支 假分支?)`：只求值命中的那个分支。"""
        parts = to_python_list(operands)
        if len(parts) not in (2, 3):
            raise EvalError("if: 需要 2 或 3 个部分（测试、真分支、可选假分支）")
        if is_truthy(self.evaluate(parts[0], environment)):
            return self.evaluate(parts[1], environment)
        if len(parts) == 3:
            return self.evaluate(parts[2], environment)
        return None                     # 假分支省略 → None，顶层不打印

    def _eval_cond(self, operands, environment):
        """`(cond (测试 表达式...) ...)`：命中第一个真测试后按 begin 求值。"""
        for clause in to_python_list(operands):
            parts = to_python_list(clause)
            if not parts:
                raise EvalError("cond: 子句不能为空")
            test = parts[0]
            if isinstance(test, Symbol) and str(test) == "else":
                return self._evaluate_sequence(parts[1:], environment)
            value = self.evaluate(test, environment)
            if is_truthy(value):
                if len(parts) == 1:
                    return value        # 子句里没有表达式 → 返回测试值本身
                return self._evaluate_sequence(parts[1:], environment)
        return None                     # 全部不匹配

    def _eval_and(self, operands, environment):
        """短路与：遇到 #f 立刻停；全为真返回最后一个值；`(and)` → #t。"""
        result = True
        for operand in to_python_list(operands):
            result = self.evaluate(operand, environment)
            if not is_truthy(result):
                return False
        return result

    def _eval_or(self, operands, environment):
        """短路或：遇到第一个非 #f 立刻返回它；`(or)` → #f。"""
        for operand in to_python_list(operands):
            result = self.evaluate(operand, environment)
            if is_truthy(result):
                return result
        return False

    def _eval_define(self, operands, environment):
        """`(define 名 表达式)` 或 `(define (函数名 参数...) 体...)`。结果是被定义的名字。"""
        parts = to_python_list(operands)
        if len(parts) < 2:
            raise EvalError("define: 需要「名字」和「表达式」两部分")
        target = parts[0]

        if isinstance(target, Symbol):                       # 定义变量
            value = self.evaluate(parts[1], environment)
            environment.define(target, value)
            return target

        if isinstance(target, Pair):                         # 定义函数的简写
            name = target.car
            if not isinstance(name, Symbol):
                raise EvalError("define: 函数名必须是符号")
            closure = self._make_closure(
                to_python_list(target.cdr), parts[1:], environment, "define"
            )
            environment.define(name, closure)
            return name

        raise EvalError(f"define: 不能定义 {write_text(target)}")

    def _eval_lambda(self, operands, environment):
        """`(lambda (参数...) 体...)`：函数体不求值，连同当前环境打包成闭包。"""
        parts = to_python_list(operands)
        if len(parts) < 2:
            raise EvalError("lambda: 需要参数表和函数体")
        parameters = to_python_list(parts[0])
        return self._make_closure(parameters, parts[1:], environment, "lambda")

    def _eval_let(self, operands, environment):
        """`(let ((名 表达式)...) 体...)`：**并行**绑定（spec §4.7）。

        关键在于所有绑定表达式都在**外层**环境求值完，再一次性装进新环境，
        所以 `(let ((a 1)) (let ((b (+ a 1))) ...))` 里的 b 看得见 a，
        而 `(let ((x 1)) (let ((x 2) (y x)) y))` 里的 y 取到的仍是外层的 1。
        """
        parts = to_python_list(operands)
        if len(parts) < 1:
            raise EvalError("let: 需要绑定表和函数体")
        bindings = []
        for binding in to_python_list(parts[0]):
            pair = to_python_list(binding)
            if len(pair) != 2:
                raise EvalError("let: 每个绑定形如 (名字 表达式)")
            name = pair[0]
            if not isinstance(name, Symbol):
                raise EvalError("let: 绑定的名字必须是符号")
            bindings.append((name, self.evaluate(pair[1], environment)))

        local = Environment(parent=environment)
        for name, value in bindings:
            local.define(name, value)
        return self._evaluate_sequence(parts[1:], local)

    def _eval_begin(self, operands, environment):
        """`(begin e1 e2 ...)`：从左到右依次求值，返回最后一个。"""
        return self._evaluate_sequence(to_python_list(operands), environment)

    # ------------------------------------------------------------------
    # 共用小工具
    # ------------------------------------------------------------------
    @staticmethod
    def _single_operand(operands, who: str):
        parts = to_python_list(operands)
        if len(parts) != 1:
            raise EvalError(f"{who}: 需要一个数据")
        return parts[0]

    @staticmethod
    def _make_closure(parameters, body, environment, who: str) -> Closure:
        """校验参数表与函数体，造出闭包。"""
        for parameter in parameters:
            if not isinstance(parameter, Symbol):
                raise EvalError(f"{who}: 参数名必须是符号，得到 {write_text(parameter)}")
        if not body:
            raise EvalError(f"{who}: 函数体不能为空")
        return Closure(parameters, body, environment)


__all__ = ["Evaluator"]
