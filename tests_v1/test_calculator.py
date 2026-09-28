import pytest
from orca.calculator import calculate, chat_expression
from orca.runtime import ModelRuntimeGateway
from orca.tools import ReadOnlyToolBroker, ToolRequest


@pytest.mark.parametrize('expression, expected', [
    ('2+3*4', '14'), ('(2+3)*4', '20'), ('0.1+0.2', '0.3'),
    ('12/6', '2'), ('2^10', '1024'), ('2^-3', '0.125'),
    ('sqrt(144)', '12'), ('abs(-3)', '3'), ('15%*200', '30'),
    ('50+10%', '50.1'), ('-10%', '-0.1'), ('1e3+2', '1002'),
    ('2×3−1', '5'), ('-2^2', '-4'), ('(-2)^2', '4'),
])
def test_exact_arithmetic(expression, expected):
    result = calculate(expression)
    assert result['status'] == 'ok'
    assert result['result'] == expected
    assert result['approximate'] is False


@pytest.mark.parametrize('expression', ['1/0', 'sqrt(-1)', '2^1000', '1e999',
    '1e-100*1e-100', '__import__("os").system("whoami")', '(1).__class__',
    '[1,2]', 'True', 'sum([1])', 'sqrt(1,2)', '2**0.5', '9'*513,
    '2%3', '(x:=3)', '0x10', '1_000'])
def test_rejected(expression):
    assert calculate(expression)['status'] == 'error'


def test_rounding():
    assert calculate('1/3')['approximate'] is True
    assert calculate('sqrt(2)')['approximate'] is True


@pytest.mark.parametrize('text', ['What is 2+2?', 'calculate 2+2', '2+2', 'please compute 2+2'])
def test_explicit_chat_math(text):
    assert chat_expression(text) == '2+2'


def test_natural_percent_and_non_math():
    assert calculate(chat_expression('what is 15% of 200?'))['result'] == '30'
    for text in ['explain 2+2', 'do not calculate 2+2', 'open calculator', '2026-09-27', 'Tell me a story']:
        assert chat_expression(text) is None


def test_direct_chat_never_calls_model(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Pure arithmetic must not require model inference')
    monkeypatch.setattr('orca.runtime.bounded_json_transport', forbidden)
    result = ModelRuntimeGateway({'forge_qwen'}).chat(prompt='what is 15% of 200?')
    assert result['mode'] == 'reason'
    assert result['result']['summary'].endswith('= 30')
    assert 'No numeric result' in ModelRuntimeGateway({'forge_qwen'}).chat(prompt='1/0')['result']['uncertainty']


def test_broker_supports_calculation_without_file_or_shell_access():
    broker = ReadOnlyToolBroker({'math.calculate': calculate})
    for bot in ['orca', 'smith', 'quench']:
        result = broker.execute(bot_id=bot, requests=[ToolRequest('math.calculate', {'expression': '4*7'})])
        assert result[0].output['result'] == '28'
    with pytest.raises(PermissionError):
        broker.execute(bot_id='security_gate', requests=[ToolRequest('math.calculate', {'expression': '4*7'})])
