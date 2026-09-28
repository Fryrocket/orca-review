import math
import pytest
from orca.engineering import CATALOG,engineering_calculate


def example(tool, **override):
    return {**{f['key']:f['example'] for f in CATALOG[tool]['fields']},**override}


@pytest.mark.parametrize('tool',list(CATALOG))
def test_every_model_has_working_documented_example(tool):
    result=engineering_calculate(tool,example(tool))
    assert result['status']=='ok',result
    assert result['assumptions'] and result['formula'] and result['notice']
    assert all(math.isfinite(value) for value in result['outputs'].values())


@pytest.mark.parametrize('tool,output,expected', [
    ('divider','vout_V',40/7), ('rc_filter','cutoff_Hz',1000/(2*math.pi)),
    ('rlc_series','series_Q',10), ('led_resistor','resistance_ohm',300),
    ('opamp_gain','inverting_gain',-10), ('capacitor_energy','energy_J',.288),
    ('conductor','power_loss_W',.1344), ('buck_ideal','inductor_ripple_peak_to_peak_A',.6),
    ('beam_cantilever','max_bending_stress_Pa',50e6), ('beam_supported','max_deflection_m',1/960),
    ('rectangular_section','area_m2',.0008), ('shaft_torsion','max_shear_stress_Pa',20e6/math.pi),
    ('rotary_power','input_power_W',500*math.pi), ('gear_pair','output_speed_rpm',500),
    ('spring','stiffness_N_per_m',4821.77734375), ('thermal_wall','heat_flow_W',40),
])
def test_reference_results(tool,output,expected):
    assert engineering_calculate(tool,example(tool))['outputs'][output]==pytest.approx(expected,rel=1e-12)


def test_beam_scaling_and_buck_applicability():
    one=engineering_calculate('beam_cantilever',example('beam_cantilever'))['outputs']
    two=engineering_calculate('beam_cantilever',example('beam_cantilever',length=1))['outputs']
    assert two['max_deflection_m']==pytest.approx(8*one['max_deflection_m'])
    assert engineering_calculate('buck_ideal',example('buck_ideal',iout=.1))['status']=='error'


@pytest.mark.parametrize('value',[None,True,'10',float('nan'),float('inf'),-1,0])
def test_invalid_values(value):
    assert engineering_calculate('rc_filter',example('rc_filter',r=value))['status']=='error'


def test_missing_inputs_and_invalid_models():
    assert engineering_calculate('rc_filter',{})['status']=='error'
    assert engineering_calculate('rc_filter',{**example('rc_filter'),'extra':1})['status']=='error'
    assert engineering_calculate('unknown',{})['status']=='error'
    assert engineering_calculate('gear_pair',example('gear_pair',efficiency=1.1))['status']=='error'
    assert engineering_calculate('gear_pair',example('gear_pair',driver=20.5))['status']=='error'
    assert engineering_calculate('spring',example('spring',mean_diameter=.004))['status']=='error'


def test_chat_exponents_and_deterministic_summary():
    from orca.engineering import engineering_chat_calculate, engineering_chat_summary
    values={'force':'100','length':'0.5','young':'200e9','inertia':'1e-8','c':'0.01'}
    result=engineering_chat_calculate('beam_cantilever',values)
    assert result['outputs']['max_bending_stress_Pa']==50e6
    assert result['outputs']['max_deflection_m']==pytest.approx(1/480)
    assert '1e-08 m⁴' in engineering_chat_summary(result)
    assert engineering_chat_calculate('beam_cantilever',{**values,'inertia':1})['status']=='error'
    assert engineering_chat_calculate('beam_cantilever',{**values,'inertia':'1e-8; bad'})['status']=='error'
    assert engineering_chat_calculate('capacitor_energy',{'c':'1','v':'1e-1000'})['status']=='error'
    assert engineering_chat_calculate('capacitor_energy',{'c':'1','v':'1e1000'})['status']=='error'
    assert engineering_chat_calculate(r='1')['status']=='error'
    for bad in [' 1','1 ','e10','1e','nan','inf','1e-'+('9'*100)]:
        assert engineering_chat_calculate('capacitor_energy',{'c':'1','v':bad})['status']=='error'
