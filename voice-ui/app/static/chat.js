import { Scribe, CommitStrategy, RealtimeEvents } from '@elevenlabs/client';
// Jerry's Ringside UI, adapted to the local Codex harness and direct speech APIs.
const $ = id => document.getElementById(id);
let config = {}, sid = null, busy = false, recording = false, speaking = false, hasReply = false;
let connection = null, context = null, playbackAbort = null, sources = new Set(), audioGeneration = 0;

function status(text, kind = '') { $('status').textContent = text; $('status').className = `status ${kind}`; }
function hint(text, error = false) { $('hint').textContent = text; $('hint').className = `hint${error ? ' error' : ''}`; }
function message(role, text) {
  $('messages').querySelector('.empty')?.remove();
  const row = document.createElement('div');
  row.className = role === 'system' ? 'system' : `message ${role === 'user' ? 'you' : 'assistant'}`;
  if (role === 'system') row.textContent = text;
  else {
    const label = document.createElement('div'); label.className = 'who'; label.textContent = role === 'user' ? 'You' : 'Assistant';
    const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = text;
    row.append(label, bubble);
  }
  $('messages').append(row); $('messages').scrollTop = $('messages').scrollHeight;
}
function render() {
  $('read-reply').hidden = !hasReply || !config.tts;
  $('read-reply').disabled = busy;
  $('quick-checks').hidden = !config.robot;
  $('quick-checks').querySelectorAll('button').forEach(button=>button.disabled=busy);
  $('send').disabled = !config.configured || busy || !$('prompt').value.trim();
  $('mic').hidden = recording; $('voice-state').hidden = !recording;
  $('mic').disabled = !config.configured || !config.stt || busy;
  $('end-text-chat').hidden = !sid || recording;
  $('end-text-chat').disabled = busy;
  $('end-chat').hidden = true;
  $('voice-label').textContent = speaking ? 'Microphone paused' : 'Listening';
  $('end-chat').disabled = false;
}
async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-UI-Token': config.token, ...options.headers}});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return response;
}
const postJSON = (path, body) => request(path, {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
function stopAudio() {
  audioGeneration++;
  playbackAbort?.abort(); playbackAbort = null;
  for (const source of sources) { try { source.stop(); } catch {} }
  sources.clear();
}
async function speak() {
  stopAudio();
  const mic = connection;
  speaking = true; render();
  try {
    if (recording && mic) {
      // The SDK opens its socket before microphone permission/setup finishes.
      let muted = false;
      for (let attempt=0; attempt<20 && connection===mic; attempt++) {
        try { mic.mute(); muted=true; break; }
        catch { await new Promise(resolve=>setTimeout(resolve,100)); }
      }
      if (!muted) throw new Error('Microphone is not ready for safe playback. Reconnect voice and allow microphone access.');
    }
  context ||= new AudioContext({sampleRate:16000});
  await context.resume();
  const generation = audioGeneration;
  playbackAbort = new AbortController();
  const response = await request('/api/speak-stream', {method:'POST', signal:playbackAbort.signal,
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:sid})});
  const reader = response.body.getReader();
  let pending = new Uint8Array(), next = context.currentTime + .06;
  status('Speaking', 'live');
  while (true) {
    const {done, value} = await reader.read();
    if (done || generation !== audioGeneration) break;
    const bytes = new Uint8Array(pending.length + value.length);
    bytes.set(pending); bytes.set(value, pending.length);
    const length = bytes.length - bytes.length % 2;
    pending = bytes.slice(length);
    if (!length) continue;
    const buffer = context.createBuffer(1, length/2, 16000);
    const data = buffer.getChannelData(0), view = new DataView(bytes.buffer);
    for (let i=0;i<data.length;i++) data[i]=view.getInt16(i*2,true)/32768;
    const source=context.createBufferSource(); source.buffer=buffer; source.connect(context.destination);
    sources.add(source); source.onended=()=>sources.delete(source);
    next=Math.max(next,context.currentTime+.02); source.start(next); next+=buffer.duration;
  }
  while (sources.size && generation === audioGeneration) await new Promise(resolve=>setTimeout(resolve,50));
  status(recording ? 'Listening' : 'Ready', recording ? 'live' : '');
  } finally {
    // Let speaker echo decay before capture resumes.
    await new Promise(resolve=>setTimeout(resolve,250));
    if (recording && connection===mic) { try { mic.unmute(); } catch {} }
    speaking=false; render();
  }
}
async function submit(text, voice = false) {
  if (!sid) sid = (await (await request('/api/sessions', {method:'POST'})).json()).session_id;
  message('user', text); status('Thinking…', 'live');
  const poll = setInterval(async()=>{
    try { const state=await (await request('/api/status')).json(); if(state.busy) status(state.message,'live'); } catch {}
  },700);
  let body;
  try { body = await (await postJSON('/api/chat', {session_id:sid, text})).json(); }
  finally { clearInterval(poll); }
  message('assistant', body.text); hasReply=true; render(); status('Ready');
  if (voice && config.tts) {
    try { await speak(); }
    catch (error) { if(error.name==='AbortError') return; message('system', `Reply received, but speech failed: ${error.message}`); status('Reply ready', 'warn'); }
  }
}
function fail(error) { status('Request failed', 'warn'); hint(error.message, true); message('system', error.message); }
async function send() {
  const text = $('prompt').value.trim();
  if (!text || busy || !config.configured) return;
  busy = true; stopAudio(); render();
  try { await submit(text, recording); $('prompt').value = ''; $('prompt').style.height = 'auto'; }
  catch (error) { fail(error); }
  finally { busy = false; render(); }
}
function releaseMic() {
  connection?.close(); connection=null; recording=false; render();
}
async function robotStop() {
  stopAudio();
  try { const result=await (await request('/api/stop',{method:'POST'})).json(); message('system',result.text); hint(result.text); }
  catch(error) { fail(error); }
}
async function voiceTurn(text) {
  if (!/[\p{L}\p{N}]/u.test(text) || !recording || speaking) return;
  if (/^(?:please\s+)?(?:stop|stop robot|stop the robot|cancel|halt)[.!?]?$/i.test(text.trim())) {
    message('user',text); await robotStop(); return;
  }
  if (busy) { message('system','Robot task is active; that request was not queued. Say “stop” to cancel.'); return; }
  busy=true; stopAudio(); render();
  try { await submit(text,true); }
  catch(error) { fail(error); }
  finally { busy=false; render(); }
}
async function startRecording() {
  if (busy || recording || !config.stt) return;
  busy=true; render(); status('Connecting microphone…');
  try {
    context ||= new AudioContext({sampleRate:16000}); await context.resume();
    const {token}=await (await request('/api/speech-token',{method:'POST'})).json();
    connection=Scribe.connect({token, modelId:'scribe_v2_realtime', commitStrategy:CommitStrategy.VAD,
      vadSilenceThresholdSecs:.8, microphone:{echoCancellation:true,noiseSuppression:true}});
    recording=true;
    connection.on(RealtimeEvents.SESSION_STARTED,()=>{ status('Listening','live'); hint('Speak naturally, then pause. Say “stop” or press Stop robot to cancel a task. Microphone pauses during spoken replies to prevent feedback.'); });
    connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT,({text})=>{ if(text && !speaking) hint(text); });
    connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT,({text})=>void voiceTurn(text));
    connection.on(RealtimeEvents.ERROR,()=>{ releaseMic(); fail(new Error('Live speech disconnected. Check microphone permission, credits, and connection; then reconnect.')); });
    connection.on(RealtimeEvents.CLOSE,(event)=>{ recording=false; connection=null; render(); status('Microphone disconnected'); hint(`Live speech closed (code ${event.code}). Press Start live voice to reconnect.`); });
  } catch(error) { releaseMic(); fail(error); }
  finally { busy=false; render(); }
}
function stopRecording() { releaseMic(); stopAudio(); hint('Microphone off. Use Stop robot to cancel an active robot task.'); }
async function endChat() {
  if (busy) return;
  busy = true; render(); stopAudio();
  try { if (sid) await request(`/api/sessions/${sid}`, {method:'DELETE'}); sid = null; hasReply=false; message('system', 'Chat ended. Your next message starts a new conversation.'); status('Ready'); }
  catch (error) { fail(error); }
  finally { busy = false; render(); }
}
$('end-chat').addEventListener('click',robotStop);
$('robot-stop').addEventListener('click',robotStop);
$('read-reply').addEventListener('click',async()=>{ if(busy)return; busy=true;render();try {await speak();} catch(error){if(error.name!=='AbortError')fail(error);}finally{busy=false;render();} });

