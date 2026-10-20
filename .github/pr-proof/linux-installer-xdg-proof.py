"""Replay real release-to-PR installer proof. See PR #4661 for archive preparation commands.

Usage: python3 .github/pr-proof/linux-installer-xdg-proof.py /path/to/prepared-archives
Runs only in fresh contained homes with a fictitious provider, without real account access.
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

root = Path(sys.argv[1]).resolve()
stable = next((root / 'stable').iterdir())
current = next((root / 'current').iterdir())
cli = root / 'cli/codexbar'
repo = Path(__file__).resolve().parents[2]
assert (current / 'Integrations/Linux/install.py').read_bytes() == (repo / 'Integrations/Linux/install.py').read_bytes()

def run(args, env, cwd):
    result = subprocess.run([str(arg) for arg in args], env=env, cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()

def runtime(app, env, cwd, configure=None):
    with (cwd / 'runtime.log').open('w') as log:
        process = subprocess.Popen([str(app), '--background', '--no-tray'], env=env, cwd=cwd, stdout=log, stderr=log)
        try:
            for _ in range(100):
                assert process.poll() is None, (cwd / 'runtime.log').read_text()
                result = subprocess.run([str(app), '--snapshot'], env=env, cwd=cwd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError('Desktop IPC did not start')
            if configure:
                assert json.loads(run([app, '--configure', json.dumps(configure)], env, cwd))['ok']
            snapshot = json.loads(run([app, '--snapshot'], env, cwd))
            autostart = json.loads(run([app, '--autostart', 'status'], env, cwd))
            assert snapshot['quotaDisplay'] == 'used', snapshot
            assert autostart == {'enabled': False, 'ok': True}, autostart
            print('  real app IPC: quotaDisplay=used; autostart enabled=false')
        finally:
            subprocess.run([str(app), '--quit'], env=env, cwd=cwd, capture_output=True, timeout=5)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            assert process.returncode == 0, (cwd / 'runtime.log').read_text()
    (cwd / 'runtime.log').unlink()

print('Real payload proof: stable v0.78.0 -> PR CI artifact at ba54a38')
print('CLI:', subprocess.check_output([str(cli), '--version'], text=True).strip())
print('Current packaged installer matches PR source byte-for-byte')
for value in ['', 'relative']:
    case = Path(tempfile.mkdtemp(prefix='empty-' if not value else 'relative-', dir=root))
    home, working = case / 'home', case / 'working'
    working.mkdir(parents=True)
    runtime_dir = case / 'runtime'
    runtime_dir.mkdir(mode=0o700)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'XDG_RUNTIME_DIR': str(runtime_dir),
           'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software',
           'CODEXBAR_SUPPRESS_TEST_KEYCHAIN_ACCESS': '1'}
    print(f'CASE XDG_CONFIG_HOME={value!r}, XDG_DATA_HOME={value!r}')
    print('  install v0.78.0 with default XDG directories and --no-autostart')
    run(['python3', stable / 'Integrations/Linux/install.py', '--cli', cli, '--no-autostart'], env, working)
    preferences = home / '.config/codexbar/linux.json'
    # A fictitious provider makes startup usage exit at argument validation, without an account probe.
    settings = json.loads(preferences.read_text())
    settings.update(provider='fixture-offline', showCosts=False, notifications=False)
    preferences.write_text(json.dumps(settings))
    app = home / '.local/bin/codexbar-linux'
    print('  stable binary:', run([app, '--version'], env, working))
    runtime(app, env, working, {'refreshSeconds': 900, 'quotaDisplay': 'used', 'resetDisplay': 'absolute'})
    before = json.loads(preferences.read_text())
    before_hash = hashlib.sha256(preferences.read_bytes()).hexdigest()
    assert before['refreshSeconds'] == 900 and before['resetDisplay'] == 'absolute'
    startup = home / '.config/autostart/com.steipete.CodexBar.desktop'
    assert 'Hidden=true' in startup.read_text()
    before_backups = set(preferences.parent.glob('linux.json.backup-*'))
    invalid_env = dict(env, XDG_CONFIG_HOME=value, XDG_DATA_HOME=value)
    print('  run unchanged v0.78.0 installer with invalid XDG overrides:')
    run(['python3', stable / 'Integrations/Linux/install.py', '--cli', cli], invalid_env, working)
    wrong = sorted(path.relative_to(working).as_posix() for path in working.rglob('*') if path.is_file())
    assert wrong, 'Stable installer did not reproduce the bug'
    print('    misplaced files:', json.dumps(wrong))
    # Preserve the stable install in HOME, discard only the contained wrong-directory reproduction.
    for child in working.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    print('  upgrade using PR CI archive installer + real desktop payload:')
    print('   ', run(['python3', current / 'Integrations/Linux/install.py', '--cli', cli], invalid_env, working).replace(str(root), '<PROOF_ROOT>'))
    after = json.loads(preferences.read_text())
    assert after == before
    backups = set(preferences.parent.glob('linux.json.backup-*')) - before_backups
    assert len(backups) == 1
    assert json.loads(next(iter(backups)).read_text()) == before
    assert hashlib.sha256(next(iter(backups)).read_bytes()).hexdigest() == before_hash
    assert 'Hidden=true' in startup.read_text()
    expected = ['.config/codexbar/linux.json', '.config/autostart/com.steipete.CodexBar.desktop',
                '.local/share/applications/com.steipete.CodexBar.desktop', '.local/share/icons/hicolor/scalable/apps/codexbar.svg']
    assert all((home / path).is_file() for path in expected)
    assert list(working.iterdir()) == []
    print('  preferences semantically unchanged; backup byte-for-byte matches; Hidden=true preserved')
    print('  installed HOME paths:', json.dumps(expected))
    print('  installer working directory: empty')
    print('  upgraded binary:', run([app, '--version'], env, working))
    # Confirm the real app also finds the preserved settings with the same invalid overrides.
    runtime(app, invalid_env, working)
    assert list(working.iterdir()) == []
    print('  PASS')
    shutil.rmtree(case)
