"""Bounded decimal arithmetic; never executes supplied Python code."""
import ast
from fractions import Fraction
from math import isqrt
from decimal import Decimal, DecimalException, Inexact, Underflow, localcontext
import re

UNSIGNED = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
NUMBER = r"[+-]?" + UNSIGNED


def calculate(expression):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 512:
        return {"status": "error", "error": "Use an expression of 1–512 characters."}
    original = expression.strip()
    expression = original.replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    expression = re.sub(rf"({UNSIGNED})\s*%", r"(\1/100)", expression)
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 128:
            raise ValueError("Expression is too complex.")
        with localcontext() as context:
            context.prec = 40
            context.Emax = 100
            context.Emin = -100
            context.traps[Underflow] = True
            def bounded(value):
                if value and not Fraction(1, 10**100) <= abs(value) < 10**101:
                    raise ValueError("Magnitude exceeds the calculator's limits.")
                return value
            def visit(node, depth=0):
                if depth > 32:
                    raise ValueError("Expression is too deeply nested.")
                if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                    token = ast.get_source_segment(expression, node)
                    if not re.fullmatch(NUMBER, token):
                        raise ValueError("Use ordinary decimal numbers.")
                    return bounded(Fraction(token))
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                    value = visit(node.operand, depth + 1)
                    return bounded(value if isinstance(node.op, ast.UAdd) else -value)
                if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                    left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
                    if isinstance(node.op, ast.Add): value = left + right
                    elif isinstance(node.op, ast.Sub): value = left - right
                    elif isinstance(node.op, ast.Mult): value = left * right
                    elif isinstance(node.op, ast.Div): value = left / right
                    else:
                        if right.denominator != 1 or abs(right) > 100 or (not left and not right):
                            raise ValueError("Powers require an integer exponent between -100 and 100.")
                        value = left ** int(right)
                    return bounded(value)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in {"sqrt", "abs"} and len(node.args) == 1 and not node.keywords):
                    value = visit(node.args[0], depth + 1)
                    if node.func.id == "abs":
                        return abs(value)
                    if value < 0:
                        raise ValueError("Square root requires a nonnegative value.")
                    numerator, denominator = isqrt(value.numerator), isqrt(value.denominator)
                    if numerator*numerator == value.numerator and denominator*denominator == value.denominator:
                        return bounded(Fraction(numerator, denominator))
                    return bounded(Fraction((Decimal(value.numerator)/Decimal(value.denominator)).sqrt()))
                raise ValueError("Use numbers, +, -, *, /, ^, parentheses, sqrt(), or abs(). Percent means divide by 100.")
            value = visit(tree.body)
            root_approximate = context.flags[Inexact]
            exact = str(value) if not root_approximate else None
            if value.denominator == 1:
                result = str(value.numerator)
            else:
                result = format(Decimal(value.numerator)/Decimal(value.denominator), "f")
            approximate = context.flags[Inexact]
            if "." in result:
                result = result.rstrip("0").rstrip(".")
            if value == 0:
                result = "0"
            return {"status": "ok", "expression": original, "result": result,
                    "exact": exact, "approximate": approximate, "precision_digits": 40}
    except (SyntaxError, ValueError, DecimalException, RecursionError, ZeroDivisionError):
        return {"status": "error", "error": "Cannot calculate that expression. Check syntax, division by zero, root domain, and size limits."}


def chat_expression(prompt):
    """Recognize only a complete explicit calculation, never instructions in prose."""
    text = prompt.strip()
    if len(text) > 600:
        return None
    text = re.sub(r"^(?:(?:please|can you)\s+)?(?:calculate|compute|what is|what's|solve)\s+", "", text, flags=re.I)
    text = re.sub(r"[?=]\s*$", "", text).strip()
    percent = re.fullmatch(rf"({NUMBER})\s*%\s+of\s+({NUMBER})", text, re.I)
    if percent:
        return f"({percent[1]}/100)*({percent[2]})"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    tokens = re.sub(r"\b(?:sqrt|abs)\b", "", text)
    if re.search(r"\d", text) and re.fullmatch(r"[\d.eE+*/^%()\s×÷−-]+", tokens):
        return text
    return None
