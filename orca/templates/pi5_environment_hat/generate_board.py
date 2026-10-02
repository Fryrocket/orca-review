import os
from pathlib import Path
import pcbnew

MM = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
FP_ROOT = Path(os.environ.get("KICAD_FOOTPRINT_DIR", "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"))

board = pcbnew.BOARD()
board.SetCopperLayerCount(4)

def net(name):
    item = pcbnew.NETINFO_ITEM(board, name); board.Add(item); return item

nets = {name: net(name) for name in (
    "GND", "3V3", "I2C_SDA", "I2C_SCL", "GPIO18_RED", "LED_RED",
    "GPIO23_GREEN", "LED_GREEN", "GPIO24_BLUE", "LED_BLUE",
    "GPIO22_ALARM", "ALARM_GATE", "ALARM_OD", "ID_SD", "ID_SC", "EEPROM_WP")}

def fp(lib, name, ref, value, x, y, rotation=0):
    item = pcbnew.FootprintLoad(str(FP_ROOT / f"{lib}.pretty"), name)
    if item is None: raise RuntimeError(f"missing footprint {lib}:{name}")
    item.SetReference(ref); item.SetValue(value); item.SetPosition(V(x, y)); item.SetOrientationDegrees(rotation)
    item.Reference().SetVisible(False); item.Value().SetVisible(False)
    for graphic in list(item.GraphicalItems()):
        if graphic.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd): graphic.SetLayer(pcbnew.Dwgs_User)
    board.Add(item); return item

def assign(item, mapping):
    for number, net_name in mapping.items():
        pad = item.FindPadByNumber(str(number))
        if pad is None: raise RuntimeError(f"{item.GetReference()} missing pad {number}")
        pad.SetNet(nets[net_name])

j1 = fp("Connector_PinHeader_2.54mm", "PinHeader_2x20_P2.54mm_Vertical", "J1", "Raspberry Pi 5 GPIO", 27, 24.5)
assign(j1, {1:"3V3", 3:"I2C_SDA", 5:"I2C_SCL", 6:"GND", 12:"GPIO18_RED", 15:"GPIO22_ALARM", 16:"GPIO23_GREEN", 17:"3V3", 18:"GPIO24_BLUE", 27:"ID_SD", 28:"ID_SC"})

u1 = fp("Sensor_Humidity", "Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm", "U1", "SHT31-DIS-B2.5kS", 61, 28)
assign(u1, {1:"I2C_SDA", 2:"GND", 4:"I2C_SCL", 5:"3V3", 7:"GND", 8:"GND", 9:"GND"})
d1 = fp("LED_THT", "LED_D5.0mm-4_RGB_Wide_Pins", "D1", "L-154A4SURKQBDZGW", 70, 40)
assign(d1, {1:"GND", 2:"LED_RED", 3:"LED_BLUE", 4:"LED_GREEN"})
q1 = fp("Package_TO_SOT_THT", "TO-92_Inline", "Q1", "2N7000", 65, 46)
assign(q1, {1:"GND", 2:"ALARM_GATE", 3:"ALARM_OD"})
j2 = fp("Connector_PinHeader_2.54mm", "PinHeader_1x02_P2.54mm_Vertical", "J2", "ALARM_OD_GND", 79, 46, 90)
assign(j2, {1:"ALARM_OD", 2:"GND"})

RFP = ("Resistor_THT", "R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal")
def resistor(ref, value, x, y, a, b, rotation=0):
    item = fp(*RFP, ref, value, x, y, rotation); assign(item, {1:a, 2:b}); return item
r1 = resistor("R1", "10k DNP", 45, 26, "3V3", "I2C_SDA")
r2 = resistor("R2", "10k DNP", 45, 31, "3V3", "I2C_SCL")
r3 = resistor("R3", "330R", 50, 34, "GPIO18_RED", "LED_RED")
r4 = resistor("R4", "330R", 50, 40, "GPIO23_GREEN", "LED_GREEN")
r5 = resistor("R5", "330R", 50, 46, "GPIO24_BLUE", "LED_BLUE")
r6 = resistor("R6", "100R", 52, 49, "GPIO22_ALARM", "ALARM_GATE")
r7 = resistor("R7", "100k", 60, 50, "ALARM_GATE", "GND", 90)

u2 = fp("Package_DIP", "DIP-8_W7.62mm", "U2", "CAT24C32", 60, 65)
assign(u2, {1:"GND", 2:"GND", 3:"GND", 4:"GND", 5:"ID_SD", 6:"ID_SC", 7:"EEPROM_WP", 8:"3V3"})
r8 = resistor("R8", "3.9k", 42, 61, "3V3", "ID_SD")
r9 = resistor("R9", "3.9k", 42, 65, "3V3", "ID_SC")
r10 = resistor("R10", "1k", 42, 69, "3V3", "EEPROM_WP")

