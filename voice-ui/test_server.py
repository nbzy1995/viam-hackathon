import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('voice_server', Path(__file__).with_name('server.py'))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Harness:
    def __init__(self):
        self.calls = []
        self.error = None

    async def reply(self, history):
        self.calls.append(history)
        if self.error:
            raise self.error
        return 'Local reply'


class Speech:
    async def transcribe(self, data, kind):
        assert data == b'voice bytes'
        assert kind == 'audio/webm'
        return 'Hello from voice'

    async def speak(self, text):
        assert text == 'Local reply'
        return b'mp3 bytes'


@pytest.fixture
def client():
    harness = Harness()
    app = server.create_app(harness, Speech())
    with TestClient(app) as client:
        client.headers['X-UI-Token'] = client.get('/api/config').json()['token']
        client.sid = client.post('/api/sessions').json()['session_id']
        yield client


def test_text_and_voice_share_harness_history(client):
    assert client.post('/api/chat', json={'session_id':client.sid, 'text':'Hello'}).json() == {'text':'Local reply'}
    transcript = client.post('/api/transcribe', content=b'voice bytes', headers={'content-type':'audio/webm'}).json()['text']
    assert client.post('/api/chat', json={'session_id':client.sid, 'text':transcript}).status_code == 200
    calls = client.app.state.harness.calls
    assert [m['role'] for m in calls[-1]] == ['user','assistant','user']
    assert calls[-1][-1]['content'] == transcript
    assert client.post('/api/speak', json={'session_id':client.sid}).content == b'mp3 bytes'


def test_busy_does_not_queue_or_change_history(client):
    client.app.state.busy = True
    assert client.post('/api/chat', json={'session_id':client.sid,'text':'Hello'}).status_code == 409
    assert client.app.state.harness.calls == []
    assert client.app.state.sessions[client.sid] == []


def test_harness_failure_preserves_history_and_unlocks(client):
    client.app.state.harness.error = HTTPException(502, 'Failed')
    assert client.post('/api/chat', json={'session_id':client.sid,'text':'Hello'}).status_code == 502
    assert not client.app.state.busy
    assert client.app.state.sessions[client.sid] == []
    client.app.state.harness.error = asyncio.TimeoutError()
    assert client.post('/api/chat', json={'session_id':client.sid,'text':'Hello'}).status_code == 504
    assert not client.app.state.busy


def test_end_and_new_chat_isolate_history(client):
    client.post('/api/chat', json={'session_id':client.sid,'text':'Hello'})
    client.delete('/api/sessions/' + client.sid)
    assert client.post('/api/chat', json={'session_id':client.sid,'text':'Again'}).status_code == 404
    new_id = client.post('/api/sessions').json()['session_id']
    assert new_id != client.sid
    assert client.app.state.sessions[new_id] == []


def test_local_request_boundary_and_secret_redaction(client, monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'secret-never-in-browser')
    response = client.get('/api/config')
    assert 'secret-never-in-browser' not in response.text
    assert client.post('/api/sessions', headers={'X-UI-Token':'wrong'}).status_code == 403
    assert client.get('/api/config', headers={'Host':'attacker.example'}).status_code == 400
    assert client.get('/static/../../../pyproject.toml').status_code != 200


def test_audio_and_text_validation(client):
    assert client.post('/api/transcribe', content=b'x', headers={'content-type':'text/plain'}).status_code == 415
    assert client.post('/api/transcribe', content=b'', headers={'content-type':'audio/webm'}).status_code == 422
    assert client.post('/api/transcribe', content=b'x'*(server.MAX_AUDIO+1), headers={'content-type':'audio/webm'}).status_code == 413
    assert client.post('/api/chat', json={'session_id':client.sid,'text':'  '}).status_code == 422
    assert client.post('/api/speak', json={'session_id':client.sid}).status_code == 409


