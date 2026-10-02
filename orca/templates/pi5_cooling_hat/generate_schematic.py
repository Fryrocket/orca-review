from skidl import *

set_default_tool(KICAD10)

def part(lib, name, ref, value, footprint):
    return Part(lib, name, ref=ref, value=value, footprint=footprint)

j1 = part('Connector_Generic', 'Conn_02x20_Odd_Even', 'J1', 'Raspberry Pi 5 GPIO',
          'Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical')
j2 = part('Connector_Generic', 'Conn_01x04', 'J2', '5V 4-wire PWM fan',
          'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical')
f1 = part('Device', 'Polyfuse', 'F1', '0.50A hold',
          'Fuse:Fuse_1206_3216Metric')
q1 = part('Transistor_FET', 'Q_NMOS_GSD', 'Q1', '2N7002K',
          'Package_TO_SOT_SMD:SOT-23')
r_gate = part('Device', 'R', 'R1', '100R', 'Resistor_SMD:R_0603_1608Metric')
r_pd = part('Device', 'R', 'R2', '100k', 'Resistor_SMD:R_0603_1608Metric')
r_tach = part('Device', 'R', 'R3', '10k', 'Resistor_SMD:R_0603_1608Metric')
r_tach_series = part('Device', 'R', 'R4', '1k', 'Resistor_SMD:R_0603_1608Metric')
d1 = part('Device', 'D_TVS', 'D1', 'SMBJ5.0A', 'Diode_SMD:D_SMB')
c1 = part('Device', 'C_Polarized', 'C1', '100uF 10V', 'Capacitor_SMD:CP_Elec_6.3x5.8')
c2 = part('Device', 'C', 'C2', '100nF', 'Capacitor_SMD:C_0603_1608Metric')
tp5 = part('Connector', 'TestPoint', 'TP1', '5V_FUSED', 'TestPoint:TestPoint_Plated_Hole_D2.0mm')
tpg = part('Connector', 'TestPoint', 'TP2', 'GND', 'TestPoint:TestPoint_Plated_Hole_D2.0mm')
tpp = part('Connector', 'TestPoint', 'TP3', 'FAN_PWM_OD', 'TestPoint:TestPoint_Plated_Hole_D2.0mm')
tpt = part('Connector', 'TestPoint', 'TP4', 'FAN_TACH_3V3', 'TestPoint:TestPoint_Plated_Hole_D2.0mm')

n_5v = Net('5V_IN')
n_5vf = Net('5V_FUSED')
n_3v3 = Net('3V3')
n_gnd = Net('GND')
n_gpio18 = Net('GPIO18_PWM')
n_gate = Net('PWM_GATE')
n_pwm = Net('FAN_PWM_OD')
n_tach = Net('FAN_TACH')
n_gpio17 = Net('GPIO17_TACH')

n_5v += j1[2], j1[4], f1[1]
n_5vf += f1[2], j2[2], d1[2], c1[1], c2[1], tp5[1]
n_3v3 += j1[1], j1[17], r_tach[1]
n_gnd += j1[6], j1[9], j1[14], j1[20], j1[25], j1[30], j1[34], j1[39]
n_gnd += j2[1], d1[1], c1[2], c2[2], q1['S'], r_pd[2], tpg[1]
n_gpio18 += j1[12], r_gate[1]
n_gate += r_gate[2], q1['G'], r_pd[1]
n_pwm += q1['D'], j2[4], tpp[1]
n_tach += j2[3], r_tach[2], r_tach_series[1], tpt[1]
n_gpio17 += r_tach_series[2], j1[11]

# Mark the Raspberry Pi rails as the board's power sources for ERC.
p5 = Part('power', 'PWR_FLAG'); p5[1] += n_5v
p3 = Part('power', 'PWR_FLAG'); p3[1] += n_3v3
pg = Part('power', 'PWR_FLAG'); pg[1] += n_gnd

unused = [3, 5, 7, 8, 10, 13, 15, 16, 18, 19, 21, 22, 23, 24,
          26, 27, 28, 29, 31, 32, 33, 35, 36, 37, 38, 40]
NC += j1[unused]

ERC()
generate_schematic(tool=KICAD10, auto_stub=True)
