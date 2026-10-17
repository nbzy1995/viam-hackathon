import { Scribe, CommitStrategy, RealtimeEvents } from '@elevenlabs/client';
// Jerry's Ringside UI, adapted to the local Codex harness and direct speech APIs.
const $ = id => document.getElementById(id);
let config = {}, sid = null, busy = false, recording = false, speaking = false, hasReply = false;
let connection = null, context = null, playbackAbort = null, sources = new Set(), audioGeneration = 0;
let lastReply = '', cancelDeviceSpeech = null;
const deviceSpeechAvailable = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
const canSpeak = () => config.tts || deviceSpeechAvailable;

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
  $('quick-checks').hidden = !config.robot;
  $('read-reply').hidden = !hasReply || !canSpeak();
  $('read-reply').disabled = busy;
  $('voice-replies').disabled = !canSpeak();
  $('reply-voice').disabled = speaking;
  $('stop-audio').hidden = !speaking;
  $('cancel-voice').hidden = !recording;
  $('robot-stop').hidden = !config.robot;
  $('send').disabled = !config.configured || busy || !$('prompt').value.trim();
  $('mic').hidden = recording; $('voice-state').hidden = !recording;
  $('mic').disabled = !config.configured || !config.stt || busy;
  $('end-text-chat').hidden = !sid || recording;
  $('end-text-chat').disabled = busy;
  $('end-chat').hidden = true;
  $('voice-label').textContent = speaking ? 'Microphone paused' : busy ? 'Working · say stop to cancel' : 'Listening';
  $('end-chat').disabled = false;
  $('waveform').classList.toggle('paused', speaking || busy);
}
async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-UI-Token': config.token, ...options.headers}});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || `Request failed (${response.status}).`);
    error.code = body.detail?.code;
    throw error;
  }
  return response;
}
const postJSON = (path, body) => request(path, {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
function stopAudio() {
  audioGeneration++;
  cancelDeviceSpeech?.();
  playbackAbort?.abort(); playbackAbort = null;
  for (const source of sources) { try { source.stop(); } catch {} }
  sources.clear();
}
function speakOnDevice(text) {
  if (!deviceSpeechAvailable) throw new Error('Device voice is unavailable in this browser. Increase the ElevenLabs key credit limit to restore speech.');
  return new Promise((resolve, reject) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = /[\u3400-\u9fff]/u.test(text) ? 'zh-CN' : 'en-US';
    let timer, settled=false;
    const finish = error => { if(settled)return; settled=true; clearTimeout(timer); cancelDeviceSpeech=null; error ? reject(error) : resolve(); };
    cancelDeviceSpeech = () => { finish(new DOMException('Playback stopped', 'AbortError')); window.speechSynthesis.cancel(); };
    utterance.onstart = () => { clearTimeout(timer); status('Speaking · device voice', 'live'); };
    utterance.onend = () => finish();
    utterance.onerror = event => finish(new Error(`Device voice failed (${event.error}). Check browser audio permission or use ElevenLabs after restoring credits.`));
    timer=setTimeout(() => { finish(new Error('Device voice did not start. Check browser audio permission or restore ElevenLabs credits.')); window.speechSynthesis.cancel(); }, 8000);
    window.speechSynthesis.speak(utterance);
  });
}
async function speak() {
  stopAudio();
  const mic = connection;
  const generation = audioGeneration;
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
  if ($('reply-voice').value === 'device') { await speakOnDevice(lastReply); return; }
  context ||= new AudioContext({sampleRate:16000});
  await context.resume();
  if (generation !== audioGeneration) return;
  playbackAbort = new AbortController();
  let response;
  try {
    response = await request('/api/speak-stream', {method:'POST', signal:playbackAbort.signal,
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:sid})});
  } catch (error) {
    if (error.code !== 'speech_quota_exceeded' || !deviceSpeechAvailable) throw error;
    $('reply-voice').value='device';
    hint('ElevenLabs key credit limit reached. Using device voice for replies.', true);
    await speakOnDevice(lastReply); return;
  }
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
    status(recording ? 'Listening' : 'Ready', recording ? 'live' : '');
  }
}
async function submit(text) {
  if (!sid) sid = (await (await request('/api/sessions', {method:'POST'})).json()).session_id;
  message('user', text); status('Thinking…', 'live');
  const poll = setInterval(async()=>{
    try { const state=await (await request('/api/status')).json(); if(state.busy) status(state.message,'live'); } catch {}
  },700);
  let body;
  try { body = await (await postJSON('/api/chat', {session_id:sid, text})).json(); }
  finally { clearInterval(poll); }
  message('assistant', body.text); lastReply=body.text; hasReply=true; render(); status('Ready');
  if ($('voice-replies').checked && canSpeak()) {
    try { await speak(); }
    catch (error) { if(error.name==='AbortError') return; message('system', `Reply received, but speech failed: ${error.message}`); status('Reply ready', 'warn'); }
  }
}
function fail(error) { status('Request failed', 'warn'); hint(error.message, true); message('system', error.message); }
async function send() {
  const text = $('prompt').value.trim();
  if (!text || busy || !config.configured) return;
  if ($('voice-replies').checked && config.tts) { context ||= new AudioContext({sampleRate:16000}); await context.resume(); }
  busy = true; stopAudio(); render();
  try { await submit(text); $('prompt').value = ''; $('prompt').style.height = 'auto'; }
  catch (error) { fail(error); }
  finally { busy = false; render(); }
}
function releaseMic() {
  const old = connection; connection=null; recording=false; old?.close();
  $('transcript').hidden=true; render();
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
  if (busy) { message('system',config.robot ? 'Robot task is active; that request was not queued. Say “stop” to cancel.' : 'Still working on your previous message; please wait for the reply.'); return; }
  busy=true; stopAudio(); render();
  try { await submit(text); }
  catch(error) { fail(error); }
  finally { busy=false; render(); }
}
async function startRecording() {
  if (busy || recording || !config.stt) return;
  busy=true; render(); status('Connecting microphone…');
  try {
    context ||= new AudioContext({sampleRate:16000}); await context.resume();
    const {token}=await (await request('/api/speech-token',{method:'POST'})).json();
    const session=Scribe.connect({token, modelId:'scribe_v2_realtime', commitStrategy:CommitStrategy.VAD,
      vadSilenceThresholdSecs:.8, microphone:{echoCancellation:true,noiseSuppression:true}});
    connection=session; recording=true;
    session.on(RealtimeEvents.SESSION_STARTED,()=>{ if(connection!==session)return; status('Listening','live'); hint(config.robot ? 'Speak naturally, then pause. Say “stop” to cancel a task. Microphone pauses during spoken replies.' : 'Speak naturally, then pause. Microphone pauses during spoken replies. Robot control is disabled.'); });
    session.on(RealtimeEvents.PARTIAL_TRANSCRIPT,({text})=>{ if(connection===session && text && !speaking) { $('transcript').hidden=false; $('transcript').textContent=text; } });
    session.on(RealtimeEvents.COMMITTED_TRANSCRIPT,({text})=>{ if(connection===session) { $('transcript').hidden=true; void voiceTurn(text); } });
    session.on(RealtimeEvents.ERROR,()=>{ if(connection!==session)return; releaseMic(); fail(new Error('Live speech disconnected. Check microphone permission, credits, and connection; then reconnect.')); });
    session.on(RealtimeEvents.CLOSE,(event)=>{ if(connection!==session)return; releaseMic(); status('Microphone disconnected'); hint(`Live speech closed (code ${event.code}). Press Start live voice to reconnect.`); });
  } catch(error) { releaseMic(); fail(error); }
  finally { busy=false; render(); }
}
function stopRecording() { releaseMic(); stopAudio(); status(busy ? 'Working…' : 'Ready'); hint(config.robot ? 'Microphone off. Use Stop robot to cancel an active robot task.' : 'Microphone off. Type a message or start voice again.'); }
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
$('stop-audio').addEventListener('click', stopAudio);
$('voice-replies').addEventListener('change', () => { if (!$('voice-replies').checked) stopAudio(); });
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
    if (check.suggested === false) continue;
    const suggestion = document.createElement('p');
    suggestion.textContent = `“${check.suggestion || check.command}”`;
    $('quick-checks').append(suggestion);
  }
  $('voice-replies').checked = Boolean(canSpeak());
  if (!config.tts) $('reply-voice').value='device';
  status(config.configured ? 'Ready' : 'Setup needed', config.configured ? '' : 'warn');
  hint(!config.configured ? 'Install Codex CLI and sign in locally, then restart this server.' : !config.stt ? 'Text chat is ready. Configure ElevenLabs to enable voice messages.' : !config.tts ? 'Voice input is ready. Configure a voice ID for spoken replies.' : (config.robot ? 'Robot control enabled. Start voice to speak a request; replies play automatically.' : 'Start voice for continuous conversation. Robot control is disabled.'));
} catch (error) { fail(error); }
render();