$('mic').addEventListener('click', startRecording);
$('cancel-voice').addEventListener('click', stopRecording);
$('end-text-chat').addEventListener('click', endChat);
$('send').addEventListener('click', send);
$('prompt').addEventListener('input', () => { $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min($('prompt').scrollHeight,180)}px`; render(); });
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });
window.addEventListener('pagehide', () => { releaseMic(); stopAudio(); if (busy) void request('/api/stop', {method:'POST',keepalive:true}).catch(()=>{}); });
$('waveform').innerHTML = Array.from({length:40}, () => '<i></i>').join('');
try {
  const response = await fetch('/api/config'); if (!response.ok) throw new Error('Could not reach the local server.');
  config = await response.json();
  for (const check of config.quick_checks || []) {
    const button=document.createElement('button'); button.textContent=check.name;button.title=check.description;
    button.addEventListener('click',async()=>{
      if(busy)return;busy=true;render();
      try {context ||= new AudioContext({sampleRate:16000});await context.resume();await submit(check.command,config.tts);}
      catch(error){fail(error);}finally{busy=false;render();}
    });
    $('quick-checks').append(button);
  }
  status(config.configured ? 'Ready' : 'Setup needed', config.configured ? '' : 'warn');
  hint(!config.configured ? 'Install Codex CLI and sign in locally, then restart this server.' : !config.stt ? 'Text chat is ready. Configure ElevenLabs to enable voice messages.' : !config.tts ? 'Voice input is ready. Configure a voice ID for spoken replies.' : (config.robot ? 'Robot control enabled. Start voice to speak a request; replies play automatically.' : 'Start voice for continuous conversation. Robot control is disabled.'));
} catch (error) { fail(error); }
render();
