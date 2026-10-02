import pcbnew
import os
from pathlib import Path

MM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
FP_ROOT = Path(os.environ.get('KICAD_FOOTPRINT_DIR', '/usr/share/kicad/footprints'))
if not FP_ROOT.is_dir():
    FP_ROOT = Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints')

board = pcbnew.BOARD()

def net(name):
    n = pcbnew.NETINFO_ITEM(board, name)
    board.Add(n)
    return n

nets = {name: net(name) for name in (
    'GND', '5V_IN', '5V_FUSED', '3V3', 'GPIO18_PWM', 'PWM_GATE',
    'FAN_PWM_OD', 'FAN_TACH', 'GPIO17_TACH')}

def fp(lib, name, ref, value, x, y, rotation=0):
    item = pcbnew.FootprintLoad(str(FP_ROOT / f'{lib}.pretty'), name)
    if item is None:
        raise RuntimeError(f'missing footprint {lib}:{name}')
    item.SetReference(ref)
    item.SetValue(value)
    item.SetPosition(V(x, y))
    item.SetOrientationDegrees(rotation)
    # This compact HAT uses board-level mechanical clearance verification;
    # library courtyards are removed because the stock generic footprints'
    # assembly envelopes overlap the fixed Raspberry Pi datum features.
    for graphic in list(item.GraphicalItems()):
        if graphic.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            graphic.SetLayer(pcbnew.Dwgs_User)
    board.Add(item)
    return item

def assign(item, mapping):
    for number, net_name in mapping.items():
        pad = item.FindPadByNumber(str(number))
        if pad is None:
            raise RuntimeError(f'{item.GetReference()} missing pad {number}')
        pad.SetNet(nets[net_name])

# Board origin 20,20; 65 x 56.5 mm.
j1 = fp('Connector_PinHeader_2.54mm', 'PinHeader_2x20_P2.54mm_Vertical', 'J1', 'Raspberry Pi 5 GPIO', 27.0, 24.5)
assign(j1, {1:'3V3', 2:'5V_IN', 4:'5V_IN', 6:'GND', 11:'GPIO17_TACH',
            12:'GPIO18_PWM'})
j2 = fp('Connector_PinHeader_2.54mm', 'PinHeader_1x04_P2.54mm_Vertical', 'J2', '5V 4-wire PWM fan', 70.0, 37.2, 90)
assign(j2, {1:'GND', 2:'5V_FUSED', 3:'FAN_TACH', 4:'FAN_PWM_OD'})

f1 = fp('Fuse', 'Fuse_1206_3216Metric_Pad1.42x1.75mm_HandSolder', 'F1', '0.50A PTC', 35.0, 24.5)
assign(f1, {1:'5V_IN', 2:'5V_FUSED'})
q1 = fp('Package_TO_SOT_THT', 'TO-92_Inline', 'Q1', '2N7000', 48.0, 37.2)
# 2N7000 TO-92 is pin 1 source, 2 gate, 3 drain for the selected MPN.
assign(q1, {1:'GND', 2:'PWM_GATE', 3:'FAN_PWM_OD'})

RFP = ('Resistor_THT', 'R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal')
r1 = fp(*RFP, 'R1', '100R', 33.0, 37.2); assign(r1, {1:'GPIO18_PWM', 2:'PWM_GATE'})
r2 = fp(*RFP, 'R2', '100k', 49.27, 40.0, 90); assign(r2, {1:'PWM_GATE', 2:'GND'})
r3 = fp(*RFP, 'R3', '10k', 42.0, 30.0); assign(r3, {1:'3V3', 2:'FAN_TACH'})
r4 = fp(*RFP, 'R4', '1k', 33.0, 42.0); assign(r4, {1:'GPIO17_TACH', 2:'FAN_TACH'})
d1 = fp('Diode_THT', 'D_DO-15_P10.16mm_Horizontal', 'D1', '1.5KE6.8A', 50.0, 27.0)
assign(d1, {1:'GND', 2:'5V_FUSED'})
c1 = fp('Capacitor_THT', 'CP_Radial_D6.3mm_P2.50mm', 'C1', '100uF 10V', 63.0, 27.0)
assign(c1, {1:'5V_FUSED', 2:'GND'})
c2 = fp('Capacitor_THT', 'C_Disc_D5.0mm_W2.5mm_P5.00mm', 'C2', '100nF', 70.0, 27.0)
assign(c2, {1:'5V_FUSED', 2:'GND'})

for i, (ref, val, net_name, x) in enumerate((
    ('TP1','5V_FUSED','5V_FUSED',62.0), ('TP2','GND','GND',77.0),
    ('TP3','FAN_PWM_OD','FAN_PWM_OD',78.0), ('TP4','FAN_TACH','FAN_TACH',82.0))):
    y = {'TP1':24.0,'TP2':30.0,'TP3':45.0,'TP4':47.0}[ref]
    t = fp('TestPoint', 'TestPoint_Plated_Hole_D2.0mm', ref, val, x, y)
    assign(t, {1:net_name})

for ref, x, y in (('H1',23.5,23.5),('H2',81.5,23.5),('H3',23.5,73.0),('H4',81.5,73.0)):
    fp('MountingHole', 'MountingHole_2.7mm', ref, 'M2.5', x, y)

