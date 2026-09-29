"""解释器自测：把 spec 的每个特性都自己验一遍（README §3 的建议）。

运行方式（在仓库根目录）：

    python3 -m unittest discover -s tests -v

只依赖标准库 unittest，不需要额外安装任何东西。
组织方式与解释器的流水线一一对应：词法、语法、打印、求值各一组，
最后单独一组验 spec §11 排错指南里列出的那些坑。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import main as entry                                  # noqa: E402
from datatypes import Pair, SchemeString, Symbol, is_proper_list   # noqa: E402
from errors import EvalError, LexError, ParseError       # noqa: E402
from evaluator import Evaluator                          # noqa: E402
from lexer import ATOM, DOT, EOF, LPAREN, QUOTE, RPAREN, tokenize   # noqa: E402
from library import create_global_environment            # noqa: E402
from parser import parse_program                         # noqa: E402
from printer import display, write                       # noqa: E402


def setUpModule():
    # 本解释器不做尾调用优化，深递归用例需要放宽 Python 的栈限制
    sys.setrecursionlimit(20000)


# --------------------------------------------------------------------------
# 三个小工具：跑一段程序、只看输出、只看最后一个值
# --------------------------------------------------------------------------

def run(source) -> str:
    """求值源码，返回"逐行打印 + display 输出"的完整文本。"""
    stream = io.StringIO()
    evaluator = Evaluator()
    environment = create_global_environment(stream)
    entry.run_source(source, evaluator, environment, stream)
    return stream.getvalue()


def lines(source) -> list:
    return run(source).splitlines()


def last_value(source):
    """求值源码中所有顶层表达式，返回最后一个的值。"""
    evaluator = Evaluator()
    environment = create_global_environment(io.StringIO())
    result = None
    for expression in parse_program(tokenize(source)):
        result = evaluator.evaluate(expression, environment)
    return result


def text(source) -> str:
    """把最后一个表达式的值打印出来，方便断言。"""
    return write(last_value(source))


# --------------------------------------------------------------------------
# 1. 词法（spec §3）
# --------------------------------------------------------------------------

class LexerTests(unittest.TestCase):

    def kinds(self, source):
        return [token.kind for token in tokenize(source) if token.kind != EOF]

    def test_parentheses_quote_and_atoms(self):
        self.assertEqual(
            self.kinds("(+ 1 'x)"),
            [LPAREN, ATOM, ATOM, QUOTE, ATOM, RPAREN],
        )

    def test_comment_runs_to_end_of_line(self):
        tokens = tokenize("; (+ 1 2)\n7 ; 后面的都忽略\n")
        atoms = [token.value for token in tokens if token.kind == ATOM]
        self.assertEqual(atoms, [7])

    def test_whitespace_is_only_a_separator(self):
        self.assertEqual(self.kinds("(\t+  \n 1\r\n 2)"),
                         [LPAREN, ATOM, ATOM, ATOM, RPAREN])

    def test_numbers(self):
        tokens = [t for t in tokenize("42 -7 0 2.5") if t.kind == ATOM]
        self.assertEqual([t.value for t in tokens], [42, -7, 0, 2.5])
        self.assertIsInstance(tokens[0].value, int)
        self.assertIsInstance(tokens[3].value, float)

    def test_booleans(self):
        tokens = [t for t in tokenize("#t #f") if t.kind == ATOM]
        self.assertEqual([t.value for t in tokens], [True, False])

    def test_symbols_are_not_plain_strings(self):
        value = tokenize("foo")[0].value
        self.assertIsInstance(value, Symbol)
        self.assertEqual(str(value), "foo")

    def test_case_sensitive(self):
        self.assertNotEqual(tokenize("foo")[0].value, tokenize("FOO")[0].value)

    def test_string_escapes(self):
        value = tokenize(r'"a\nb\t\"c\"\\d"')[0].value
        self.assertIsInstance(value, SchemeString)
        self.assertEqual(value.value, 'a\nb\t"c"\\d')

    def test_unterminated_string_is_an_error(self):
        with self.assertRaises(LexError):
            tokenize('"没有收尾')

    def test_dot_is_its_own_token(self):
        self.assertEqual(self.kinds("(1 . 2)"), [LPAREN, ATOM, DOT, ATOM, RPAREN])

    def test_tokens_carry_positions(self):
        token = tokenize("\n  (+")[0]
        self.assertEqual((token.line, token.column), (2, 3))


# --------------------------------------------------------------------------
# 2. 语法（spec §3、§4.1、§6）
# --------------------------------------------------------------------------

class ParserTests(unittest.TestCase):

    def test_quote_shorthand_becomes_quote_form(self):
        self.assertEqual(write(parse_program(tokenize("'x"))[0]), "(quote x)")

    def test_empty_and_nested_lists(self):
        self.assertEqual(write(parse_program(tokenize("'()"))[0]), "(quote ())")
        program = parse_program(tokenize("(* (+ 1 2) 3)"))
        self.assertEqual(len(program), 1)
        self.assertTrue(is_proper_list(program[0]))

    def test_dotted_pair_syntax(self):
        self.assertEqual(text("'(1 . 2)"), "(1 . 2)")
        self.assertEqual(text("'(1 2 . 3)"), "(1 2 . 3)")

    def test_unbalanced_parenthesis_is_an_error(self):
        with self.assertRaises(ParseError):
            parse_program(tokenize("(+ 1 2"))

    def test_extra_closing_parenthesis_is_an_error(self):
        with self.assertRaises(ParseError):
            parse_program(tokenize("(+ 1 2))"))

    def test_incomplete_quote_is_an_error(self):
        with self.assertRaises(ParseError):
            parse_program(tokenize("'"))

    def test_multiple_top_level_expressions(self):
        self.assertEqual(len(parse_program(tokenize("1 2 3"))), 3)


# --------------------------------------------------------------------------
# 3. 打印（spec §8）
# --------------------------------------------------------------------------

class PrinterTests(unittest.TestCase):

    def test_basic_values(self):
        self.assertEqual(write(42), "42")
        self.assertEqual(write(-7), "-7")
        self.assertEqual(write(0.5), "0.5")
        self.assertEqual(write(True), "#t")
        self.assertEqual(write(False), "#f")
        self.assertEqual(write(Symbol("foo")), "foo")
        self.assertEqual(text("'()"), "()")

    def test_strings_are_quoted_and_escaped_when_written(self):
        self.assertEqual(write(SchemeString("hello")), '"hello"')
        self.assertEqual(write(SchemeString("a\nb")), '"a\\nb"')
        self.assertEqual(write(SchemeString('say "hi"')), '"say \\"hi\\""')

    def test_display_drops_the_quotes(self):
        self.assertEqual(display(SchemeString("hello")), "hello")
        self.assertEqual(display(SchemeString("a\nb")), "a\nb")

    def test_proper_list(self):
        self.assertEqual(text("(list 1 2 3)"), "(1 2 3)")

    def test_improper_pair(self):
        self.assertEqual(text("(cons 1 2)"), "(1 . 2)")
        self.assertEqual(text("(cons 1 (cons 2 3))"), "(1 2 . 3)")

    def test_procedure(self):
        self.assertEqual(text("car"), "#<procedure>")
        self.assertEqual(text("(lambda (x) x)"), "#<procedure>")


# --------------------------------------------------------------------------
# 4. 算术与比较（spec §5）
# --------------------------------------------------------------------------

class ArithmeticTests(unittest.TestCase):

    def test_variadic_arithmetic(self):
        self.assertEqual(lines("(+ 1 2 3)"), ["6"])
        self.assertEqual(lines("(- 10 4 1)"), ["5"])
        self.assertEqual(lines("(* 2 3 4)"), ["24"])
        self.assertEqual(lines("(+)"), ["0"])
        self.assertEqual(lines("(*)"), ["1"])

    def test_single_argument_negation(self):
        self.assertEqual(lines("(- 5)"), ["-5"])

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(lines("(/ 7 2)"), ["3"])
        self.assertEqual(lines("(/ -7 2)"), ["-3"])
        self.assertEqual(lines("(/ 7 -2)"), ["-3"])

    def test_single_argument_division_is_float(self):
        self.assertEqual(lines("(/ 2)"), ["0.5"])

    def test_modulo_and_quotient(self):
        self.assertEqual(lines("(modulo 17 5)"), ["2"])
        self.assertEqual(lines("(quotient 17 5)"), ["3"])
        self.assertEqual(lines("(quotient -7 2)"), ["-3"])

    def test_expt_and_abs(self):
        self.assertEqual(lines("(expt 2 10)"), ["1024"])
        self.assertEqual(lines("(abs (- 5 9))"), ["4"])

    def test_division_by_zero_is_an_error(self):
        with self.assertRaises(EvalError):
            last_value("(/ 1 0)")

    def test_arithmetic_rejects_non_numbers(self):
        with self.assertRaises(EvalError):
            last_value("(+ 1 'a)")


class ComparisonTests(unittest.TestCase):

    def test_chained_comparison(self):
        self.assertEqual(lines("(< 2 3 4)"), ["#t"])
        self.assertEqual(lines("(< 2 3 3)"), ["#f"])
        self.assertEqual(lines("(> 5 5)"), ["#f"])
        self.assertEqual(lines("(<= 5 5)"), ["#t"])
        self.assertEqual(lines("(>= 5 5)"), ["#t"])
        self.assertEqual(lines("(= 1 1 1)"), ["#t"])

    def test_comparison_works_on_symbols(self):
        self.assertEqual(lines("(< 'a 'b)"), ["#t"])

    def test_value_equality_vs_structural_equality(self):
        self.assertEqual(lines("(eq? '() '())"), ["#t"])
        self.assertEqual(lines("(eq? '(1) '(1))"), ["#f"])
        self.assertEqual(lines("(equal? '(1 2 3) (list 1 2 3))"), ["#t"])
        self.assertEqual(lines("(eq? 'a 'a)"), ["#t"])


class BooleanTests(unittest.TestCase):

    def test_short_circuit(self):
        # 短路：后面的 (/ 1 0) 根本不会执行，所以不报错
        self.assertEqual(lines("(and #f (/ 1 0))"), ["#f"])
        self.assertEqual(lines("(or #t (/ 1 0))"), ["#t"])

    def test_empty_and_or(self):
        self.assertEqual(lines("(and)"), ["#t"])
        self.assertEqual(lines("(or)"), ["#f"])

    def test_and_or_values(self):
        self.assertEqual(lines("(and 1 2 3)"), ["3"])
        self.assertEqual(lines("(or #f 2 3)"), ["2"])
        self.assertEqual(lines("(and #t #f)"), ["#f"])
        self.assertEqual(lines("(or #f #f)"), ["#f"])

    def test_only_false_is_false(self):
        self.assertEqual(lines("(if 0 'truthy 'falsy)"), ["truthy"])
        self.assertEqual(lines("(if '() 'truthy 'falsy)"), ["truthy"])
        self.assertEqual(lines("(if #f 'truthy 'falsy)"), ["falsy"])

    def test_not(self):
        self.assertEqual(lines("(not #f)"), ["#t"])
        self.assertEqual(lines("(not 0)"), ["#f"])
        self.assertEqual(lines("(not #t)"), ["#f"])


# --------------------------------------------------------------------------
# 5. 特殊形式（spec §4）
# --------------------------------------------------------------------------

class SpecialFormTests(unittest.TestCase):

    def test_quote_returns_data_untouched(self):
        self.assertEqual(lines("'x"), ["x"])
        self.assertEqual(lines("'(1 2 3)"), ["(1 2 3)"])
        self.assertEqual(lines("'()"), ["()"])
        self.assertEqual(lines("(quote (1 (2 3)))"), ["(1 (2 3))"])

    def test_if(self):
        self.assertEqual(lines("(if (> 3 2) 'yes 'no)"), ["yes"])
        self.assertEqual(lines("(if #f 'bad 'good)"), ["good"])
        self.assertEqual(lines("(if (null? '()) 1 2)"), ["1"])

    def test_if_without_alternative_has_no_value(self):
        self.assertEqual(run("(if #f 1)"), "")

    def test_if_does_not_evaluate_the_other_branch(self):
        self.assertEqual(lines("(if #t 1 (/ 1 0))"), ["1"])

    def test_cond(self):
        self.assertEqual(lines("(cond ((= 1 2) 'a) ((= 2 2) 'b) (else 'c))"), ["b"])
        self.assertEqual(lines("(cond (else 'd))"), ["d"])
        self.assertEqual(lines("(cond ((> 2 3)) (else 42))"), ["42"])

    def test_cond_clause_without_body_returns_the_test_value(self):
        self.assertEqual(lines("(cond ((+ 1 2)))"), ["3"])

    def test_cond_without_match_has_no_value(self):
        self.assertEqual(run("(cond ((= 1 2) 'a))"), "")

    def test_cond_body_is_a_sequence(self):
        self.assertEqual(lines("(cond (#t 1 2 3))"), ["3"])

    def test_define_and_print_the_name(self):
        self.assertEqual(lines("(define pi 3)\n(+ pi 1)"), ["pi", "4"])

    def test_define_function_shorthand(self):
        self.assertEqual(lines("(define (square x) (* x x))\n(square 7)"), ["square", "49"])

    def test_lambda(self):
        self.assertEqual(lines("((lambda (x) (* x 2)) 5)"), ["10"])

    def test_let(self):
        self.assertEqual(lines("(let ((x 3) (y 4)) (+ x y))"), ["7"])
        self.assertEqual(lines("(let ((a 1)) (let ((b (+ a 1))) (* a b)))"), ["2"])

    def test_let_binds_in_parallel(self):
        # 并行绑定：内层 y 取到的是外层 x（=1），而不是同层的 x（=2）
        self.assertEqual(lines("(let ((x 1)) (let ((x 2) (y x)) y))"), ["1"])

    def test_begin(self):
        self.assertEqual(lines("(begin (define z 1) (+ z 41))"), ["42"])
        self.assertEqual(lines("(begin 1 2 3)"), ["3"])

    def test_nested_special_forms(self):
        program = """
        (define (classify n)
          (cond ((< n 0) 'negative)
                ((= n 0) 'zero)
                (else (if (even? n) 'even 'odd))))
        (classify -5)
        (classify 0)
        (classify 8)
        (classify 9)
        """
        self.assertEqual(lines(program), ["classify", "negative", "zero", "even", "odd"])


# --------------------------------------------------------------------------
# 6. 函数、闭包与递归（spec §4.6、§7、§9）
# --------------------------------------------------------------------------

class FunctionTests(unittest.TestCase):

    def test_closure_remembers_its_definition_environment(self):
        program = """
        (define (make-adder n) (lambda (x) (+ x n)))
        (define add5 (make-adder 5))
        (add5 10)
        ((make-adder 100) 7)
        """
        self.assertEqual(lines(program), ["make-adder", "add5", "15", "107"])

    def test_closure_keeps_environment_alive_after_call_returns(self):
        program = """
        (define (counter-from start) (lambda (step) (+ start step)))
        (define c (counter-from 10))
        (c 1)
        (c 100)
        """
        self.assertEqual(lines(program), ["counter-from", "c", "11", "110"])

    def test_lexical_scope_not_dynamic(self):
        # 函数体里看到的是定义处的 x，而不是调用处的 x
        program = """
        (define x 1)
        (define (get-x) x)
        (let ((x 99)) (get-x))
        """
        self.assertEqual(lines(program), ["x", "get-x", "1"])

    def test_recursion(self):
        program = """
        (define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))
        (fact 10)
        (define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))
        (fib 15)
        (define (sum-to n) (if (= n 0) 0 (+ n (sum-to (- n 1)))))
        (sum-to 1000)
        """
        self.assertEqual(lines(program),
                         ["fact", "3628800", "fib", "610", "sum-to", "500500"])

    def test_wrong_argument_count_is_an_error(self):
        with self.assertRaises(EvalError):
            last_value("(define (f x) x)\n(f 1 2)")

    def test_calling_a_non_procedure_is_an_error(self):
        with self.assertRaises(EvalError):
            last_value("(1 2 3)")

    def test_unbound_variable_is_an_error(self):
        with self.assertRaises(EvalError):
            last_value("nope")


# --------------------------------------------------------------------------
# 7. 列表（spec §5、§6）
# --------------------------------------------------------------------------

class ListTests(unittest.TestCase):

    def test_accessors(self):
        self.assertEqual(lines("(car '(1 2 3))"), ["1"])
        self.assertEqual(lines("(cdr '(1 2 3))"), ["(2 3)"])
        self.assertEqual(lines("(cdr '(1))"), ["()"])

    def test_cons_builds_pairs_and_lists(self):
        self.assertEqual(lines("(cons 1 '(2 3))"), ["(1 2 3)"])
        self.assertEqual(lines("(cons 1 2)"), ["(1 . 2)"])

    def test_list_procedure_is_a_function_call(self):
        self.assertEqual(lines("(list 1 2 3)"), ["(1 2 3)"])
        self.assertEqual(lines("(list (+ 1 1) 2)"), ["(2 2)"])
        self.assertEqual(lines("(list)"), ["()"])

    def test_length_and_append(self):
        self.assertEqual(lines("(length '(a b c d))"), ["4"])
        self.assertEqual(lines("(append '(1 2) '(3 4))"), ["(1 2 3 4)"])
        self.assertEqual(lines("(append '(1) '(2) '(3))"), ["(1 2 3)"])
        self.assertEqual(lines("(append)"), ["()"])
        self.assertEqual(lines("(append '(1 2))"), ["(1 2)"])
        self.assertEqual(lines("(append '(1) 2)"), ["(1 . 2)"])

    def test_list_predicates(self):
        self.assertEqual(lines("(null? '())"), ["#t"])
        self.assertEqual(lines("(null? '(1))"), ["#f"])
        self.assertEqual(lines("(pair? '(1 2))"), ["#t"])
        self.assertEqual(lines("(pair? '())"), ["#f"])
        self.assertEqual(lines("(list? '(1 2))"), ["#t"])
        self.assertEqual(lines("(list? (cons 1 2))"), ["#f"])

    def test_user_defined_map_and_filter(self):
        program = """
        (define (map f xs)
          (if (null? xs) '() (cons (f (car xs)) (map f (cdr xs)))))
        (define (filter pred xs)
          (cond ((null? xs) '())
                ((pred (car xs)) (cons (car xs) (filter pred (cdr xs))))
                (else (filter pred (cdr xs)))))
        (map (lambda (x) (* x x)) '(1 2 3 4))
        (filter odd? '(1 2 3 4 5))
        (length (map (lambda (x) (+ x 1)) '(1 2 3 4 5 6)))
        """
        self.assertEqual(lines(program), ["map", "filter", "(1 4 9 16)", "(1 3 5)", "6"])

    def test_deeply_nested_structure(self):
        self.assertEqual(lines("'(1 (2 (3 (4))))"), ["(1 (2 (3 (4))))"])
        self.assertEqual(lines("(equal? '(1 (2 3)) (list 1 (list 2 3)))"), ["#t"])


# --------------------------------------------------------------------------
# 8. 谓词（spec §5、§11）
# --------------------------------------------------------------------------

class PredicateTests(unittest.TestCase):

    def test_type_predicates(self):
        cases = {
            "(number? 5)": "#t",
            "(number? 'x)": "#f",
            "(number? #t)": "#f",
            "(boolean? #t)": "#t",
            "(boolean? 0)": "#f",
            "(symbol? 'x)": "#t",
            "(symbol? \"x\")": "#f",
            "(string? \"s\")": "#t",
            "(string? 's)": "#f",
            "(procedure? car)": "#t",
            "(procedure? (lambda (x) x))": "#t",
            "(procedure? 1)": "#f",
            "(zero? 0)": "#t",
            "(even? 8)": "#t",
            "(odd? 7)": "#t",
        }
        for program, expected in cases.items():
            with self.subTest(program=program):
                self.assertEqual(lines(program), [expected])

    def test_booleans_are_not_numbers(self):
        # Python 里 True == 1，这里必须靠类型区分（spec §11）
        self.assertEqual(lines("(equal? #t 1)"), ["#f"])
        self.assertEqual(lines("(equal? (= 1 1) 1)"), ["#f"])

    def test_symbol_is_not_a_string(self):
        # Python 里 Symbol 是 str 的子类，直接比较会误判（spec §11）
        self.assertEqual(lines("(equal? 'a \"a\")"), ["#f"])
        self.assertEqual(lines("(eq? 'a \"a\")"), ["#f"])

    def test_eq_uses_identity_for_compound_data(self):
        self.assertEqual(lines("(eq? '(1) '(1))"), ["#f"])
        self.assertEqual(lines("(define xs (list 1))\n(eq? xs xs)"), ["xs", "#t"])

    def test_equal_compares_structure(self):
        self.assertEqual(lines("(equal? '(1 2 3) (list 1 2 3))"), ["#t"])
        self.assertEqual(lines("(equal? '(1 2) '(1 3))"), ["#f"])
        self.assertEqual(lines("(equal? '() '())"), ["#t"])


# --------------------------------------------------------------------------
# 9. 输出与入口（spec §2、§5）
# --------------------------------------------------------------------------

class OutputTests(unittest.TestCase):

    def test_display_and_newline_have_no_value(self):
        self.assertEqual(run("(display 3)"), "3")
        self.assertEqual(run("(newline)"), "\n")
        self.assertEqual(run("(begin (display 1) (newline) 9)"), "1\n9\n")

    def test_display_of_string_is_unquoted(self):
        self.assertEqual(run('(display "hello")'), "hello")
        self.assertEqual(run('(display "a\\nb")'), "a\nb")

    def test_top_level_string_is_quoted(self):
        self.assertEqual(run('"hello"'), '"hello"\n')
        self.assertEqual(run('"a\\nb"'), '"a\\nb"\n')

    def test_display_of_a_list(self):
        self.assertEqual(run("(display '(1 2 3))"), "(1 2 3)")

    def test_each_result_on_its_own_line(self):
        self.assertEqual(run("1 2 3"), "1\n2\n3\n")

    def test_no_output_for_empty_program(self):
        self.assertEqual(run("; 只有注释\n"), "")


class EntryPointTests(unittest.TestCase):

    def test_reads_a_file_and_shares_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "a.scm")
            second = os.path.join(directory, "b.scm")
            with open(first, "w", encoding="utf-8") as handle:
                handle.write("; 定义放这儿\n(define x 41)\n")
            with open(second, "w", encoding="utf-8") as handle:
                handle.write("(+ x 1)\n")     # 后一个文件看得见前一个的 define
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = entry.main([first, second])
            self.assertEqual(code, 0)
            self.assertEqual(buffer.getvalue(), "x\n42\n")

    def test_file_saved_with_bom_is_still_readable(self):
        # 记事本存的 UTF-8 会带 BOM，不能让它变成程序里第一个多余的符号
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bom.scm")
            with open(path, "w", encoding="utf-8-sig") as handle:
                handle.write("(+ 40 2)\n")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = entry.main([path])
            self.assertEqual(code, 0)
            self.assertEqual(buffer.getvalue(), "42\n")

    def test_reads_standard_input_when_no_argument(self):
        buffer = io.StringIO()
        saved = sys.stdin
        try:
            sys.stdin = io.StringIO("(+ 1 2)\n")
            with contextlib.redirect_stdout(buffer):
                code = entry.main([])
        finally:
            sys.stdin = saved
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "3\n")

    def test_error_goes_to_stderr_with_exit_code_1(self):
        errors = io.StringIO()
        saved = sys.stdin
        try:
            sys.stdin = io.StringIO("(car 1)\n")
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(errors):
                code = entry.main([])
        finally:
            sys.stdin = saved
        self.assertEqual(code, 1)
        self.assertIn("car", errors.getvalue())

    def test_missing_file_is_reported(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = entry.main([os.path.join(tempfile.gettempdir(), "不存在的文件.scm")])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
