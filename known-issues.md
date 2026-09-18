# grep — known issues and technical debt

Tracked list. `grep.py`'s header comment block is the raw scratchpad; anything worth acting on
later should end up here with enough context to act on without rediscovering it.

Test status at last run: **`python test_grep.py` — 44 passed, 0 failed** (py↔cpp parity
asserted on every case). No known failing or skipped tests.

---

## Recently fixed (kept for the record)

### A filespec in the regex slot failed silently (both impls)
`grep -i -l -e math -e logic "d:\book\*.html"` puts the *path* in the positional regex slot
(`argparse` fills `nargs="?"` before `nargs="*"`), leaving no filename pattern at all, so it
searched `*` in the cwd for a nonsense regex and reported nothing. Not detectable by validating
the regex: `\t` in `d:\temp\*` is a legal tab escape in Python, and `std::regex` accepts unknown
escapes like `\m` as literals, so in C++ every Windows path compiles fine. Python *did* error for
`\m` — but with `bad escape \m at position 2`, which points at the regex engine rather than at the
argument slot, and the user reported not understanding it. Fixed by adding `filespec_hit_count()` /
`print_slot_hint()` to both builds: a warning when a positional regex coexists with `-e` patterns
while `files` and `-f` are both empty and the positional glob-matches ≥1 real file, plus the same
hint appended to the compile-error message. See design.md "The argument-slot trap and its
warning". Regression tests: "filespec consumed as the regex".

### `-l` / `-L` with a single pattern reported every file (both impls)
Introduced by the AND-gate change. `all_present_lines()` short-circuited to `true` when there
were fewer than two patterns — correct for `process_full`, whose per-line loop does the real
filtering, but fatal for `-l`/`-L`, where the gate is the *only* match test. `grep -l foo *.txt`
listed every file; `-L` listed none. Missed because every `-l`/`-L` case in the test matrix used
two patterns. Fixed by making the gate always honest and moving the optimisation to the
`process_full` call site. Regression tests: "`-l` / `-L` with one pattern".

### One unrepresentable filename blinded C++ grep to a whole directory
`ld()` built entry names with `fs::path::string()`, which throws on Windows for characters the
active ANSI code page can't encode (e.g. U+22C6 in cp1252). The throw unwound past the entire
search into `main`'s empty `catch (...)`, so the C++ build printed **nothing** for such a
directory — no matches, no "No files matched", no error — and exited 0. Fixed by carrying paths
as UTF-8 (`to_utf8`/`from_utf8`), switching the Windows entry point to `wmain`, setting the
console output code page to UTF-8 for the run, and making the catch-alls report. Regression
tests: "non-ANSI filenames".

### Path-qualified filespec also scanned the current directory
`grep -il centre old\*` returned filenames from the cwd alongside those from `old`. Fixed with
the `had_dir_spec` flag; see design.md "Traversal". Regression tests: "path-qualified filespec".

---

## Environment

### `grep` on the PATH resolves to Embarcadero Turbo GREP, not this tool
**Status:** unresolved, needs a decision that touches system state.

`C:\Program Files (x86)\Embarcadero\Studio\23.0\bin` is Machine-PATH entry **#1**;
`d:\utils` is **#10**. So `grep` runs Embarcadero Turbo GREP 5.6 regardless of what is
installed in `d:\utils`. Turbo GREP interprets `-r` as *"regular expression search"* (default
on) and its recursion flag is `-d`, so `grep -r pattern *.py` exits 0 with non-recursive
results — indistinguishable from "`-r` is ignored". This is the entire cause of the original
`todo.txt` complaint that "the current grep in d:\utils doesn't support -r"; both
implementations here have always supported `-r`/`-R`.

Two fixes, either of which works; both need a decision:
- Move `d:\utils` ahead of the Embarcadero entry in the **Machine** PATH (needs admin,
  trivially reversible).
- Rename Embarcadero's `grep.exe` (may affect Delphi/C++Builder tooling that shells out to it).

Note also that `where grep` run through MSYS/Git bash is misleading — bash injects
`C:\Program Files\Git\usr\bin` early. Read the real PATH with
`[Environment]::GetEnvironmentVariable('Path','Machine')` in PowerShell instead.

---

## Correctness / robustness

### Binary files are decoded as UTF-8, distorting output
GNU grep detects binary files and just reports whether they matched. This tool decodes
everything as UTF-8, so binary content is mangled on screen.
*Proper fix:* detect NUL bytes in the first block and switch to "Binary file X matches"
reporting, matching GNU grep.

### Circular recursion through symlinks is not detected
`-R` follows all symlinks with no cycle detection. A symlink loop will recurse until the OS
path limit stops it.
*Proper fix:* track visited directory identities (inode/`st_ino` on POSIX, file ID via
`GetFileInformationByHandle` on Windows) and skip repeats.

### `-R` reports a symlinked directory more than once
`grep.py -R temp` shows both the symlinked dir `temp` and `temp\temp`.
*Proper fix:* same visited-set as above.

### No sanity check for `-r` together with `-R`
Both accepted silently; the effective behaviour is whichever the traversal code checks first.
*Proper fix:* error out, or document one as taking precedence.

### Out-of-memory paths are untested
`oom()` and the `MemoryError` handling in `all_present_lines` / the read loops have never been
exercised. There is no test that constructs a line large enough to fail allocation.

### Poor error detail on unreadable devices
Wrapping in `try/except` hides useful text: an empty drive produced
`PermissionError: [WinError 21] The device is not ready: 'd:\\'` before the handler was added,
but the handler now prints only "Permission denied".
*Proper fix:* include the OS error string in the message.

### Directories and files are indistinguishable in error messages
An error naming `foo` doesn't say whether `foo` was a file or a directory.

