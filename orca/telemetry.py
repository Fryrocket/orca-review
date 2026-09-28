"""Bounded local hardware sampling; no remote commands or caller-selected paths."""
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

PREFIX = 'ORCA_METRICS_V1:'


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3,
                                env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C'})
        return result.stdout[:32000] if result.returncode==0 else ''
    except (OSError, subprocess.SubprocessError): return ''


def number(path, scale=1):
    try:
        value=float(Path(path).read_text().strip())/scale
        return round(value,2) if math.isfinite(value) else None
    except (OSError,ValueError): return None


def collect():
    result={'sampled_at':int(time.time()),'cpu_percent':None,'logical_cpus':os.cpu_count(),
            'load_1_5_15':None,'memory_used_bytes':None,'memory_total_bytes':None,
            'swap_used_bytes':None,'swap_total_bytes':None,'uptime_seconds':None,
            'temperatures':[],'gpus':[],'disks':[]}
    try: result['load_1_5_15']=[round(n,2) for n in os.getloadavg()]
    except OSError: pass
    mounts=['/']
    if platform.system()=='Linux':
        try:
            def ticks():
                values=[int(n) for n in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
                return sum(values),values[3]+values[4]
            total,idle=ticks(); time.sleep(.1); later,later_idle=ticks()
            if later>total: result['cpu_percent']=round(100*(1-(later_idle-idle)/(later-total)),1)
            mem={key:int(value.split()[0])*1024 for key,value in
                 (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}
            result.update(memory_total_bytes=mem['MemTotal'],
                          memory_used_bytes=mem['MemTotal']-mem['MemAvailable'],
                          swap_total_bytes=mem['SwapTotal'],swap_used_bytes=mem['SwapTotal']-mem['SwapFree'])
            result['uptime_seconds']=int(float(Path('/proc/uptime').read_text().split()[0]))
            for line in Path('/proc/mounts').read_text().splitlines():
                parts=line.split()
                if parts[0].startswith('/dev/') and parts[1] not in mounts and not parts[1].startswith('/snap/'):
                    mounts.append(parts[1].replace('\\040',' '))
        except (OSError,ValueError,KeyError,IndexError): pass
        for hw in sorted(Path('/sys/class/hwmon').glob('hwmon*'))[:16]:
            try: name=(hw/'name').read_text().strip()
            except OSError: name=hw.name
            for sensor in sorted(hw.glob('temp*_input'))[:4]:
                value=number(sensor,1000)
                if value is None or not -40<=value<=200: continue
                try: label=sensor.with_name(sensor.name.replace('_input','_label')).read_text().strip()
                except OSError: label=sensor.stem
                result['temperatures'].append({'label':(name+' '+label)[:64],'celsius':value})
        for device in sorted(Path('/sys/class/drm').glob('card[0-9]*/device'))[:8]:
            if not re.fullmatch(r'card\d+', device.parent.name): continue
            busy=number(device/'gpu_busy_percent'); total=number(device/'mem_info_vram_total')
            if busy is not None or total is not None:
                result['gpus'].append({'name':device.parent.name+' AMD/sysfs','load_percent':busy,
                    'memory_total_bytes':total,'memory_used_bytes':number(device/'mem_info_vram_used'),
                    'temperature_c':next((number(p,1000) for p in sorted(device.glob('hwmon/hwmon*/temp1_input'))),None)})
        smi=shutil.which('nvidia-smi')
        if smi:
            output=command([smi,'--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu','--format=csv,noheader,nounits'])
            for line in output.splitlines()[:4]:
                parts=[p.strip() for p in line.split(',')]
                if len(parts)!=5: continue
                def numeric(value, factor=1):
                    try:
                        n=float(value)*factor
                        return n if math.isfinite(n) else None
                    except ValueError: return None
                result['gpus'].append({'name':parts[0][:80],'load_percent':numeric(parts[1]),
                    'memory_used_bytes':numeric(parts[2],1024**2),'memory_total_bytes':numeric(parts[3],1024**2),
                    'temperature_c':numeric(parts[4])})
    elif platform.system()=='Darwin':
        total=command(['/usr/sbin/sysctl','-n','hw.memsize']).strip()
        vm=command(['/usr/bin/vm_stat'])
        match=re.search(r'page size of (\d+) bytes',vm)
        pages={key.strip():int(value) for key,value in re.findall(r'^([^:\n]+):\s*(\d+)\.',vm,re.M)}
        if total.isdigit() and match:
            available=(pages.get('Pages free',0)+pages.get('Pages inactive',0)+pages.get('Pages speculative',0))*int(match[1])
            result.update(memory_total_bytes=int(total),memory_used_bytes=max(0,int(total)-available))
        top=command(['/usr/bin/top','-l','2','-s','1','-n','0','-stats','pid'])
        matches=re.findall(r'CPU usage:.*?([\d.]+)% idle',top)
        if len(matches)>=2: result['cpu_percent']=round(100-float(matches[-1]),1)
        boot=command(['/usr/sbin/sysctl','-n','kern.boottime'])
        match=re.search(r'sec = (\d+)',boot)
        if match: result['uptime_seconds']=max(0,int(time.time())-int(match[1]))
        swap=command(['/usr/sbin/sysctl','-n','vm.swapusage'])
        values=dict(re.findall(r'(total|used) = ([\d.]+)M',swap))
        if values: result.update(swap_total_bytes=int(float(values.get('total',0))*1024**2),swap_used_bytes=int(float(values.get('used',0))*1024**2))
    seen=set()
    for mount in mounts[:8]:
        try:
            device=os.stat(mount).st_dev
            if device in seen: continue
            seen.add(device); disk=shutil.disk_usage(mount)
            result['disks'].append({'mount':mount[:100],'total_bytes':disk.total,'used_bytes':disk.used})
        except OSError: pass
    result['temperatures']=result['temperatures'][:10]
    result['gpus']=result['gpus'][:4]
    result['disks']=result['disks'][:4]
    return result


def encode_detail(summary):
    try:
        metrics=collect()
        encoded=PREFIX+json.dumps({'summary':summary[:200],'metrics':metrics},separators=(',',':'),allow_nan=False)
        return encoded if len(encoded)<=4000 else summary
    except Exception:
        return summary  # A missing sensor must not stop heartbeat delivery.


def decode_detail(detail):
    if not isinstance(detail,str) or not detail.startswith(PREFIX): return None
    try:
        payload=json.loads(detail[len(PREFIX):])
        metrics=payload['metrics']
        if not isinstance(metrics,dict) or type(metrics.get('sampled_at')) is not int: return None
        return payload
    except (ValueError,KeyError,TypeError): return None
