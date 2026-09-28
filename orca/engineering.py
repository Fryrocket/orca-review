"""Deterministic first-order engineering models, explicit SI inputs and assumptions."""
import math
import re
from decimal import Decimal


def field(key, label, unit, example, minimum=0, zero=False):
    return {'key': key, 'label': label, 'unit': unit, 'example': example,
            'minimum': minimum, 'allow_zero': zero}


def spec(title, category, fields, formula, assumptions):
    return {'title': title, 'category': category, 'fields': fields,
            'formula': formula, 'assumptions': assumptions}


CATALOG = {
 'divider': spec('Loaded voltage divider', 'Electronics', [field('vin','Input voltage','V',12),field('r1','Upper resistance','Ω',10000),field('r2','Lower resistance','Ω',10000),field('load','Load resistance','Ω',100000)],
   'Rb = R2 || Rload; Vout = Vin·Rb/(R1+Rb)', 'DC resistive load, ideal source. Enter the actual load; resistor tolerance and temperature effects are excluded.'),
 'rc_filter': spec('RC low-pass filter', 'Electronics', [field('r','Resistance','Ω',1000),field('c','Capacitance','F',1e-6),field('f','Frequency','Hz',1000,zero=True)],
   'τ = RC; fc = 1/(2πRC); |H| = 1/√(1+(2πfRC)²)', 'Ideal unloaded first-order low-pass. Phase in degrees; component ESR, source and load impedance excluded.'),
 'rlc_series': spec('Series RLC impedance', 'Electronics', [field('r','Series resistance','Ω',10),field('l','Inductance','H',.01),field('c','Capacitance','F',1e-6),field('f','Frequency','Hz',1000)],
   'Z = R + j(ωL−1/(ωC)); f0 = 1/(2π√LC); Q = √(L/C)/R', 'Sinusoidal steady state, ideal lumped elements. Q uses total series resistance; no saturation or parasitics.'),
 'led_resistor': spec('LED series resistor', 'Electronics', [field('vs','Supply voltage','V',5),field('vf','LED forward voltage','V',2),field('current','Target current','A',.01)],
   'R = (Vs−Vf)/I; PR = (Vs−Vf)I', 'Nominal operating point only. Vf must come from the LED specification. Check tolerances and thermal derating; computed power is not a selected resistor rating.'),
 'opamp_gain': spec('Ideal op-amp gains', 'Electronics', [field('rf','Feedback resistance','Ω',10000),field('rin','Input / ground resistance','Ω',1000)],
   'Inverting gain = −Rf/Rin; non-inverting gain = 1+Rf/Rin', 'Ideal negative feedback, linear operation. Does not check supply rails, common-mode range, bandwidth, slew rate, stability, or output loading.'),
 'capacitor_energy': spec('Capacitor energy and charge', 'Electronics', [field('c','Capacitance','F',.001),field('v','Voltage magnitude','V',24,zero=True)],
   'E = ½CV²; Q = CV', 'Ideal capacitor at stated voltage. Stored energy is not a discharge procedure or a safe-touch determination.'),
 'conductor': spec('DC conductor loss', 'Electronics', [field('rho','Resistivity at operating temperature','Ω·m',1.68e-8),field('length','Total current-path length','m',2),field('area','Cross-sectional area','m²',1e-6),field('current','Current magnitude','A',2,zero=True)],
   'R = ρL/A; Vdrop = IR; Ploss = I²R', 'Uniform conductor, DC. Supply total loop length when applicable. Excludes connectors, skin effect and thermal feedback; not an ampacity rating.'),
 'buck_ideal': spec('Ideal buck converter', 'Electronics', [field('vin','Input voltage','V',24),field('vout','Output voltage','V',12),field('l','Inductance','H',.0001),field('fs','Switching frequency','Hz',100000),field('iout','Output current','A',2)],
   'D = Vout/Vin; ΔIL = (Vin−Vout)D/(Lfs); Ipeak = Iout+ΔIL/2', 'Ideal continuous-conduction model. Boundary check included; excludes losses, control dynamics, current limits, saturation and transients.'),
 'beam_cantilever': spec('Cantilever: end point load', 'Mechanical', [field('force','End load magnitude','N',100),field('length','Beam length','m',.5),field('young','Young modulus','Pa',200e9),field('inertia','Second moment of area','m⁴',1e-8),field('c','Neutral axis to extreme fiber','m',.01)],
   'δ = FL³/(3EI); Mmax = FL; σmax = Mmax·c/I', 'Uniform Euler–Bernoulli beam, fixed end, transverse end load, linear elastic small deflection. Shear deformation, buckling, stress concentrations and connection flexibility excluded.'),
 'beam_supported': spec('Simply supported: center load', 'Mechanical', [field('force','Center load magnitude','N',100),field('length','Span','m',1),field('young','Young modulus','Pa',200e9),field('inertia','Second moment of area','m⁴',1e-8),field('c','Neutral axis to extreme fiber','m',.01)],
   'δmax = FL³/(48EI); Mmax = FL/4; σmax = Mmax·c/I', 'Uniform Euler–Bernoulli beam, simple supports, centered point load, linear elastic small deflection. No buckling or stress concentrations.'),
 'rectangular_section': spec('Rectangular section properties', 'Mechanical', [field('width','Width','m',.02),field('height','Height in bending direction','m',.04)],
   'A = bh; I = bh³/12; Z = bh²/6', 'Solid rectangle; bending about centroidal axis parallel to width. Orientation matters.'),
 'shaft_torsion': spec('Solid circular shaft torsion', 'Mechanical', [field('torque','Torque magnitude','N·m',10),field('diameter','Shaft diameter','m',.02),field('length','Shaft length','m',.5),field('shear','Shear modulus','Pa',80e9)],
   'J = πd⁴/32; τmax = 16T/(πd³); θ = TL/(JG)', 'Solid circular uniform shaft, linear elastic pure torsion. No keyways, combined loads, fatigue, or stress concentrations.'),
 'rotary_power': spec('Torque, speed and power', 'Mechanical', [field('torque','Torque magnitude','N·m',10,zero=True),field('rpm','Speed','rpm',1500,zero=True),field('efficiency','Overall efficiency','fraction',.9)],
   'ω = 2πn/60; Pin = Tω; Pout = ηPin', 'Steady-state shaft input torque and speed. Efficiency must be supplied; startup and transient torque are excluded.'),
 'gear_pair': spec('Ideal gear pair with efficiency', 'Mechanical', [field('driver','Driver teeth','count',20),field('driven','Driven teeth','count',60),field('rpm','Input speed','rpm',1500),field('torque','Input torque','N·m',10),field('efficiency','Mesh efficiency','fraction',.95)],
   'ratio = Ndriven/Ndriver; nout = nin/ratio; Tout = Tin·ratio·η', 'Speed and torque magnitudes only. Requires compatible gears; does not check tooth stress, undercut, lubrication, or rotation direction.'),
 'spring': spec('Close-coiled compression spring', 'Mechanical', [field('wire','Wire diameter','m',.002),field('mean_diameter','Mean coil diameter','m',.016),field('coils','Active coils','count',8),field('shear','Shear modulus','Pa',79e9),field('force','Axial load','N',20)],
   'k = Gd⁴/(8D³n); δ = F/k; τ = Kw·8FD/(πd³)', 'Round-wire close-coiled spring, linear elastic; Wahl stress correction. Spring index limited to 4–12. Does not check solid height, end conditions, buckling, yield, fatigue, or available travel.'),
 'thermal_wall': spec('1D wall conduction', 'Mechanical', [field('k','Thermal conductivity','W/(m·K)',.2),field('area','Area','m²',.1),field('thickness','Thickness','m',.01),field('delta_t','Temperature difference magnitude','K',20,zero=True)],
   'Rth = L/(kA); Qdot = ΔT/Rth', 'Steady one-dimensional conduction through a uniform wall. Constant material properties; convection, radiation and contact resistance excluded.'),
}


