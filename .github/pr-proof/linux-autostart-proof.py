"""Exercise release-to-current autostart preservation with real Linux desktop and CLI payloads.

Usage: python3 .github/pr-proof/linux-autostart-proof.py STABLE_DESKTOP_DIR CLI CURRENT_ARCHIVE_DIR
Run from the PR checkout. See the PR body for download and packaging commands.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

stable, cli, current = (Path(value).resolve() for value in sys.argv[1:])
repo = Path(__file__).resolve().parents[2]
assert (current / 'Integrations/Linux/install.py').read_bytes() == (repo / 'Integrations/Linux/install.py').read_bytes()


def run(command, environment, working):
    result = subprocess.run([str(value) for value in command], env=environment, cwd=working,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def app_status(app, environment, working):
    with (working / 'app.log').open('w') as log:
        process = subprocess.Popen([str(app), '--background', '--no-tray'], env=environment,
                                   cwd=working, stdout=log, stderr=log)
        try:
            for _ in range(100):
                assert process.poll() is None, (working / 'app.log').read_text()
                result = subprocess.run([str(app), '--snapshot'], env=environment, cwd=working,
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError('Desktop IPC did not start')
            assert json.loads(run([app, '--configure', '{"quotaDisplay":"used","refreshSeconds":900}'],
                                  environment, working))['ok']
            snapshot = json.loads(run([app, '--snapshot'], environment, working))
            assert snapshot['quotaDisplay'] == 'used'
            status = json.loads(run([app, '--autostart', 'status'], environment, working))
            assert status['ok']
            return status['enabled']
        finally:
            subprocess.run([str(app), '--quit'], env=environment, cwd=working, capture_output=True, timeout=5)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            assert process.returncode == 0, (working / 'app.log').read_text()


print('Real-payload autostart upgrade proof: published v0.78.0 -> current installer')
print('CLI:', subprocess.check_output([str(cli), '--version'], text=True).strip())
print('Current archive installer matches PR source byte-for-byte')
for title, entry, enabled in [
    ('disabled with whitespace', 'Hidden = true\n', False),
    ('enabled with comment', '# Hidden=true disables startup\nHidden=false\n', True),
]:
    with tempfile.TemporaryDirectory(prefix='codexbar-autostart-proof-') as temporary:
        root = Path(temporary)
        home, working, runtime = root / 'home', root / 'working', root / 'runtime'
        working.mkdir()
        runtime.mkdir(mode=0o700)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                       'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_RUNTIME_DIR': str(runtime),
                       'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software'}
        startup = home / '.config/autostart/com.steipete.CodexBar.desktop'
        preferences = home / '.config/codexbar/linux.json'
        app = home / '.local/bin/codexbar-linux'
        run(['python3', stable / 'Integrations/Linux/install.py', '--cli', cli], environment, working)
        settings = json.loads(preferences.read_text())
        # Startup usage rejects a fictitious provider before any account probe.
        settings.update(provider='fixture-offline', showCosts=False, notifications=False)
        preferences.write_text(json.dumps(settings))
        original = startup.read_text().replace('Hidden=false\n', entry)
        startup.write_text(original)
        print('CASE:', title)
        print('  stable app:', run([app, '--version'], environment, working))
        before_enabled = app_status(app, environment, working)
        assert before_enabled == enabled
        before_settings = json.loads(preferences.read_text())
        print(f'  before reinstall, real app reports enabled={before_enabled}')
        run(['python3', stable / 'Integrations/Linux/install.py', '--cli', cli], environment, working)
        broken_enabled = app_status(app, environment, working)
        assert broken_enabled != enabled
        print(f'  after shipped v0.78.0 reinstall, real app reports enabled={broken_enabled}: BUG reproduced')
        startup.write_text(original)
        before_bytes = preferences.read_bytes()
        backups_before = set(preferences.parent.glob('linux.json.backup-*'))
        run(['python3', current / 'Integrations/Linux/install.py', '--cli', cli], environment, working)
        assert json.loads(preferences.read_text()) == before_settings
        new_backups = set(preferences.parent.glob('linux.json.backup-*')) - backups_before
        assert len(new_backups) == 1 and next(iter(new_backups)).read_bytes() == before_bytes
        assert f'Hidden={str(not enabled).lower()}' in startup.read_text().splitlines()
        assert (home / '.local/share/applications/com.steipete.CodexBar.desktop').is_file()
        assert hashlib.sha256(app.read_bytes()).digest() == hashlib.sha256((stable / 'bin/codexbar-linux').read_bytes()).digest()
        fixed_enabled = app_status(app, environment, working)
        assert fixed_enabled == enabled
        assert json.loads(preferences.read_text()) == before_settings
        print(f'  after current archive reinstall, real app reports enabled={fixed_enabled}: PASS')
        print('  all settings preserved; backup byte-identical; launcher present; actual release binaries retained')
