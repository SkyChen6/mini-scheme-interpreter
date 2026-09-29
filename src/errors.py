"""解释器的错误类型。

spec §10 说明"错误处理策略不在范围内"（出错时行为未定义，验收测试不触发错误）。
但一个健壮的解释器应当给出人话的错误信息而不是 Python 堆栈，所以这里统一了一套
异常类型：全流程只抛 SchemeError 的子类，由入口 src/main.py 捕获后写到 stderr。
"""


class SchemeError(Exception):
    """mini-Scheme 解释过程中的错误基类。"""


class LexError(SchemeError):
    """词法阶段出错：例如字符串少了收尾的双引号。"""


class ParseError(SchemeError):
    """语法阶段出错：例如括号不配对、'.' 用错位置。"""


class EvalError(SchemeError):
    """求值阶段出错：例如未绑定的变量、参数个数不符、类型不对。"""