def engineering_catalog():
    return CATALOG


def engineering_chat_calculate(tool=None, values=None, **extra):
    """Quoted decimals preserve exponents in grammar-constrained model plans."""
    if extra or not isinstance(values, dict) or any(
        not isinstance(value, str) or len(value) > 120 or not re.fullmatch(
            r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value)
        for value in values.values()
    ):
        return {'status': 'error', 'error': 'Chat engineering inputs must be quoted decimal SI strings, preserving every exponent (for example "1e-8"). No calculation was performed.'}
    for value in values.values():
        exponent = re.search(r'[eE]([+-]?\d+)$', value)
        if exponent and abs(int(exponent[1])) > 300:
            return {'status': 'error', 'error': 'Engineering decimal exponent must be between -300 and 300.'}
    converted = {key: float(value) for key, value in values.items()}
    if any(not math.isfinite(converted[key]) or (converted[key] == 0 and Decimal(value) != 0)
           for key, value in values.items()):
        return {'status': 'error', 'error': 'Engineering input overflow or underflow; revise the magnitude or units.'}
    return engineering_calculate(tool, converted)


def engineering_chat_summary(output):
    """Never ask a language model to reinterpret a computed engineering result."""
    if output.get('status') != 'ok':
        return output.get('error', 'Engineering calculation did not complete.')
    fields = CATALOG[output['tool']]['fields']
    lines = [output['title'], 'Check these interpreted SI inputs against your design:']
    lines += [f"{field['label']}: {output['inputs'][field['key']]:.12g} {field['unit']}" for field in fields]
    lines += ['', 'Computed results:']
    lines += [f"{key.replace('_', ' ')}: {value:.12g}" for key, value in output['outputs'].items()]
    lines += ['', output['formula'], output['assumptions'], *output['warnings'], output['notice']]
    return '\n'.join(lines)


