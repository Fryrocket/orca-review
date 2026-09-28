import json
from types import SimpleNamespace
import pytest
from orca.bot_creator import BotProfiles,run_profile
from orca.tools import ReadOnlyToolBroker


def draft(**overrides):
    return dict(request_id='request_0001',id='',revision=0,name='Circuit Scout',
        role='Analyze circuits using available tools.',personality='Direct and precise.',
        tools=['math.scientific'],enabled=True,**overrides)


def test_save_replay_revision_and_persistence(tmp_path):
    path=tmp_path/'bots.db'; store=BotProfiles(path); request=draft()
    one=store.save(request)
    assert store.save(request)==one
    assert len(store.list())==1
    assert BotProfiles(path).get(one['id'])==one
    edit={**request,'id':one['id'],'revision':1,'request_id':'request_0002','name':'New name'}
    assert store.save(edit)['revision']==2
    with pytest.raises(ValueError):store.save({**edit,'request_id':'request_0003'})
    with pytest.raises(ValueError):store.save({**request,'name':'Wrong replay'})


@pytest.mark.parametrize('changes',[{'tools':['terminal.execute']},{'tools':['math.scientific']*2},
 {'enabled':'yes'},{'revision':True},{'name':''},{'role':'x'*3001},{'id':'../file'},
 {'tools':'all'},{'tools':[{}]},{'permission':'admin'},{'request_id':'a'*101},{'id':"' OR '1'='1"}])
def test_invalid_profiles(changes):
    with pytest.raises(ValueError):BotProfiles(':memory:').save({**draft(),**changes})


def test_profile_only_receives_selected_handlers(monkeypatch):
    captured={}
    def invoke(self,**request):
        captured.update(handlers=set(self.tool_broker.handlers),request=request)
        return {'summary':'test'}
    monkeypatch.setattr('orca.runtime.ModelRuntimeGateway.invoke',invoke)
    profile=BotProfiles(':memory:').save(draft())
    gateway=SimpleNamespace(enabled_services={'forge_qwen'},tool_broker=ReadOnlyToolBroker(
        {'math.scientific':lambda:None,'file.read':lambda:None,'terminal.inspect':lambda:None}))
    assert run_profile(profile,'Hello',gateway)['summary']=='test'
    assert captured['handlers']=={'math.scientific'}
    assert captured['request']['bot_id']=='orca'
    with pytest.raises(ValueError):run_profile({**profile,'enabled':False},'Hello',gateway)


def test_profile_api_requires_owner(tmp_path):
    from threading import Thread
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from orca.web import OrcaHTTPServer
    from orca.control_plane import ControlPlane
    server=OrcaHTTPServer(('127.0.0.1',0),ControlPlane(),operator_token='t'*32,bot_profiles=BotProfiles(tmp_path/'bots.db'))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        def post(action,body,auth=False):
            headers={'Content-Type':'application/json'}
            if auth:headers['X-ORCA-Operator-Token']='t'*32
            return urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/custom-bots/{action}',data=json.dumps(body).encode(),headers=headers))
        for action,body in [('list',{}),('save',draft()),('test',{'id':'a'*32,'prompt':'Hi'})]:
            with pytest.raises(HTTPError) as exc:post(action,body)
            assert exc.value.code==401
        with post('save',draft(),True) as response:assert json.load(response)['name']=='Circuit Scout'
        with post('list',{},True) as response:assert len(json.load(response)['bots'])==1
    finally:server.shutdown();server.server_close()