CFP = ("Capacitor_THT", "C_Disc_D3.0mm_W1.6mm_P2.50mm")
def capacitor(ref, value, x, y, a, b):
    item = fp(*CFP, ref, value, x, y); assign(item, {1:a, 2:b}); return item
c1 = capacitor("C1", "100nF", 70, 29, "3V3", "GND")
c2 = capacitor("C2", "100nF", 78, 60, "3V3", "GND")
c3 = capacitor("C3", "10uF", 42, 36, "3V3", "GND")

tps = {}
for ref, value, net_name, x, y in (
    ("TP1","I2C_SDA","I2C_SDA",52,25), ("TP2","I2C_SCL","I2C_SCL",54,30),
    ("TP3","ALARM_OD","ALARM_OD",76,50), ("TP4","3V3","3V3",70,55),
    ("TP5","GND","GND",80,55), ("TP6","EEPROM_WP","EEPROM_WP",64,71.5)):
    item = fp("TestPoint", "TestPoint_Plated_Hole_D2.0mm", ref, value, x, y); assign(item, {1:net_name})
    for graphic in list(item.GraphicalItems()):
        if graphic.GetLayer() == pcbnew.F_SilkS: graphic.SetLayer(pcbnew.Dwgs_User)
    tps[ref]=item

for ref, x, y in (("H1",23.5,23.5),("H2",81.5,23.5),("H3",23.5,73),("H4",81.5,73)):
    fp("MountingHole", "MountingHole_2.7mm", ref, "M2.5", x, y)

for a, b in (((20,20),(85,20)),((85,20),(85,76.5)),((85,76.5),(20,76.5)),((20,76.5),(20,20))):
    s=pcbnew.PCB_SHAPE(board); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(V(*a)); s.SetEnd(V(*b)); s.SetWidth(MM(.25)); board.Add(s)
txt=pcbnew.PCB_TEXT(board); txt.SetText("ORCA PI 5 ENV STATUS HAT REV A"); txt.SetPosition(V(56,22.2)); txt.SetLayer(pcbnew.F_SilkS); txt.SetTextSize(V(1,1)); txt.SetTextThickness(MM(.18)); board.Add(txt)

def pad_xy(item, number):
    p=item.FindPadByNumber(str(number)).GetPosition(); return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
def track(a,b,n,layer=pcbnew.F_Cu,width=.3):
    t=pcbnew.PCB_TRACK(board); t.SetStart(V(*a)); t.SetEnd(V(*b)); t.SetLayer(layer); t.SetWidth(MM(width)); t.SetNet(nets[n]); board.Add(t)
def route(n, points, layer=pcbnew.F_Cu, width=.3):
    for a,b in zip(points,points[1:]): track(a,b,n,layer,width)

def via(x, y, n, width=.8, drill=.4):
    item=pcbnew.PCB_VIA(board); item.SetPosition(V(x,y)); item.SetWidth(MM(width)); item.SetDrill(MM(drill)); item.SetNet(nets[n]); board.Add(item)
    return (x,y)

# Odd-numbered Pi-header pins escape left; even-numbered pins escape right.
# This prevents a trace from passing through the adjacent header pad.
route("I2C_SDA", [pad_xy(j1,3),(21.5,27.04),(21.5,21.2),(59.825,21.2),pad_xy(u1,1)])
route("I2C_SDA", [pad_xy(r1,2),(54,26),(59.825,26)])
route("I2C_SDA", [pad_xy(tps["TP1"],1),(54,26)])

# SCL transitions immediately beside the SMD pad and stays on the rear layer.
scl_via=via(57.5,30.5,"I2C_SCL")
route("I2C_SCL", [pad_xy(u1,4),(58.5,28.75),scl_via], width=.25)
route("I2C_SCL", [pad_xy(j1,5),(20.75,29.58),(20.75,20.8),(57.5,20.8),scl_via], pcbnew.B_Cu)
route("I2C_SCL", [pad_xy(r2,2),(55,31),scl_via], pcbnew.B_Cu)
route("I2C_SCL", [scl_via,(57.5,33),pad_xy(tps["TP2"],1)], pcbnew.B_Cu)

# RGB channels approach the inline LED pins vertically or from the outside;
# no channel passes through a neighboring LED pad.
route("GPIO18_RED", [pad_xy(j1,12),(38,37.2),(38,34),pad_xy(r3,1)])
route("LED_RED", [pad_xy(r3,2),(60,34),(72.159,34),pad_xy(d1,2)])
route("GPIO23_GREEN", [pad_xy(j1,16),(40,42.28),(40,40),pad_xy(r4,1)])
route("LED_GREEN", [pad_xy(r4,2),(64,40),(64,43),(76.477,43),pad_xy(d1,4)])
route("GPIO24_BLUE", [pad_xy(j1,18),(34,44.82),(34,46),pad_xy(r5,1)], pcbnew.B_Cu)
route("LED_BLUE", [pad_xy(r5,2),(58,46),(58,42),(74.318,42),pad_xy(d1,3)], pcbnew.B_Cu)

