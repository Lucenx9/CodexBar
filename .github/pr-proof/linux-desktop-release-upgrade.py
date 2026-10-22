"""Run with xvfb-run and a checksum-verified, extracted v0.79.0 desktop archive."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

repo = Path(__file__).resolve().parents[2]
release = Path(sys.argv[1]).resolve()
screenshot = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None

with tempfile.TemporaryDirectory(prefix='codexbar-release-proof-') as temporary:
    root = Path(temporary)
    home = root / 'home %f= $cash`tick"quote\\slash'
    home.mkdir()
    runtime = root / 'runtime'
    runtime.mkdir(mode=0o700)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(root / 'config'),
               XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state'),
               XDG_CACHE_HOME=str(root / 'cache'), XDG_RUNTIME_DIR=str(runtime),
               QT_QPA_PLATFORM='xcb', QT_QUICK_BACKEND='software')
    fake = root / 'fixture-cli'
    fake.write_text('''#!/usr/bin/env python3
import json,sys
if sys.argv[1] == 'config':
    print(json.dumps([{'provider':'codex','displayName':'Codex'}]))
else:
    print(json.dumps([{'provider':'codex','usage':{'primary':{'usedPercent':40,'windowMinutes':300}}}]))
''')
    fake.chmod(0o755)
    binary = release / 'bin/codexbar-linux'
    installed = home / '.local/bin/codexbar-linux'
    preferences = root / 'config/codexbar/linux.json'
    startup = root / 'config/autostart/com.steipete.CodexBar.desktop'
    launcher = root / 'data/applications/com.steipete.CodexBar.desktop'

    def run(*args, check=True):
        return subprocess.run([str(arg) for arg in args], env=env, capture_output=True,
                              text=True, timeout=15, check=check)

    def ready():
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            result = run(installed, '--snapshot', check=False)
            if result.returncode == 0:
                value = json.loads(result.stdout)
                if value.get('summary') == 'CX 60%' and not value.get('busy'):
                    return value
            time.sleep(0.05)
        raise AssertionError('The installed desktop did not return fixture usage over IPC')

    def stop():
        run(installed, '--quit', check=False)
        deadline = time.monotonic() + 5
        while (runtime / 'codexbar-linux/desktop.lock').exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not (runtime / 'codexbar-linux/desktop.lock').exists(), 'Desktop did not exit'

    print('Official release:', run(binary, '--version').stdout.strip(), flush=True)
    run('python3', release / 'Integrations/Linux/install.py', '--cli', fake, '--no-autostart')
    settings = json.loads(preferences.read_text())
    settings.update(provider='codex', refreshSeconds=900, showIdentity=False, showTray=False,
                    showCosts=False, showStatus=False, notifications=False, quotaDisplay='remaining')
    preferences.write_text(json.dumps(settings, indent=2) + '\n')
    assert 'Hidden=true' in startup.read_text()
    baseline = run('gio', 'launch', launcher, check=False)
    assert baseline.returncode != 0
    print('v0.79.0 launcher before upgrade: FAIL as expected, GIO rejected Exec', flush=True)
    with (root / 'desktop.log').open('w+') as log:
        process = subprocess.Popen([str(installed), '--background'], env=env, stdout=log, stderr=log)
        try:
            ready()
            print('v0.79.0 installed app loads existing preferences: PASS, CX 60%', flush=True)
        finally:
            stop()
            process.wait(timeout=5)
        saved = json.loads(preferences.read_text())
        run('python3', repo / 'Integrations/Linux/install.py', '--binary', binary)
        assert json.loads(preferences.read_text()) == saved
        backups = sorted(preferences.parent.glob('linux.json.backup-*'))
        assert any(json.loads(path.read_text()) == saved for path in backups)
        assert 'Hidden=true' in startup.read_text()
        print('Upgrade: existing preferences, backup, and disabled autostart preserved: PASS', flush=True)
        for entry, label in [(launcher, 'launcher'), (startup, 'autostart')]:
            try:
                subprocess.run(['gio', 'launch', str(entry)], env=env, stdout=log, stderr=log,
                               timeout=10, check=True)
                snapshot = ready()
                pid = snapshot['pid']
                assert Path(f'/proc/{pid}/exe').resolve() == installed
                print(f'After upgrade, GIO {label}: PASS, actual installed Qt app, IPC CX 60%', flush=True)
                assert json.loads(preferences.read_text()) == saved
                assert 'Hidden=true' in startup.read_text()
                if label == 'launcher':
                    tree = run('xwininfo', '-root', '-tree').stdout
                    assert 'Usage & Spend' in tree
                    if screenshot:
                        run('import', '-window', 'root', screenshot)
                    print('Actual Usage & Spend window on Xvfb display: PASS', flush=True)
            finally:
                stop()
        log.flush()
        log.seek(0)
        output = log.read()
        for error in ['ReferenceError', 'TypeError', 'failed to load', 'Cannot assign', 'Unable to assign']:
            assert error not in output, output.replace(str(root), '<FIXTURE>')
    print('Final preferences unchanged and Hidden=true: PASS', flush=True)
    print('No live providers; temporary HOME/XDG paths, official desktop binary, synthetic CLI only.', flush=True)
