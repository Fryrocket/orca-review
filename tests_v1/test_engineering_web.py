import json
from threading import Thread
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from orca.control_plane import ControlPlane
from orca.web import OrcaHTTPServer


def test_math_endpoints_require_owner_and_work_without_model():
    token='t'*32
    server=OrcaHTTPServer(('127.0.0.1',0),ControlPlane(),operator_token=token)
    Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        catalog=json.load(urlopen(base+'/api/engineering/catalog'))
        assert len(catalog)==16
        for path,payload in [('/api/science',{'operation':'evaluate','expression':'sin(pi/6)'}),
                             ('/api/engineering',{'tool':'capacitor_energy','values':{'c':.001,'v':24}})]:
            def post(headers):
                return urlopen(Request(base+path,data=json.dumps(payload).encode(),headers=headers))
            with pytest.raises(HTTPError) as denied: post({'Content-Type':'application/json'})
            assert denied.value.code==401
            with post({'Content-Type':'application/json','X-ORCA-Operator-Token':token}) as response:
                assert json.load(response)['status']=='ok'
    finally:
        server.shutdown();server.server_close()


def test_scientific_chat_command_avoids_model(monkeypatch):
    from orca.runtime import ModelRuntimeGateway
    def forbidden(*args,**kwargs): pytest.fail('Explicit command should not invoke a model')
    monkeypatch.setattr('orca.runtime.bounded_json_transport',forbidden)
    result=ModelRuntimeGateway({'forge_qwen'}).chat(prompt='/diff x^3')
    assert '3*x**2' in result['result']['summary']


def test_engineering_results_are_not_rewritten_by_model():
    from orca.runtime import SandboxedOpenAIAdapter
    from orca.tools import ReadOnlyToolBroker
    from orca.engineering import engineering_chat_calculate
    calls=[]
    def transport(endpoint,payload,timeout):
        calls.append(payload)
        assert len(calls)==1, 'Engineering numeric results must bypass model narration'
        plan={'tool_requests':[{'name':'engineering.calculate','arguments':{
            'tool':'beam_cantilever','values':{'force':'100','length':'.5','young':'200e9','inertia':'1e-8','c':'.01'}}}]}
        return {'choices':[{'message':{'content':json.dumps(plan)}}]}
    adapter=SandboxedOpenAIAdapter(endpoint='http://127.0.0.1:11436/v1/chat/completions',allowed_models=('ORCA-QWEN',),transport=transport)
    result=adapter.invoke(bot_id='orca',model='ORCA-QWEN',prompt='Calculate the beam.',tool_broker=ReadOnlyToolBroker({'engineering.calculate':engineering_chat_calculate}))
    assert '50000000' in result['summary']
    assert '1e-08 m⁴' in result['summary']
