from skidl import *

set_default_tool(KICAD9)

def part(lib, name, ref, value, footprint):
    return Part(lib, name, ref=ref, value=value, footprint=footprint)

j1=part("Connector_Generic","Conn_02x20_Odd_Even","J1","Raspberry Pi 5 GPIO","Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical")
u1=part("Sensor_Humidity","SHT31-DIS","U1","SHT31-DIS-B2.5kS","Sensor_Humidity:Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm")
d1=part("Device","LED_KRBG","D1","L-154A4SURKQBDZGW","LED_THT:LED_D5.0mm-4_RGB_Wide_Pins")
q1=part("Transistor_FET","Q_NMOS_GSD","Q1","2N7000","Package_TO_SOT_THT:TO-92_Inline")
j2=part("Connector_Generic","Conn_01x02","J2","ALARM_OD_GND","Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")
u2=part("Memory_EEPROM","24LC32","U2","CAT24C32","Package_DIP:DIP-8_W7.62mm")
rfp="Resistor_THT:R_Axial_DIN0204_L3.6mm_D1.6mm_P5.08mm_Horizontal"
rs=[part("Device","R",f"R{i}",v,rfp) for i,v in enumerate(("10k DNP","10k DNP","330R","330R","330R","100R","100k","3.9k","3.9k","1k"),1)]
cfp="Capacitor_THT:C_Disc_D3.0mm_W1.6mm_P2.50mm"
cs=[part("Device","C",f"C{i}",v,cfp) for i,v in enumerate(("100nF","100nF","10uF"),1)]
tps=[part("Connector","TestPoint",f"TP{i}",v,"TestPoint:TestPoint_Plated_Hole_D2.0mm") for i,v in enumerate(("I2C_SDA","I2C_SCL","ALARM_OD","3V3","GND","EEPROM_WP"),1)]

names=("GND","3V3","I2C_SDA","I2C_SCL","GPIO18_RED","LED_RED","GPIO23_GREEN","LED_GREEN","GPIO24_BLUE","LED_BLUE","GPIO22_ALARM","ALARM_GATE","ALARM_OD","ID_SD","ID_SC","EEPROM_WP")
n={name:Net(name) for name in names}
n["3V3"] += j1[1],j1[17],u1[5],u2[8],rs[0][1],rs[1][1],rs[7][1],rs[8][1],rs[9][1],cs[0][1],cs[1][1],cs[2][1],tps[3][1]
n["GND"] += j1[6],j1[9],j1[14],j1[20],j1[25],j1[30],j1[34],j1[39],u1[2],u1[7],u1[8],u1[9],d1[1],q1[2],j2[2],rs[6][2],u2[1],u2[2],u2[3],u2[4],cs[0][2],cs[1][2],cs[2][2],tps[4][1]
n["I2C_SDA"] += j1[3],u1[1],rs[0][2],tps[0][1]
n["I2C_SCL"] += j1[5],u1[4],rs[1][2],tps[1][1]
n["GPIO18_RED"] += j1[12],rs[2][1]; n["LED_RED"] += rs[2][2],d1[2]
n["GPIO23_GREEN"] += j1[16],rs[3][1]; n["LED_GREEN"] += rs[3][2],d1[4]
n["GPIO24_BLUE"] += j1[18],rs[4][1]; n["LED_BLUE"] += rs[4][2],d1[3]
n["GPIO22_ALARM"] += j1[15],rs[5][1]; n["ALARM_GATE"] += rs[5][2],q1[1],rs[6][1]
n["ALARM_OD"] += q1[3],j2[1],tps[2][1]
n["ID_SD"] += j1[27],u2[5],rs[7][2]; n["ID_SC"] += j1[28],u2[6],rs[8][2]
n["EEPROM_WP"] += u2[7],rs[9][2],tps[5][1]

NC += u1[3],u1[6]
unused=[2,4,7,8,10,11,13,19,21,22,23,24,26,29,31,32,33,35,36,37,38,40]
NC += j1[unused]
p3=Part("power","PWR_FLAG"); p3[1]+=n["3V3"]
pg=Part("power","PWR_FLAG"); pg[1]+=n["GND"]
ERC(); generate_schematic(tool=KICAD9, auto_stub=True)
