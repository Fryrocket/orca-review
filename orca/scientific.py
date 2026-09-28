"""Bounded subprocess access to the optional free symbolic mathematics runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import re

_slots = threading.BoundedSemaphore(2)


def scientific_argument_schema():
    """Constrain model plans to exactly the worker's operation-specific inputs."""
    variants = []
    for operation in ('evaluate', 'simplify', 'differentiate', 'integrate', 'definite_integral',
                      'solve', 'matrix_determinant', 'matrix_inverse', 'linear_solve', 'eigenvalues'):
        properties = {'operation': {'type': 'string', 'const': operation},
                      'precision': {'type': 'integer', 'minimum': 15, 'maximum': 100}}
        required = ['operation']
        if operation in {'matrix_determinant', 'matrix_inverse', 'linear_solve', 'eigenvalues'}:
            properties['matrix'] = {'type': 'array', 'minItems': 1, 'maxItems': 6,
                'items': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'items': {'type': 'string'}}}
            required.append('matrix')
            if operation == 'linear_solve':
                properties['rhs'] = {'type': 'array', 'minItems': 1, 'maxItems': 6, 'items': {'type': 'string'}}
                required.append('rhs')
        else:
            properties['expression'] = {'type': 'string'}
            required.append('expression')
            if operation in {'differentiate', 'integrate', 'definite_integral', 'solve'}:
                properties['variable'] = {'type': 'string'}
            if operation == 'definite_integral':
                properties.update(lower={'type': 'string'}, upper={'type': 'string'})
                required += ['lower', 'upper']
            if operation == 'solve':
                properties['domain'] = {'type': 'string', 'enum': ['real', 'complex']}
        variants.append({'type': 'object', 'properties': properties,
                         'required': required, 'additionalProperties': False})
    return {'anyOf': variants}


def chat_science_request(prompt):
    match = re.fullmatch(r'/(math|simplify|diff|integrate|solve)\s+(.+)', prompt.strip(), re.S)
    if not match:
        return None
    operations = {'math':'evaluate','simplify':'simplify','diff':'differentiate','integrate':'integrate','solve':'solve'}
    result = {'operation':operations[match[1]], 'expression':match[2].strip()}
    if match[1] in {'diff','integrate','solve'}:
        result['variable'] = 'x'
    return result


def scientific_calculate(**request):
    try:
        encoded = json.dumps(request, allow_nan=False)
    except (ValueError, TypeError):
        return {'status': 'error', 'error': 'Request must contain finite JSON values.'}
    if len(encoded.encode()) > 8192:
        return {'status': 'error', 'error': 'Scientific request exceeds 8 KB.'}
    if not _slots.acquire(blocking=False):
        return {'status': 'error', 'error': 'Two scientific calculations are already running. Try again shortly.'}
    try:
        interpreter = os.environ.get('ORCA_MATH_PYTHON', sys.executable)
        if not os.path.isabs(interpreter):
            return {'status': 'error', 'error': 'Math interpreter must be an absolute configured path.'}
        worker = str(Path(__file__).with_name('science_worker.py').resolve())
        result = subprocess.run([interpreter, '-I', worker], input=encoded, text=True,
            capture_output=True, timeout=8, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
            cwd=str(Path(worker).parent), start_new_session=True)
        if result.returncode or len(result.stdout.encode()) > 16384:
            return {'status': 'error', 'error': 'Calculation exceeded worker limits or could not complete.'}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'error': 'Calculation exceeded the eight-second time limit.'}
    except (OSError, ValueError):
        return {'status': 'error', 'error': 'Scientific worker is unavailable or returned an invalid result.'}
    finally:
        _slots.release()