// Every image and its boxes share one capture; status freshness is independent.
let dashboardTimer, dashboardClosed = false, displayedFrame = null;
function cameraUnavailable(label) {
  $('camera-badge').textContent=label; $('camera-badge').className='badge';
  $('camera-image').hidden=true; $('camera-boxes').toggleAttribute('hidden',true);
  $('camera-boxes').replaceChildren(); $('camera-placeholder').hidden=false;
  $('camera-empty-text').textContent=label === 'Paused' ? 'Another controller is using the robot' : 'Waiting for a fresh camera frame';
  $('objects').replaceChildren();
  const item=document.createElement('li'); item.className='none'; item.textContent='Recognition unavailable'; $('objects').append(item);
  $('object-count').textContent='—'; $('vision-updated').textContent='No current recognition data';
  displayedFrame=null;
}
function drawBoxes(data) {
  const svg=$('camera-boxes'), ns='http://www.w3.org/2000/svg';
  svg.replaceChildren(); svg.setAttribute('viewBox', `0 0 ${data.width} ${data.height}`);
  for (const object of data.objects) {
    const [x1,y1,x2,y2]=object.box;
    const color=({blue:'#6fb4ff',red:'#ff8686',yellow:'#ffe07a'})[object.color] || '#8cddad';
    const rect=document.createElementNS(ns,'rect');
    for (const [key,value] of Object.entries({x:x1,y:y1,width:x2-x1,height:y2-y1,stroke:color})) rect.setAttribute(key,value);
    const label=document.createElementNS(ns,'text'); label.setAttribute('x',Math.min(x1+4,Math.max(0,data.width-object.label.length*24))); label.setAttribute('y',y1>50?y1-10:Math.min(data.height-10,y2+45)); label.setAttribute('fill',color); label.textContent=object.label;
    svg.append(rect,label);
  }
  svg.toggleAttribute('hidden',false);
}
async function updateDashboard() {
  try {
    const data=await (await request('/api/dashboard',{signal:AbortSignal.timeout(4000)})).json();
    if(dashboardClosed)return;
    $('robot-badge').textContent=data.paused ? 'Paused' : data.status_fresh ? 'Live' : 'Unavailable';
    $('robot-badge').className=data.status_fresh ? 'badge live' : 'badge';
    $('robot-state').textContent=data.state; $('robot-activity').textContent=data.activity;
    $('robot-telemetry').textContent=data.status_fresh ? `Gripper: ${data.holding ? 'holding an object' : 'empty'} · Updated ${new Date(data.status_updated_at).toLocaleTimeString()}` : 'Waiting for fresh robot readings.';
    $('camera-updated').textContent=data.updated_at ? `Captured ${new Date(data.updated_at).toLocaleTimeString()}` : 'No camera connected';
    if(!data.fresh) { cameraUnavailable(data.paused ? 'Paused' : data.connected ? 'Waiting' : 'Disconnected'); return; }
    if(data.frame !== displayedFrame) {
      const img=new Image(); img.src=`/api/camera/${encodeURIComponent(data.frame)}`;
      await img.decode();
      if(dashboardClosed)return;
      $('camera-image').src=img.src; $('camera-image').hidden=false; $('camera-placeholder').hidden=true;
      drawBoxes(data); displayedFrame=data.frame;
    }
    $('camera-badge').textContent='Live'; $('camera-badge').className='badge live';
    $('objects').replaceChildren();
    for(const label of new Set(data.objects.map(object=>object.label))) {
      const item=document.createElement('li'); item.textContent=label; $('objects').append(item);
    }
    $('object-count').textContent=data.vision_available ? String(data.objects.length) : '—';
    $('vision-updated').textContent=data.vision_available ? `Native color detection · ${data.vision_partial ? 'some detectors unavailable' : 'boxes match this frame'}` : 'Recognition unavailable';
    if(!data.objects.length) { const item=document.createElement('li'); item.className='none'; item.textContent=data.vision_available ? 'No colored regions detected' : 'Waiting for vision data'; $('objects').append(item); }
  } catch {
    cameraUnavailable('Disconnected'); $('robot-badge').textContent='Unavailable'; $('robot-badge').className='badge';
    $('robot-state').textContent='State unavailable'; $('robot-telemetry').textContent=''; $('robot-activity').textContent='Waiting for the local server.';
  } finally { if(!dashboardClosed)dashboardTimer=setTimeout(updateDashboard,250); }
}
void updateDashboard();
window.addEventListener('pagehide',()=>{dashboardClosed=true;clearTimeout(dashboardTimer);});
