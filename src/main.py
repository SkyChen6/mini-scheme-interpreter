"""入口：把整条流水线串起来（spec §2 的 CLI 约定）。

   程序文本 ──词法──→ token ──语法──→ 表达式 ──求值──→ 值 ──打印──→ 结果
   (lexer)          (parser)        (evaluator)      (printer)

用法：

    python3 src/main.py file1.scm [file2.scm ...]    # 依次求值这些文件
    python3 src/main.py                             # 没有参数就从标准输入读

行为约定：

- 按顺序求值每个顶层表达式，**每个结果独占一行**；
- 结果为"无值"（`display` / `newline`、省略了假分支的 `if`）时不打印；
- 多个文件共用同一个全局环境，后一个文件能看见前一个文件的 `define`；
- 出错时把一句话的错误信息写到 stderr，退出码 1（验收用例不会触发错误）。
"""

from __future__ import annotations

import locale
import os
import sys

# 允许直接以脚本方式运行（python3 src/main.py）：把 src 放进模块搜索路径
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from library import create_global_environment       # noqa: E402
from errors import SchemeError                      # noqa: E402
from evaluator import Evaluator                     # noqa: E402
from lexer import tokenize                          # noqa: E402
from parser import parse_program                    # noqa: E402
from printer import write                           # noqa: E402

# 本解释器不做尾调用优化（spec §10 明确不要求），深递归会真实地吃掉 Python 的栈。
# 每次 Scheme 调用大约要 10 层 Python 帧，这里把上限放宽到约一万层 Scheme 调用，
# 让 (sum-to 1000)、(count-down 5000) 这类常规深递归跑得完，
# 而不是先撞上 Python 默认的 1000 层限制。真超过上限时由下面的 RecursionError
# 分支给出一句人话的错误，而不是几千行堆栈。
RECURSION_LIMIT = 100000


def run_source(source, evaluator, environment, output=None) -> None:
    """求值一段源码里的每个顶层表达式，并逐行打印结果。"""
    stream = sys.stdout if output is None else output
    for expression in parse_program(tokenize(source)):
        value = evaluator.evaluate(expression, environment)
        if value is not None:               # None = 无值，不打印（spec §2）
            stream.write(write(value) + "\n")


def read_file(path) -> str:
    """读一个 .scm 文件。

    先按 UTF-8 读（顺带吃掉记事本可能写进去的 BOM），失败再退回本机默认编码——
    课程里的 .scm 多半是在 Windows 上用记事本存的，编码没法指望统一。
    """
    with open(path, "rb") as handle:
        data = handle.read()
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "gbk"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def read_stdin() -> str:
    """从标准输入读源码。

    用和 stdin 相同的编码解码，保证与外部喂数据的进程一致（避免把中文注释读成乱码）；
    万一遇到无法解码的字节，退化成 UTF-8 并替换，至少不中断求值。
    """
    stream = sys.stdin
    buffer = getattr(stream, "buffer", None)
    if buffer is None:                      # 例如被替换成 StringIO 时
        source = stream.read()
    else:
        data = buffer.read()
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            source = data.decode(encoding)
        except UnicodeDecodeError:
            source = data.decode("utf-8", errors="replace")
    return source.lstrip("\ufeff")          # 去掉可能存在的 BOM


def main(argv=None) -> int:
    """程序主流程：准备环境 → 取源码 → 求值 → 打印。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    sys.setrecursionlimit(RECURSION_LIMIT)

    evaluator = Evaluator()
    environment = create_global_environment(sys.stdout)   # 全局环境 + 内置过程

    try:
        if arguments:
            for path in arguments:                        # 多文件共享同一个环境
                run_source(read_file(path), evaluator, environment)
        else:
            run_source(read_stdin(), evaluator, environment)
    except SchemeError as error:
        print(f"mini-Scheme 错误：{error}", file=sys.stderr)
        return 1
    except RecursionError:
        # 递归太深撞上了 Python 的栈上限。本语言不承诺尾调用优化（spec §10），
        # 这里给一句人话，而不是吐出几千行 Python 堆栈。
        print("mini-Scheme 错误：递归层级太深（本解释器不做尾调用优化）", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"无法读取文件：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
