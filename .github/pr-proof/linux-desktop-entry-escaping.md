# Linux desktop entry escaping proof

Verified on Linux x86_64 with Python 3.13.5 and GIO 2.84.4.
Baseline: `eb7d060e4d932883737ee79fbb7dd4bd817ecba0`.

## Cause and coverage

The installer escaped command arguments, but omitted the desktop entry string
escaping applied before command parsing. Dollar signs, backticks, and double
quotes in the home directory made installed launcher and autostart entries fail
to launch. The repair doubles the argument's backslashes for the outer string
layer, as required by the [Desktop Entry specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).

The serialization regression runs the actual installer with synthetic homes and
checks all four generated Exec commands: usage, settings, spending, and autostart.
It covers spaces, dollar signs, backticks, double quotes, backslashes, and the
existing percent escaping.

The runtime regression installs a recording executable into a synthetic home
containing spaces, dollar signs, a backtick, a double quote, and a backslash. GIO
launches both generated desktop entries. The test checks the executable's receipt
for its exact installed path and the expected `--usage` or `--background` argument.
Receipts are renamed into place after writing to avoid partial reads.

The runtime test is skipped when `gio` is unavailable. It ran without skipping
on the verification host. All test files and installations use temporary
directories; no provider credentials or real application processes are involved.

## Before

Both new tests were run against a temporary copy of the unmodified baseline
installer, using the current test file and the repository icon:

```text
test_desktop_commands_escape_special_characters_in_the_home_path
  FAIL: has$cash
  FAIL: has`tick
  FAIL: has"quote
  FAIL: has\slash
test_desktop_entries_launch_the_installed_binary_with_special_home_characters
  FAIL: --usage
  FAIL: --background
  gio: Desktop file didn't specify Exec field

Ran 2 tests in 0.393s
FAILED (failures=6)
```

Reproduce from this PR checkout in Bash without changing the working tree:

```bash
(
proof_root=$(mktemp -d)
trap 'rm -rf "$proof_root"' EXIT
mkdir -p "$proof_root/Integrations/Linux" "$proof_root/Integrations/Omarchy"
git show eb7d060e4d932883737ee79fbb7dd4bd817ecba0:Integrations/Linux/install.py > "$proof_root/Integrations/Linux/install.py"
cp Integrations/Linux/icon.svg "$proof_root/Integrations/Linux/"
cp Integrations/Omarchy/test_install.py "$proof_root/Integrations/Omarchy/"
python3 "$proof_root/Integrations/Omarchy/test_install.py" \
  InstallTests.test_desktop_commands_escape_special_characters_in_the_home_path \
  InstallTests.test_desktop_entries_launch_the_installed_binary_with_special_home_characters
)
```

## After

```text
$ python3 -m unittest -v Integrations.Omarchy.test_install Integrations.Linux.tests.test_package
Ran 13 tests in 3.207s
OK

$ node --test Integrations/Omarchy/test.mjs Integrations/Omarchy/notifications.test.mjs
tests 94
pass 94
fail 0
skipped 0

$ git diff --check
exit 0
```

## Repository check limitation

`nice -n 10 make check` passed the initial localization checks, then stopped in
the pre-existing CLI installer regression on this Linux host:

```text
AssertionError: The installer regression test requires macOS AppleScript.
make: *** [Makefile:26: check] Error 1
```

The complete repository check is not claimed as passing. No Swift sources changed;
no Swift build or full Swift suite was run on the Intel N95.
