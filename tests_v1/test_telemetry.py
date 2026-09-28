import json
import pytest
from orca.telemetry import collect,encode_detail,decode_detail,PREFIX


def test_legacy_and_invalid_detail():
    assert decode_detail('healthy') is None
    assert decode_detail(PREFIX+'{}') is None
    assert decode_detail(PREFIX+'bad') is None


def test_report_fits_signed_envelope(monkeypatch):
    monkeypatch.setattr('orca.telemetry.collect',lambda:{'sampled_at':123,'cpu_percent':None})
    text=encode_detail('endpoint healthy')
    assert len(text)<=4000
    assert decode_detail(text)['metrics']['cpu_percent'] is None
    assert decode_detail(text)['summary']=='endpoint healthy'


def test_collector_failure_preserves_health(monkeypatch):
    def fail():raise OSError('missing sensor')
    monkeypatch.setattr('orca.telemetry.collect',fail)
    assert encode_detail('healthy')=='healthy'


def test_real_local_sample_is_finite_and_bounded():
    result=collect()
    assert type(result['sampled_at']) is int
    json.dumps(result,allow_nan=False)
    assert len(result['gpus'])<=4 and len(result['temperatures'])<=10 and len(result['disks'])<=4
    assert result['memory_total_bytes'] is None or result['memory_total_bytes']>0


def test_verified_heartbeat_exposes_metrics_without_schema_change():
    from orca.control_plane import ControlPlane
    from orca.fleet import Heartbeat,sign_heartbeat
    control=ControlPlane();key=b'k'*32
    control.enroll_node('forge',key=key,actor='fry')
    detail=PREFIX+json.dumps({'summary':'healthy','metrics':{'sampled_at':123,'cpu_percent':25}})
    beat=Heartbeat('forge',123,1,'healthy',detail)
    control.accept_heartbeat(beat,signature=sign_heartbeat(beat,key),key=key,now=123)
    node=next(n for n in control.snapshot()['nodes'] if n['id']=='forge')
    assert node['telemetry']['cpu_percent']==25
    assert node['detail']=='healthy'