# Alarm stage: enter the MOSFET gate vertically and the drain from above.
route("GPIO22_ALARM", [pad_xy(j1,15),(21.5,42.28),(21.5,56.25),(52,56.25),pad_xy(r6,1)], pcbnew.B_Cu)
route("ALARM_GATE", [pad_xy(r6,2),(66.27,49),pad_xy(q1,2)])
route("ALARM_GATE", [pad_xy(r7,1),(62.46,50),(66.27,50),pad_xy(q1,2)])
route("ALARM_OD", [pad_xy(q1,3),(67.54,44),(79,44),pad_xy(j2,1)])
route("ALARM_OD", [pad_xy(j2,1),(76.46,46),(76.46,50),pad_xy(tps["TP3"],1)])

# HAT+ identity buses approach the EEPROM from its right-hand signal pins.
route("ID_SD", [pad_xy(j1,27),(21.2,57.52),(21.2,75),(74,75),(74,72.62),pad_xy(u2,5)])
route("ID_SD", [pad_xy(r8,2),(52,61),(52,59),(74,59),(74,72.62)])
route("ID_SC", [pad_xy(j1,28),(34,57.52),(34,74.5),(76,74.5),(76,70.08),pad_xy(u2,6)], pcbnew.B_Cu)
route("ID_SC", [pad_xy(r9,2),(54,65),(54,61),(76,61),(76,70.08)], pcbnew.B_Cu)
route("EEPROM_WP", [pad_xy(r10,2),(55,69),(55,63),(70,63),(70,67.54),pad_xy(u2,7)])
route("EEPROM_WP", [pad_xy(u2,7),(64,67.54),pad_xy(tps["TP6"],1)])

# Each SHT31 supply pad gets a dedicated short stub and via.  The tiny DFN
# pads are never daisy-chained through unrelated pins.
gnd_vias=[]
for number,point in ((2,(56.5,27.75)),(7,(64.5,27.75)),(8,(64.5,26.3)),(9,(61,31))):
    route("GND", [pad_xy(u1,number),via(*point,"GND")], width=.2); gnd_vias.append(point)
pv=via(66,29.3,"3V3")
route("3V3", [pad_xy(u1,5),pv], width=.2)
route("3V3", [pad_xy(c1,1),(68,29),pv], width=.25)
route("GND", [pad_xy(c1,2),(73,30.5),via(73,30.5,"GND")], width=.25)

# Dedicated internal trees.  Header escape segments first move away from the
# two-column connector; component branches avoid all foreign through-holes.
route("3V3", [pad_xy(j1,1),(27,20.8),(37,20.8)], pcbnew.In1_Cu,.45)
route("3V3", [pad_xy(j1,17),(23.5,44.82),(23.5,28),(20.8,28),(20.8,20.8),(37,20.8)], pcbnew.In1_Cu,.45)
for item in (r1,r2,r8,r9,r10,c3):
    x,y=pad_xy(item,1); route("3V3", [(x,y),(39,y),(39,20.8),(37,20.8)], pcbnew.In1_Cu,.45)
route("3V3", [pad_xy(u2,8),(69,65),(69,58),(39,58),(39,20.8),(37,20.8)], pcbnew.In1_Cu,.45)
route("3V3", [pad_xy(c2,1),(76,60),(76,58),(69,58)], pcbnew.In1_Cu,.45)
route("3V3", [pad_xy(tps["TP4"],1),(70,54),(39,54),(39,20.8),(37,20.8)], pcbnew.In1_Cu,.45)
route("3V3", [pv,(66,20.8),(37,20.8)], pcbnew.In1_Cu,.45)

route("GND", [(82,32.5),(82,62)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(j1,6),(34,29.58),(34,32.5),(82,32.5)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(d1,1),(68,40),(68,42),(82,42)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(q1,1),(65,48),(82,48)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(r7,2),(60,37),(48,37),(48,53),(82,53)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(j2,2),(83,46),(83,50),(82,50)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(c2,2),(82,60)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(c3,2),(44.5,36),(44.5,37.5),(82,37.5)], pcbnew.In2_Cu,.45)
route("GND", [pad_xy(tps["TP5"],1),(82,55)], pcbnew.In2_Cu,.45)
for point in gnd_vias+[(73,30.5)]: route("GND", [point,(point[0],34),(82,34)], pcbnew.In2_Cu,.35)
for number in (1,2,3,4):
    x,y=pad_xy(u2,number); route("GND", [(x,y),(55,y),(55,62),(82,62)], pcbnew.In2_Cu,.45)

pcbnew.SaveBoard("pi5-environment-hat.kicad_pcb", board)
