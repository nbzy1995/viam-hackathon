"""Loopback voice bridge with optional validated physical robot execution."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent
MAX_AUDIO = 10 * 1024 * 1024


class CodexHarness:
    async def reply(self, history):
        # Read-only, no inherited MCP integrations, no shell interpolation.
        prompt = ('You are the local assistant for the Viam workshop chat UI. '
                  'Answer concisely. This interface has no robot execution connection. '
                  'Never claim to move, stop, inspect live hardware, or complete a robot task. '
                  'Do not run tools or commands. Conversation JSON follows:\n' + json.dumps(history))
        env = {k: v for k, v in os.environ.items() if k in
               {'PATH', 'HOME', 'USER', 'TMPDIR', 'CODEX_HOME', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}}
        process = await asyncio.create_subprocess_exec(
            'codex', 'exec', '--ignore-user-config', '--ephemeral', '--sandbox', 'read-only',
            '--json', '--color', 'never', '-C', str(ROOT.parent), '-',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env, start_new_session=True,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(prompt.encode()), 120)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
            raise
        if process.returncode:
            raise HTTPException(502, 'Codex failed. Check local Codex login and CLI availability.')
        replies = []
        for line in stdout.decode().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                replies.append(item.get('text', ''))
        if not replies:
            raise HTTPException(502, 'Codex returned no assistant response.')
        return '\n\n'.join(replies)


class ElevenSpeech:
    @staticmethod
    async def provider_error(response):
        await response.aread()
        try:
            detail = response.json().get('detail', {})
            code = detail.get('code') or detail.get('status') if isinstance(detail, dict) else None
        except ValueError:
            code = None
        if code == 'quota_exceeded':
            return HTTPException(502, detail={
                'code': 'speech_quota_exceeded',
                'message': 'ElevenLabs API-key credit limit reached. Increase the key limit or use device voice for replies.'})
        return HTTPException(502, f'ElevenLabs rejected speech (HTTP {response.status_code}). Check key permissions and credits.')

    async def request(self, endpoint, **kwargs):
        key = os.getenv('ELEVENLABS_API_KEY', '').strip()
        if not key:
            raise HTTPException(503, 'Set ELEVENLABS_API_KEY in voice-ui/.env for speech.')
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post('https://api.elevenlabs.io/v1/' + endpoint,
                                            headers={'xi-api-key': key}, **kwargs)
        except httpx.HTTPError:
            raise HTTPException(502, 'Could not reach ElevenLabs.') from None
        if response.is_error:
            raise await self.provider_error(response)
        return response

    async def realtime_token(self):
        response = await self.request('single-use-token/realtime_scribe')
        return response.json()['token']

    async def stream(self, text):
        voice = os.getenv('ELEVENLABS_VOICE_ID', '').strip()
        if not voice:
            raise HTTPException(503, 'Voice ID is not configured.')
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream('POST', 'https://api.elevenlabs.io/v1/text-to-speech/' + quote(voice, safe='') + '/stream',
                headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY']},
                params={'output_format':'pcm_16000'},
                json={'text':text, 'model_id':os.getenv('ELEVENLABS_TTS_MODEL','eleven_flash_v2_5')}) as response:
                if response.is_error:
                    raise await self.provider_error(response)
                async for chunk in response.aiter_bytes():
                    yield chunk

    async def transcribe(self, audio, content_type):
        response = await self.request('speech-to-text',
            files={'file': ('recording', audio, content_type)},
            data={'model_id': os.getenv('ELEVENLABS_STT_MODEL', 'scribe_v2'), 'tag_audio_events': 'false'})
        try:
            text = response.json()['text'].strip()
        except (ValueError, KeyError, AttributeError, TypeError):
            raise HTTPException(502, 'ElevenLabs returned an invalid transcript.') from None
        if not text:
            raise HTTPException(422, 'No speech was recognized. Try another recording.')
        return text

    async def speak(self, text):
        voice = os.getenv('ELEVENLABS_VOICE_ID', '').strip()
        if not voice:
            raise HTTPException(503, 'Set ELEVENLABS_VOICE_ID in voice-ui/.env for spoken replies.')
        response = await self.request('text-to-speech/' + quote(voice, safe=''),
            params={'output_format': 'mp3_44100_128'},
            json={'text': text, 'model_id': os.getenv('ELEVENLABS_TTS_MODEL', 'eleven_flash_v2_5')})
        return response.content


class Turn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=8000)


class Speech(BaseModel):
    session_id: str


def create_app(harness=None, speech=None, dashboard=None):
    from dashboard import Dashboard
    observe_robot = harness is None and os.getenv('VOICE_ROBOT_ENABLED') == '1'

    @asynccontextmanager
    async def lifespan(app):
        await app.state.dashboard.start()
        try:
            yield
        finally:
            await app.state.dashboard.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
    if harness is None and os.getenv('VOICE_ROBOT_ENABLED') == '1':
        import sys
        sys.path.insert(0, str(ROOT))
        from robot_bridge import RobotHarness
        harness = RobotHarness()
    app.state.harness = harness or CodexHarness()
    app.state.speech = speech or ElevenSpeech()
    app.state.sessions = {}
    app.state.busy = False
    app.state.dashboard = dashboard or Dashboard(
        os.getenv('VOICE_ROBOT_SOURCE', str(ROOT.parent)) if observe_robot else None,
        busy=lambda: app.state.busy)
    token = secrets.token_urlsafe(32)

    @app.middleware('http')
    async def local_access(request, call_next):
        if request.method not in ('GET', 'HEAD') and request.headers.get('x-ui-token') != token:
            return JSONResponse({'detail': 'Reload the local UI before sending requests.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    @app.get('/chat')
    async def index():
        return FileResponse(ROOT / 'app/static/chat.html')

    @app.get('/api/config')
    async def config():
        return {'token': token, 'configured': harness is not None or shutil.which('codex') is not None,
                'robot': os.getenv('VOICE_ROBOT_ENABLED') == '1',
                'quick_checks': json.loads((ROOT / 'quick-checks.json').read_text()),
                'stt': bool(os.getenv('ELEVENLABS_API_KEY')),
                'tts': bool(os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID'))}

    @app.post('/api/speech-token')
    async def speech_token():
        return {'token': await app.state.speech.realtime_token()}

    @app.get('/api/status')
    async def progress():
        return {'busy': app.state.busy, 'message': getattr(app.state.harness, 'progress', 'Thinking')}

    @app.get('/api/dashboard')
    async def dashboard_state():
        activity = getattr(app.state.harness, 'progress', 'Working') if app.state.busy else 'Waiting for a voice or text request.'
        return app.state.dashboard.snapshot(activity=activity)

    @app.get('/api/camera/{name}')
    async def camera_frame(name: str):
        frame = app.state.dashboard.frames.get(name)
        if frame is None:
            raise HTTPException(404, 'Camera frame unavailable.')
        return Response(frame, media_type='image/jpeg')

    @app.post('/api/stop')
    async def stop():
        method = getattr(app.state.harness, 'stop', None)
        return {'text': await method() if method else 'No robot controller is connected.'}

    @app.post('/api/sessions')
    async def new_session():
        if len(app.state.sessions) >= 32:
            raise HTTPException(503, 'Too many open chats. End a chat or restart the local server.')
        sid = secrets.token_urlsafe(24)
        app.state.sessions[sid] = []
        return {'session_id': sid}

    def history(sid):
        if sid not in app.state.sessions:
            raise HTTPException(404, 'Chat ended. Start a new chat.')
        return app.state.sessions[sid]

    @app.delete('/api/sessions/{sid}')
    async def end_session(sid):
        app.state.sessions.pop(sid, None)
        return {'ended': True}

    @app.post('/api/chat')
    async def chat(turn: Turn):
        messages = history(turn.session_id)
        if app.state.busy:
            raise HTTPException(409, 'The local harness is busy. Try again when it finishes.')
        if not turn.text.strip():
            raise HTTPException(422, 'Enter a message.')
        # Bound context without silently dropping earlier turns.
        if sum(len(m['content']) for m in messages) + len(turn.text) > 48000:
            raise HTTPException(413, 'This chat is full. End it and start a new chat.')
        app.state.busy = True
        try:
            pending = [*messages, {'role': 'user', 'content': turn.text.strip()}]
            try:
                answer = await app.state.harness.reply(pending)
            except asyncio.TimeoutError:
                raise HTTPException(504, 'The task timed out. Completion is unconfirmed; any active robot task was asked to stop.') from None
            except RuntimeError as exc:
                raise HTTPException(502, str(exc)) from None
            if turn.session_id not in app.state.sessions:
                raise HTTPException(409, 'Chat ended while Codex was replying.')
            messages.extend([pending[-1], {'role': 'assistant', 'content': answer}])
            return {'text': answer}
        finally:
            app.state.busy = False

    @app.post('/api/transcribe')
    async def transcribe(request: Request):
        content_type = request.headers.get('content-type', '').split(';')[0]
        if content_type not in {'audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav'}:
            raise HTTPException(415, 'Unsupported recording format.')
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_AUDIO:
                raise HTTPException(413, 'Recording too large. Keep voice messages under 60 seconds.')
        if not audio:
            raise HTTPException(422, 'Recording is empty.')
        return {'text': await app.state.speech.transcribe(bytes(audio), content_type)}

    @app.post('/api/speak')
    async def speak(body: Speech):
        messages = history(body.session_id)
        if not messages or messages[-1]['role'] != 'assistant':
            raise HTTPException(409, 'No assistant reply to speak.')
        return Response(await app.state.speech.speak(messages[-1]['content']), media_type='audio/mpeg')

    @app.post('/api/speak-stream')
    async def speak_stream(body: Speech):
        messages = history(body.session_id)
        if not messages or messages[-1]['role'] != 'assistant':
            raise HTTPException(409, 'No assistant reply to speak.')
        chunks = app.state.speech.stream(messages[-1]['content'])
        try:
            first = await anext(chunks)
        except StopAsyncIteration:
            raise HTTPException(502, 'Speech provider returned no audio.') from None
        async def body_stream():
            try:
                yield first
                async for chunk in chunks:
                    yield chunk
            finally:
                await chunks.aclose()
        return StreamingResponse(body_stream(), media_type='application/octet-stream')

    app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')
    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('VOICE_UI_PORT', '8088')))
