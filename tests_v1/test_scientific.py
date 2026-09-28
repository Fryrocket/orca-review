import json
import subprocess
import pytest
from orca.science_worker import execute
from orca.scientific import scientific_calculate, chat_science_request
from orca.calculator import calculate


@pytest.mark.parametrize('expression,expected', [
    ('(10^40+1)-10^40','1'), ('1/3+1/6','1/2'), ('sin(pi/6)','1/2'),
    ('exp(i*pi)+1','0'), ('log(1000,10)','3'), ('sqrt(-1)','I'),
    ('(1+i)*(1-i)','2'), ('2^(1/2)','sqrt(2)'),
])
def test_exact_scientific(expression,expected):
    assert execute({'operation':'evaluate','expression':expression})['exact']==expected


def test_exact_basic_cancellation_and_fractions():
    assert calculate('(1e40+1)-1e40')['result']=='1'
    assert calculate('(1e100+1)-1e100')['result']=='1'
    assert calculate('1/3+1/6')['exact']=='1/2'
    assert calculate('2^100')['result']==str(2**100)
    assert not calculate('2^100')['approximate']


def test_calculus_and_equations():
    assert execute({'operation':'differentiate','expression':'x^3','variable':'x'})['exact']=='3*x**2'
    result=execute({'operation':'integrate','expression':'x^2','variable':'x'})
    assert result['exact']=='x**3/3'
    assert any('constant C' in note for note in result['notes'])
    assert execute({'operation':'definite_integral','expression':'x^2','lower':'0','upper':'3'})['exact']=='9'
    assert execute({'operation':'solve','expression':'x^2-2'})['exact']=='{-sqrt(2), sqrt(2)}'
    assert execute({'operation':'solve','expression':'x^2+1','domain':'complex'})['exact']=='{-I, I}'


def test_domain_is_not_lost_when_division_cancels():
    result=execute({'operation':'solve','expression':'(x^2-1)/(x-1)-2'})
    assert result['exact']=='EmptySet'
    assert any('x - 1 != 0' in note for note in result['notes'])
    result=execute({'operation':'simplify','expression':'x/x'})
    assert result['exact']=='1'
    assert any('x != 0' in note for note in result['notes'])


def test_matrices():
    matrix=[['2','1'],['1','-1']]
    assert execute({'operation':'matrix_determinant','matrix':matrix})['exact']=='-3'
    assert execute({'operation':'linear_solve','matrix':matrix,'rhs':['5','1']})['exact']=='Matrix([[2], [1]])'
    result=execute({'operation':'eigenvalues','matrix':[['2','0'],['0','3']]})
    assert '2: 1' in result['exact'] and '3: 1' in result['exact']


@pytest.mark.parametrize('expression', [
    '__import__("os")', '(1).__class__', 'sin.__globals__', 'open("/etc/passwd")',
    '[1,2]', '(x:=3)', '1e1000000', '2^10000', 'sqrt(x,1)', 'x[0]', '0^0',
])
def test_forbidden_input(expression):
    with pytest.raises((ValueError,SyntaxError)):
        execute({'operation':'evaluate','expression':expression})


def test_worker_boundary_and_error_cases():
    assert scientific_calculate(operation='evaluate',expression='sin(pi/6)')['exact']=='1/2'
    assert scientific_calculate(operation='matrix_inverse',matrix=[['1','2'],['2','4']])['status']=='error'
    assert scientific_calculate(operation='evaluate',expression='1/0')['status']=='error'
    assert scientific_calculate(operation='definite_integral',expression='1/x',lower='-1',upper='1')['status']=='error'
    assert scientific_calculate(operation='evaluate',expression='2',precision=101)['status']=='error'
    assert scientific_calculate(operation='evaluate',expression='2',command='id')['status']=='error'


def test_worker_timeout_is_reported_and_slot_released(monkeypatch):
    def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('worker',8)
    monkeypatch.setattr('orca.scientific.subprocess.run',timeout)
    for _ in range(3):
        assert 'time limit' in scientific_calculate(operation='evaluate',expression='2')['error']


def test_worker_request_limit_and_commands():
    assert scientific_calculate(operation='evaluate',expression='1'*9000)['status']=='error'
    assert chat_science_request('/diff x^3')=={'operation':'differentiate','expression':'x^3','variable':'x'}
    assert chat_science_request('do not /diff x^3') is None
def test_model_schema_excludes_irrelevant_fields():
    from orca.scientific import scientific_argument_schema
    branches = {item['properties']['operation']['const']: item
                for item in scientific_argument_schema()['anyOf']}
    assert set(branches['evaluate']['properties']) == {'operation','precision','expression'}
    assert set(branches['definite_integral']['properties']) == {'operation','precision','expression','variable','lower','upper'}
    assert set(branches['solve']['properties']) == {'operation','precision','expression','variable','domain'}
    for branch in branches.values():
        assert 'precision' not in branch['required']
        assert set(branch['required']) <= set(branch['properties'])
        assert branch['additionalProperties'] is False