### `--dotall` multiline output is misaligned
The first line of a multi-line match carries the `filename:` prefix; continuation lines do
not, so the block doesn't line up.

### Listing a whole drive (`d:\`) is slow even with no regex
Cause not investigated. Likely per-entry `os.stat` in the traversal;
`os.scandir`/`DirEntry` caches the stat data and would avoid it. Caveat recorded during earlier
investigation: `os.walk` is built on `scandir`, and whether the cache can ever omit files was
never resolved. `os.walk` would also give in-place `dirnames` pruning for `--x_paths` and has a
`follow_symlinks` option.

---

## Missing features

- `grep -f *` prints only filenames; it should print every line of every file.
- No multiline mode short of `--dotall`.
- No option for regex (rather than glob) matching of file and directory names.
- `max_err` is a hardcoded constant with no flag to override it.
- Colour output is not auto-disabled when stdout is redirected to a file. (Detectable:
  `sys.stdout.isatty()` / `_isatty`.)

---

## Interface warts

- `--x_paths` / `--x_files` use underscores where every other long option uses hyphens.
  Renaming to `--x-paths` / `--x-files` would be consistent but breaks existing command lines;
  accept both if changed.
- `--set-colors` requires all six colours in a fixed remembered order. A `name=colour` form
  would be far easier to use.
- Config load/save errors and the (Python-only) colorama notice print at the *top* of the
  scroll, where they scroll away; the end would be more visible.
- Trailing spaces after colour codes in error messages may or may not be wanted — undecided.
- An invalid filespec is not detected up front; the search runs and finds nothing.
- **Chicken-and-egg in colour error reporting:** errors in the `--set-colors` arguments are
  printed using the config file's colours, and config-file errors would ideally be printed
  using `--set-colors`' colours. One has to be processed first, so one of the two cases can't
  use the colours the user just asked for.
- `if args.no_color and not args.allow_match_colors` should force `allow_match_colors = False`
  even when the config file sets it True — currently it doesn't.

---

## Code quality

### Heavy use of module-level globals in `grep.py`
`args`, `c`, `s`, `regexcs`, `before_context`, `after_context`, `max_err` are all module
globals mutated across functions, which is why several helpers need `global`/`nonlocal`.
`grep.cpp` mirrors this with `g_`-prefixed globals.
*Proper fix:* a context object (or class) threaded through `process*`. Sizeable refactor; would
need the full parity matrix green afterwards.

### Leftover scratch files in the working tree
`testdir/proxdemo.txt`, `testdir/proxdemo2.txt`, `testdir/ctx.txt`, `testdir/big.txt` (7.5 MB),
`bugrepro/inner.txt` and `cwdfile.txt` were hand-made while developing the AND gate and the
proximity change. `test_grep.py` now builds equivalent fixtures in a temp directory, so these
are redundant — `big.txt` in particular is 7.5 MB of dead weight. Awaiting a decision on
deleting them.

Older clutter in the same category, predating this work: `out.txt` (1.1 MB of captured output),
`temp/`, `test.txt`, `test.html`, `test.conf`, `testcontext.txt`, and the one-off probe scripts
`test.py`, `test2.py`–`test5.py`, `testperm.py`, `testre.py`, `subpath.py`, `module2.py`,
`grep2.py`, `scraps.2.py`. `grep.exe` (429 KB) and `grep.obj` (2.6 MB) are build artifacts and
would need to be gitignored if the project is ever put under version control.

### Not under version control
The project is not a git repo. History is kept instead as ~70 numbered snapshots in the project
root (`grep.3.py` … `grep.66.unfinished.py`, plus `grep.34.lastworking.py`,
`grep.37.broken.py`, `grep.unknown.py`, `grep.scrap.py`), which is a working substitute for
recovery but not for diffing or bisecting, and it means the C++ port has no history at all.
Note the snapshots stop at 66 while the live `grep.py` has moved well past it, so the numbering
no longer tracks the current file.
*Proper fix:* `git init` with the numbered snapshots either imported as commits or moved into an
`old/` subdirectory. **Not done — this is the user's own snapshot workflow and switching it is
their call.**

---

## Intentional, documented divergences (not bugs)

- `grep.cpp` uses `std::regex` (ECMAScript grammar) rather than Python's `re`. Most patterns
  behave identically, but named groups are `(?<name>...)` instead of `(?P<name>...)`, and
  `std::regex` lacks lookbehind and possessive/atomic groups. A pattern using those will work
  in `grep.py` and fail in `grep.exe`. `test_grep.py` does not currently cover any such
  pattern; adding a case that asserts the *error* is identical would be worthwhile.
- **The two engines disagree about which patterns fail to compile at all**, so the compile-error
  path cannot be parity-tested. ECMAScript treats an unknown escape such as `\m` as the literal
  `m`, while Python's `re` rejects it (`bad escape \m at position 2`). So
  `grep -e math "d:\book\*.html"` errors in Python and succeeds-with-no-results in C++. Only the
  engine-independent argument-slot warning is asserted identical; the wording of the compile
  failure itself is not.
- Colours are enabled on Windows via `SetConsoleMode` in C++ versus `colorama` in Python.
- The `error_printing` / "There were errors printing results. `set PYTHONUTF8=1` to resolve this."
  footer is **Python-only**: C++ writes UTF-8 bytes directly and has no encode step that can
  fail. Since `grep.py` now reconfigures `sys.stdout` to UTF-8 at import, this footer is
  unreachable in any tested configuration — it survives only for streams that can't be
  reconfigured, where `PYTHONUTF8=1` (interpreter-wide UTF-8 mode) genuinely is the fix. It is
  therefore not a parity risk, but it also cannot be regression-tested.
- The config file is `grep.colors.conf` in C++, `grep.py.colors.conf` in Python.
