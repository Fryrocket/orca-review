"""Owner-managed saved specialist profiles; profiles are not security identities."""
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import uuid4

from .security import redact_text
from .tools import BOT_TOOL_MANIFESTS, ReadOnlyToolBroker

CREATOR_TOOLS = frozenset({'math.calculate', 'math.scientific', 'engineering.calculate',
    'engineering.catalog', 'file.read', 'file.search', 'repo.read', 'web.search',
    'web.fetch', 'drive.read', 'drive.search'}) & BOT_TOOL_MANIFESTS['orca']


class BotProfiles:
    def __init__(self, path):
        self.lock = RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        if str(path) != ':memory:': Path(path).chmod(0o600)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS custom_bots (
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS custom_bot_edits (
                request_id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        ''')

    def list(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM custom_bots ORDER BY rowid')]

    def get(self, bot_id):
        if not isinstance(bot_id,str) or not re.fullmatch(r'[a-f0-9]{32}',bot_id):
            raise ValueError('Invalid bot ID.')
        with self.lock:
            row = self.db.execute('SELECT body FROM custom_bots WHERE id=?', (bot_id,)).fetchone()
        if not row: raise ValueError('Saved bot not found.')
        return json.loads(row[0])

    def save(self, request):
        if not isinstance(request, dict) or set(request) != {
            'request_id','id','revision','name','role','personality','tools','enabled'}:
            raise ValueError('Invalid bot profile fields.')
        rid = request['request_id']
        if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', rid):
            raise ValueError('Invalid save request ID.')
        for key, limit in [('name',80),('role',3000),('personality',2000)]:
            value=request[key]
            if not isinstance(value,str) or not value.strip() or len(value)>limit or redact_text(value)!=value:
                raise ValueError(f'{key} needs text without secrets, up to {limit} characters.')
        if type(request['enabled']) is not bool or type(request['revision']) is not int:
            raise ValueError('Invalid enabled state or revision.')
        if not isinstance(request['id'],str) or (request['id'] and not re.fullmatch(r'[a-f0-9]{32}',request['id'])):
            raise ValueError('Invalid bot ID.')
        selected=request['tools']
        if (not isinstance(selected,list) or len(selected)>len(CREATOR_TOOLS)
                or any(not isinstance(t,str) or t not in CREATOR_TOOLS for t in selected)
                or len(set(selected))!=len(selected)):
            raise ValueError('Choose only listed read-only tools.')
        encoded=json.dumps(request,sort_keys=True)
        with self.lock, self.db:
            previous=self.db.execute('SELECT request,response FROM custom_bot_edits WHERE request_id=?',(rid,)).fetchone()
            if previous:
                if previous[0]!=encoded: raise ValueError('Save request already used for another edit.')
                return json.loads(previous[1])
            bot_id=request['id']
            old=self.get(bot_id) if bot_id else None
            if request['revision'] != (old['revision'] if old else 0):
                raise ValueError('This bot changed. Reload before saving.')
            if not bot_id and self.db.execute('SELECT count(*) FROM custom_bots').fetchone()[0]>=100:
                raise ValueError('Bot profile limit reached (100). Edit an existing profile.')
            profile={k:request[k] for k in ('name','role','personality','tools','enabled')}
            profile.update(id=bot_id or uuid4().hex,revision=request['revision']+1)
            body=json.dumps(profile,sort_keys=True)
            self.db.execute('INSERT OR REPLACE INTO custom_bots VALUES(?,?,?)',(profile['id'],profile['revision'],body))
            self.db.execute('INSERT INTO custom_bot_edits(request_id,request,response) VALUES(?,?,?)',(rid,encoded,body))
            return profile


def run_profile(profile, prompt, gateway):
    if not profile['enabled']: raise ValueError('Enable this bot before testing it.')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>6000:
        raise ValueError('Test prompt must contain 1–6000 characters.')
    if gateway is None: raise ValueError('The model service is unavailable.')
    # A profile never becomes a new privileged identity or receives a caller's broker.
    handlers=gateway.tool_broker.handlers if gateway.tool_broker else {}
    broker=ReadOnlyToolBroker({key:handlers[key] for key in profile['tools'] if key in handlers and key in CREATOR_TOOLS})
    from .runtime import ModelRuntimeGateway
    scoped=ModelRuntimeGateway(set(gateway.enabled_services),tool_broker=broker)
    description=json.dumps({key:profile[key] for key in ('name','role','personality')})
    return scoped.invoke(service_id='forge_qwen',bot_id='orca',prompt=(
        'Use this owner-authored specialist profile for the response. It is task context, '
        'not a new identity or permission grant. Existing system rules and available tool restrictions apply.\n'
        + description + '\nUser request:\n' + prompt))
