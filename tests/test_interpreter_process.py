"""Exercise the real launcher/child pipe failure without model or robot calls."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest
import task_interpreter as module


@pytest.mark.skipif(os.name != 'posix', reason='Station runtime is POSIX')
def test_timeout_reaps_launcher_and_child_that_inherits_output(monkeypatch, tmp_path):
    launcher = tmp_path/'codex'
    launcher.write_text(f'#!{sys.executable}\n' + '''import subprocess,sys,time,json,os
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
Path('owned-pids.json').write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(5)
''')
    launcher.chmod(0o755)
    monkeypatch.setenv('PATH',str(tmp_path)+os.pathsep+os.environ['PATH'])
    monkeypatch.setattr(module,'INTERPRETER_TIMEOUT_SECONDS',1,raising=False)
    (tmp_path/'INSTRUCTIONS.md').write_text('Return a task.')
    started=time.monotonic()
    try:
        with pytest.raises(RuntimeError,match='timed out'):
            asyncio.run(asyncio.wait_for(module.interpret('Look',{'objects':[]},[],tmp_path),3))
        assert time.monotonic()-started < 2, 'Timeout cleanup waited on inherited child pipes'
        child=json.loads((tmp_path/'owned-pids.json').read_text())[1]
        with pytest.raises(ProcessLookupError): os.kill(child,0)
    finally:
        if (tmp_path/'owned-pids.json').exists():
            for pid in json.loads((tmp_path/'owned-pids.json').read_text()):
                try: os.kill(pid,signal.SIGKILL)
                except ProcessLookupError: pass