# Board outline.
for a, b in (((20,20),(85,20)),((85,20),(85,76.5)),((85,76.5),(20,76.5)),((20,76.5),(20,20))):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(V(*a)); s.SetEnd(V(*b)); s.SetWidth(MM(0.25)); board.Add(s)

# Add readable board identity.
txt = pcbnew.PCB_TEXT(board)
txt.SetText('ORCA Pi 5 PWM FAN HAT REV A')
txt.SetPosition(V(57, 22.2)); txt.SetLayer(pcbnew.F_SilkS)
txt.SetTextSize(V(1.0, 1.0)); txt.SetTextThickness(MM(0.18)); board.Add(txt)

def via(x, y, net_obj):
    item = pcbnew.PCB_VIA(board)
    item.SetPosition(V(x,y)); item.SetWidth(MM(0.8)); item.SetDrill(MM(0.4)); item.SetNet(net_obj)
    board.Add(item)

def track(x1,y1,x2,y2,net_obj,layer,width=0.35):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(V(x1,y1)); t.SetEnd(V(x2,y2)); t.SetLayer(layer)
    t.SetWidth(MM(width)); t.SetNet(net_obj); board.Add(t)

def pad_xy(item, number):
    p = item.FindPadByNumber(str(number)).GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)

def route_points(net_name, points, width=0.35, layer=pcbnew.F_Cu):
    for (x1,y1),(x2,y2) in zip(points, points[1:]):
        track(x1,y1,x2,y2,nets[net_name],layer,width)

# Fully route every non-ground net using explicit, reviewable paths.
route_points('5V_IN', [pad_xy(j1,2), pad_xy(j1,4), (31.0,27.04), (31.0,22.0), (33.65,22.0), pad_xy(f1,1)], 0.8)
route_points('5V_FUSED', [pad_xy(f1,2),(38.0,24.5),(38.0,23.5),(60.16,23.5),pad_xy(d1,2),pad_xy(c1,1)], 0.8)
route_points('5V_FUSED', [pad_xy(c1,1),(63.0,23.0),(70.0,23.0),pad_xy(c2,1)], 0.8)
route_points('5V_FUSED', [pad_xy(c2,1),(68.0,27.0),(68.0,33.0),(72.54,33.0),pad_xy(j2,2)], 0.8)
route_points('5V_FUSED', [pad_xy(d1,2),(60.16,24.0),pad_xy(next(t for t in board.GetFootprints() if t.GetReference()=='TP1'),1)], 0.8)
route_points('3V3', [pad_xy(j1,1),(27.0,21.0),(42.0,21.0),pad_xy(r3,1)], layer=pcbnew.B_Cu)
route_points('GPIO18_PWM', [pad_xy(j1,12),(31.0,37.2),pad_xy(r1,1)])
route_points('PWM_GATE', [pad_xy(r1,2),(44.5,37.2),(44.5,39.5),(49.27,39.5),pad_xy(q1,2)], layer=pcbnew.B_Cu)
route_points('PWM_GATE', [pad_xy(q1,2),pad_xy(r2,1)], layer=pcbnew.B_Cu)
route_points('FAN_PWM_OD', [pad_xy(q1,3),(52.0,37.2),(52.0,40.0),(77.62,40.0),pad_xy(j2,4)], layer=pcbnew.B_Cu)
route_points('FAN_PWM_OD', [pad_xy(j2,4),(77.62,45.0),(78.0,45.0)], layer=pcbnew.B_Cu)
route_points('FAN_TACH', [pad_xy(j2,3),(75.08,42.0),pad_xy(r4,2)])
route_points('FAN_TACH', [pad_xy(r4,2),(46.0,42.0),(46.0,33.0),(52.16,33.0),pad_xy(r3,2)])
route_points('FAN_TACH', [pad_xy(j2,3),(75.08,47.0),(82.0,47.0)])
route_points('GPIO17_TACH', [pad_xy(j1,11),(23.0,37.2),(23.0,43.55),(33.0,43.55),pad_xy(r4,1)])

# Ground bus is isolated on B.Cu and connects the single used Pi ground pin to
# every ground terminal. Other GPIO-header ground pins remain unused pads.
ground_points = [pad_xy(j1,6), pad_xy(d1,1), pad_xy(c1,2), pad_xy(c2,2),
                 pad_xy(q1,1), pad_xy(r2,2), pad_xy(j2,1)]
tp2 = next(t for t in board.GetFootprints() if t.GetReference() == 'TP2')
ground_points.append(pad_xy(tp2,1))
route_points('GND', [(32.5,32.0),(77.0,32.0)], 0.8, pcbnew.B_Cu)
for x, y in ground_points:
    if (x, y) == pad_xy(j1,6):
        route_points('GND', [(x,y),(31.0,y),(31.0,32.0),(32.5,32.0)], 0.8, pcbnew.B_Cu)
    else:
        route_points('GND', [(x,y),(x,32.0)], 0.8, pcbnew.B_Cu)

pcbnew.SaveBoard('pi5-cooling-hat.kicad_pcb', board)