def test_speech_provider_contract(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'voice-id')
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['xi-api-key'] == 'test-key'
        if request.url.path.endswith('/speech-to-text'):
            assert b'scribe_v2' in request.content and b'voice bytes' in request.content
            return httpx.Response(200, json={'text':'Hello'})
        assert request.url.path.endswith('/text-to-speech/voice-id')
        assert b'eleven_flash_v2_5' in request.content
        return httpx.Response(200, content=b'mp3')
    original = httpx.AsyncClient
    monkeypatch.setattr(server.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    async def run():
        speech = server.ElevenSpeech()
        assert await speech.transcribe(b'voice bytes', 'audio/webm') == 'Hello'
        assert await speech.speak('Hello') == b'mp3'
    asyncio.run(run())
    assert len(requests) == 2


def test_codex_subprocess_contract(monkeypatch):
    captured = {}
    class Process:
        returncode = 0
        async def communicate(self, prompt):
            captured['prompt'] = prompt
            return b'{"type":"item.completed","item":{"type":"agent_message","text":"Hello"}}\n', None
    async def create(*args, **kwargs):
        captured['args'], captured['kwargs'] = args, kwargs
        return Process()
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'must-not-inherit')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
    assert asyncio.run(server.CodexHarness().reply([{'role':'user','content':'Hello'}])) == 'Hello'
    assert '--ignore-user-config' in captured['args']
    assert '--ephemeral' in captured['args']
    assert captured['args'][captured['args'].index('--sandbox')+1] == 'read-only'
    assert 'ELEVENLABS_API_KEY' not in captured['kwargs']['env']
    assert captured['args'][-1] == '-'


def test_realtime_token_and_pcm_stream(client):
    async def token(): return 'single-use-test-token'
    async def stream(text):
        assert text == 'Local reply'
        yield b'\x01\x00'
        yield b'\x02\x00'
    client.app.state.speech.realtime_token = token
    client.app.state.speech.stream = stream
    assert client.post('/api/speech-token').json() == {'token':'single-use-test-token'}
    assert client.post('/api/speak-stream',json={'session_id':client.sid}).status_code == 409
    client.post('/api/chat',json={'session_id':client.sid,'text':'hello'})
    assert client.post('/api/speak-stream',json={'session_id':client.sid}).content == b'\x01\x00\x02\x00'


def test_stream_provider_error_is_reported_before_http_success(client):
    async def stream(text):
        raise HTTPException(502,'Speech provider unavailable')
        yield b''
    client.app.state.speech.stream = stream
    client.post('/api/chat',json={'session_id':client.sid,'text':'hello'})
    response=client.post('/api/speak-stream',json={'session_id':client.sid})
    assert response.status_code == 502
    assert 'unavailable' in response.json()['detail']


def test_stop_remains_available_while_busy(client):
    async def stop(): return 'Stop requested'
    client.app.state.harness.stop = stop
    client.app.state.busy = True
    assert client.post('/api/stop').json() == {'text':'Stop requested'}
    assert client.app.state.harness.calls == []


def test_dashboard_reads_do_not_start_tasks_and_frames_are_memory_only(client):
    assert not client.get('/api/dashboard').json()['connected']
    client.app.state.dashboard.frames['frame-1.jpg'] = b'jpeg'
    assert client.get('/api/camera/frame-1.jpg').content == b'jpeg'
    assert client.get('/api/camera/.env').status_code == 404
    assert client.app.state.harness.calls == []


@pytest.mark.parametrize('streaming', [True, False])
def test_key_quota_is_identified_without_leaking_provider_details(monkeypatch, streaming):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'secret-test-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'voice-id')
    def handle(request):
        return httpx.Response(401, json={'detail': {'status': 'quota_exceeded',
            'message': 'Sensitive account details here', 'request_id': 'private-id'}})
    original = httpx.AsyncClient
    monkeypatch.setattr(server.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    async def run():
        speech = server.ElevenSpeech()
        with pytest.raises(HTTPException) as error:
            if streaming:
                await anext(speech.stream('Hello'))
            else:
                await speech.speak('Hello')
        assert error.value.detail['code'] == 'speech_quota_exceeded'
        assert 'credit limit' in error.value.detail['message']
        assert 'Sensitive' not in str(error.value.detail)
        assert 'private-id' not in str(error.value.detail)
    asyncio.run(run())