def engineering_calculate(tool, values):
    if not isinstance(tool, str) or tool not in CATALOG:
        return {'status': 'error', 'error': 'Unknown engineering calculator.'}
    spec = CATALOG[tool]
    if not isinstance(values, dict) or set(values) != {item['key'] for item in spec['fields']}:
        return {'status': 'error', 'error': 'Supply exactly the labeled input fields; no missing values or implicit defaults.'}
    v = {}
    try:
        for item in spec['fields']:
            value = values[item['key']]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{item['label']} must be a finite number in {item['unit']}.")
            if value < item['minimum'] or (value == item['minimum'] and not item['allow_zero']):
                raise ValueError(f"{item['label']} must be {'at least' if item['allow_zero'] else 'greater than'} {item['minimum']}.")
            if value > 1e300: raise ValueError('Input magnitude is too large.')
            v[item['key']] = float(value)
        if 'efficiency' in v and v['efficiency'] > 1: raise ValueError('Efficiency must be greater than 0 and no greater than 1.')
        warnings = []
        def out(**items): return items
        if tool == 'divider':
            rb = v['r2']*v['load']/(v['r2']+v['load'])
            current = v['vin']/(v['r1']+rb); voltage = current*rb
            result = out(vout_V=voltage, source_current_A=current, r1_power_W=current**2*v['r1'], r2_power_W=voltage**2/v['r2'], load_power_W=voltage**2/v['load'])
        elif tool == 'rc_filter':
            tau = v['r']*v['c']; ratio = 2*math.pi*v['f']*tau
            result = out(time_constant_s=tau, cutoff_Hz=1/(2*math.pi*tau), gain_magnitude=1/math.hypot(1,ratio), phase_deg=-math.degrees(math.atan(ratio)))
        elif tool == 'rlc_series':
            omega=2*math.pi*v['f']; reactance=omega*v['l']-1/(omega*v['c'])
            result=out(resistance_ohm=v['r'], reactance_ohm=reactance, impedance_magnitude_ohm=math.hypot(v['r'],reactance), phase_deg=math.degrees(math.atan2(reactance,v['r'])), resonance_Hz=1/(2*math.pi*math.sqrt(v['l']*v['c'])), series_Q=math.sqrt(v['l']/v['c'])/v['r'])
        elif tool == 'led_resistor':
            if v['vs'] <= v['vf']: raise ValueError('Supply must exceed the stated LED forward voltage.')
            result=out(resistance_ohm=(v['vs']-v['vf'])/v['current'], resistor_dissipation_W=(v['vs']-v['vf'])*v['current'], led_dissipation_W=v['vf']*v['current'])
        elif tool == 'opamp_gain': result=out(inverting_gain=-v['rf']/v['rin'], noninverting_gain=1+v['rf']/v['rin'])
        elif tool == 'capacitor_energy': result=out(energy_J=.5*v['c']*v['v']**2, charge_C=v['c']*v['v'])
        elif tool == 'conductor':
            r=v['rho']*v['length']/v['area']; result=out(resistance_ohm=r, voltage_drop_V=v['current']*r, power_loss_W=v['current']**2*r)
        elif tool == 'buck_ideal':
            if v['vout'] >= v['vin']: raise ValueError('Buck output must be below input voltage.')
            duty=v['vout']/v['vin']; ripple=(v['vin']-v['vout'])*duty/(v['l']*v['fs'])
            if v['iout'] <= ripple/2: raise ValueError('Inputs are at or below the CCM boundary; this continuous-conduction model is not applicable.')
            result=out(duty_fraction=duty, inductor_ripple_peak_to_peak_A=ripple, inductor_peak_A=v['iout']+ripple/2, inductor_valley_A=v['iout']-ripple/2)
        elif tool in {'beam_cantilever','beam_supported'}:
            cantilever=tool=='beam_cantilever'; deflection=v['force']*v['length']**3/((3 if cantilever else 48)*v['young']*v['inertia']); moment=v['force']*v['length']/(1 if cantilever else 4)
            if deflection/v['length'] > .05: warnings.append('Deflection exceeds 5% of span; small-deflection theory may be invalid. This is a model-validity warning, not a safety criterion.')
            result=out(max_deflection_m=deflection, max_moment_Nm=moment, max_bending_stress_Pa=moment*v['c']/v['inertia'])
        elif tool=='rectangular_section': result=out(area_m2=v['width']*v['height'], second_moment_m4=v['width']*v['height']**3/12, section_modulus_m3=v['width']*v['height']**2/6)
        elif tool=='shaft_torsion':
            j=math.pi*v['diameter']**4/32; angle=v['torque']*v['length']/(j*v['shear'])
            result=out(polar_moment_m4=j, max_shear_stress_Pa=16*v['torque']/(math.pi*v['diameter']**3), twist_rad=angle, twist_deg=math.degrees(angle))
        elif tool=='rotary_power':
            omega=2*math.pi*v['rpm']/60; result=out(angular_speed_rad_s=omega, input_power_W=v['torque']*omega, output_power_W=v['torque']*omega*v['efficiency'])
        elif tool=='gear_pair':
            if any(v[key] != int(v[key]) for key in ['driver','driven']): raise ValueError('Gear tooth counts must be integers.')
            ratio=v['driven']/v['driver']; result=out(ratio=ratio, output_speed_rpm=v['rpm']/ratio, output_torque_Nm=v['torque']*ratio*v['efficiency'])
        elif tool=='spring':
            index=v['mean_diameter']/v['wire']
            if not 4 <= index <= 12: raise ValueError('This spring approximation requires a spring index D/d between 4 and 12.')
            k=v['shear']*v['wire']**4/(8*v['mean_diameter']**3*v['coils']); wahl=(4*index-1)/(4*index-4)+.615/index
            result=out(spring_index=index, stiffness_N_per_m=k, deflection_m=v['force']/k, corrected_shear_stress_Pa=wahl*8*v['force']*v['mean_diameter']/(math.pi*v['wire']**3))
        else:
            resistance=v['thickness']/(v['k']*v['area']); result=out(thermal_resistance_K_per_W=resistance, heat_flow_W=v['delta_t']/resistance)
        if not all(math.isfinite(value) for value in result.values()): raise ValueError('Numeric overflow; revise magnitudes or units.')
        return {'status':'ok','tool':tool,'title':spec['title'],'inputs':v,'outputs':result,
                'formula':spec['formula'],'assumptions':spec['assumptions'],'warnings':warnings,
                'notice':'First-order model, not a safety certification or component rating. Check units, tolerances, material data and applicable standards.'}
    except (ValueError, OverflowError, ZeroDivisionError) as error:
        return {'status':'error','error':str(error) or 'Inputs fall outside the numeric model.'}
