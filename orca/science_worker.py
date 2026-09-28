"""Isolated symbolic math worker. Build SymPy objects from an allowlisted AST, never eval."""
import ast
import json
import re
import sys


def execute(payload):
    import sympy as sp
    operations = {'evaluate', 'simplify', 'differentiate', 'integrate', 'definite_integral',
                  'solve', 'matrix_determinant', 'matrix_inverse', 'linear_solve', 'eigenvalues'}
    if not isinstance(payload, dict):
        raise ValueError('Request must be an object.')
    operation = payload.get('operation')
    if operation not in operations:
        raise ValueError('Unknown scientific operation.')
    allowed = {'operation', 'precision'}
    if operation in {'matrix_determinant', 'matrix_inverse', 'linear_solve', 'eigenvalues'}:
        allowed |= {'matrix'}
        if operation == 'linear_solve': allowed |= {'rhs'}
    else:
        allowed |= {'expression'}
        if operation in {'differentiate', 'integrate', 'definite_integral', 'solve'}: allowed |= {'variable'}
        if operation == 'definite_integral': allowed |= {'lower', 'upper'}
        if operation == 'solve': allowed |= {'domain'}
    if set(payload) - allowed:
        raise ValueError('Unexpected fields for this operation.')
    precision = payload.get('precision', 50)
    if type(precision) is not int or not 15 <= precision <= 100:
        raise ValueError('Precision must be 15–100 digits.')
    symbols = {}
    denominators = []
    constants = {'pi': sp.pi, 'e': sp.E, 'E': sp.E, 'i': sp.I, 'I': sp.I}
    functions = {'sin': sp.sin, 'cos': sp.cos, 'tan': sp.tan, 'asin': sp.asin,
                 'acos': sp.acos, 'atan': sp.atan, 'sinh': sp.sinh, 'cosh': sp.cosh,
                 'tanh': sp.tanh, 'exp': sp.exp, 'log': sp.log, 'sqrt': sp.sqrt, 'abs': sp.Abs}
    def symbol(name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z]{1,8}', name) or name in constants or name in functions:
            raise ValueError('Use a short variable name, such as x or t.')
        if name not in symbols:
            if len(symbols) >= 8: raise ValueError('At most eight variables are allowed.')
            symbols[name] = sp.Symbol(name)
        return symbols[name]
    def parse(text):
        if not isinstance(text, str) or not 1 <= len(text) <= 512:
            raise ValueError('Each expression must contain 1–512 characters.')
        text = text.strip().replace('^', '**').replace('×', '*').replace('÷', '/').replace('−', '-')
        tree = ast.parse(text, mode='eval')
        if len(list(ast.walk(tree))) > 128: raise ValueError('Expression is too complex.')
        def visit(node, depth=0):
            if depth > 24: raise ValueError('Expression is too deeply nested.')
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                token = ast.get_source_segment(text, node)
                if not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', token):
                    raise ValueError('Use decimal numeric literals.')
                if len(token) > 120: raise ValueError('Numeric literal is too long.')
                exponent = re.search(r'[eE]([+-]?\d+)$', token)
                if exponent and abs(int(exponent[1])) > 100:
                    raise ValueError('Literal exponent exceeds 100.')
                return sp.Rational(token)
            if isinstance(node, ast.Name):
                return constants[node.id] if node.id in constants else symbol(node.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand, depth+1)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                left, right = visit(node.left, depth+1), visit(node.right, depth+1)
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0: raise ValueError('Division by zero.')
                    if right.free_symbols: denominators.append(right)
                    return left / right
                if not right.is_Rational or abs(right) > 100 or right.q > 100:
                    raise ValueError('Power exponents must be rational, bounded by 100, denominator at most 100.')
                if left == 0 and right == 0: raise ValueError('0^0 is not supported.')
                if right < 0 and left.free_symbols: denominators.append(left)
                return left ** right
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in functions and not node.keywords):
                valid_count = len(node.args) == 1 or (node.func.id == 'log' and len(node.args) == 2)
                if not valid_count: raise ValueError('Invalid function argument count.')
                args = [visit(arg, depth+1) for arg in node.args]
                if node.func.id == 'exp' and args[0].is_number and abs(args[0]) > 1000:
                    raise ValueError('Numeric exponential argument exceeds limits.')
                return functions[node.func.id](*args)
            raise ValueError('Unsupported syntax. Use explicit multiplication; no code, attributes, or indexing.')
        result = visit(tree.body)
        if result.has(sp.zoo, sp.nan, sp.oo, -sp.oo): raise ValueError('Expression is singular or non-finite.')
        return result

    notes = ['Angles are in radians. Inputs are dimensionless unless you consistently supply one unit system.',
             'Original expression domain restrictions still apply after simplification.']
    if operation in {'matrix_determinant', 'matrix_inverse', 'linear_solve', 'eigenvalues'}:
        matrix = payload.get('matrix')
        if not isinstance(matrix, list) or not 1 <= len(matrix) <= 6 or any(
            not isinstance(row, list) or len(row) != len(matrix) for row in matrix):
            raise ValueError('Provide a square matrix of 1–6 rows, with string entries.')
        values = [[parse(value) for value in row] for row in matrix]
        if any(value.free_symbols for row in values for value in row):
            raise ValueError('Matrix entries must be numeric.')
        a = sp.Matrix(values)
        if operation in {'matrix_inverse', 'linear_solve'} and a.det() == 0:
            raise ValueError('Matrix is singular; no inverse or unique linear-system solution exists.')
        if operation == 'matrix_determinant': result = a.det()
        elif operation == 'matrix_inverse': result = a.inv()
        elif operation == 'eigenvalues':
            eigen = a.eigenvals()
            return {'status': 'ok', 'operation': operation, 'exact': str(eigen),
                    'numeric': str({str(value.evalf(precision)): count for value, count in eigen.items()}),
                    'notes': notes + ['Dictionary values give algebraic multiplicities.']}
        else:
            rhs = payload.get('rhs')
            if not isinstance(rhs, list) or len(rhs) != len(matrix):
                raise ValueError('Provide one right-hand-side string per matrix row.')
            b = [parse(value) for value in rhs]
            if any(value.free_symbols for value in b): raise ValueError('Right-hand side must be numeric.')
            result = a.inv() * sp.Matrix(b)
    else:
        expression = parse(payload.get('expression'))
        variable = symbol(payload.get('variable', 'x'))
        if operation == 'evaluate':
            if expression.free_symbols: raise ValueError('Evaluation requires numeric values; use simplify for symbols.')
            result = sp.simplify(expression)
        elif operation == 'simplify': result = sp.simplify(expression)
        elif operation == 'differentiate': result = sp.diff(expression, variable)
        elif operation == 'integrate':
            result = sp.integrate(expression, variable)
            notes.append('Indefinite integral: add an arbitrary constant C.')
        elif operation == 'definite_integral':
            lower, upper = parse(payload.get('lower')), parse(payload.get('upper'))
            if lower.free_symbols or upper.free_symbols or lower.is_real is not True or upper.is_real is not True:
                raise ValueError('Integration bounds must be finite real numbers.')
            result = sp.integrate(expression, (variable, lower, upper))
            notes.append('No principal-value interpretation is requested; inspect singularities and convergence.')
        else:
            domain = payload.get('domain', 'real')
            if domain not in {'real', 'complex'}: raise ValueError('Domain must be real or complex.')
            if expression.free_symbols - {variable}: raise ValueError('Single-variable solve only; substitute other variables first.')
            result = sp.solveset(expression, variable, domain=sp.S.Reals if domain == 'real' else sp.S.Complexes)
            for denominator in denominators:
                if denominator.free_symbols - {variable}:
                    raise ValueError('Single-variable domain restrictions only.')
                excluded = sp.solveset(denominator, variable, domain=sp.S.Reals if domain == 'real' else sp.S.Complexes)
                result = sp.Complement(result, excluded)
            notes.append('Solves expression = 0. A ConditionSet indicates a result not fully solved.')
    if denominators:
        notes.append('Excluded denominator zeros: ' + '; '.join(str(value) + ' != 0' for value in denominators))
    if result.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        raise ValueError('Result is divergent, singular, or non-finite.')
    if result.has(sp.Integral, sp.Derivative, sp.ConditionSet):
        return {'status': 'unresolved', 'operation': operation, 'exact': str(result),
                'numeric': None, 'notes': notes + ['No completed solution claimed.']}
    return {'status': 'ok', 'operation': operation, 'exact': str(result),
            'numeric': str(result.evalf(precision)), 'notes': notes,
            'precision_digits': precision}


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS, (512*1024**2, 512*1024**2))
        data = sys.stdin.read(8193)
        if len(data.encode()) > 8192: raise ValueError('Request is too large.')
        result = execute(json.loads(data))
        encoded = json.dumps(result, allow_nan=False)
        if len(encoded.encode()) > 16384: raise ValueError('Result exceeds output limit; simplify the request.')
        print(encoded)
    except ImportError:
        print(json.dumps({'status': 'error', 'error': 'Scientific math dependencies are not installed in the configured worker.'}))
    except Exception as error:
        message = str(error)[:250] if isinstance(error, (ValueError, SyntaxError)) else 'Calculation failed; check domains, matrix rank, and input dimensions.'
        print(json.dumps({'status': 'error', 'error': message}))
