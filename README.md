# grep — fast file search tool

A command-line file search tool with regex support, recursive directory traversal, proximity matching, context lines, and configurable colored output.

C++ port of `grep.py`.

## Building

**MSVC (Visual Studio):**
```
cl /std:c++17 /EHsc /O2 grep.cpp /Fe:grep.exe
```

**GCC:**
```
g++ -std=c++17 -O2 -o grep grep.cpp
```

**Clang:**
```
clang++ -std=c++17 -O2 -o grep grep.cpp
```

Or just run `build.bat` on Windows, which sets up the MSVC environment, compiles, and
deploys the result to `d:\utils\grep.exe` (skipping the copy if the compile failed).
`d:\utils\greppy.bat` launches the Python implementation, so both are reachable from
anywhere.

Requires C++17 for `<filesystem>` support.

> **Windows PATH gotcha.** If `grep -r` seems to ignore `-r`, you are probably not running this
> tool. Embarcadero Turbo GREP ships in `C:\Program Files (x86)\Embarcadero\Studio\23.0\bin`,
> which sits ahead of `d:\utils` in the Machine PATH; it reads `-r` as "regular expression
> search" and uses `-d` for recursion, so it accepts the flag and quietly returns
> non-recursive results. Check with `where grep` from **cmd** (not Git bash, which injects its
> own path entries). See `known-issues.md`.

## Tests

```
python test_grep.py          # python + c++ parity
python test_grep.py --py-only # skip the C++ build
python test_grep.py -v        # also print each command's output
```

`test_grep.py` builds fixtures in a temp directory and runs a matrix of invocations against
both implementations, asserting that they produce byte-identical output and that the
multi-pattern gate semantics match expectations.

## Usage

```
grep [regex] [files ...] [options]
```

Running with no arguments prints usage help.

## Positional Arguments

| Argument | Description |
|----------|-------------|
| `regex`  | Regular expression pattern to search for (optional) |
| `files`  | One or more filename patterns (globs) to search. Default: `*` |

## Options

### Pattern Matching

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-e PATTERN` | `--expression PATTERN` | Specify additional regex patterns. Can be repeated. **All** patterns must be present before any results are shown for a file — see [Multiple patterns](#multiple-patterns). |
| `-P NUM` | `--proximity NUM` | Require all patterns (positional + all `-e`) to occur within NUM lines of each other, instead of anywhere in the file. Only matching lines inside a satisfying window are shown. |
| `-i` | | Make regex matching case-insensitive. |
| | `--dotall` | Make `.` in regex match newlines. Reads the entire file at once. Disables line numbers. |

### File Selection

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-f [PATTERN ...]` | | Search files matching these filename patterns. Use this when you have no positional regex — see [Patterns come before filenames](#patterns-come-before-filenames). |
| `-r` | `--recursive` | Search directories recursively, ignoring symlinked directories unless they're explicitly included via `-p`. |
| `-R` | `--dereference-recursive` | Search directories recursively, following all symlinks. |
| `-p [PATH ...]` | | Search these directory paths. Default: `.` (current directory). |
| | `--x_files [SPEC ...]` | Exclude files matching these filename patterns. |
| | `--x_paths [PATH ...]` | Exclude these directory paths from recursive search. Matches against path suffixes (e.g. `node_modules` excludes any directory named `node_modules` at any depth). |
| `-c` | | Make filename pattern matching case-sensitive regardless of your system's default (Windows defaults to case-insensitive). |

### Output Control

| Flag | Long Form | Description |
|------|-----------|-------------|
| `-l` | | Show only filenames of files that contain a match. |
| `-L` | `--negate` | Show only filenames of files that contain no match. |
| `-n` | `--line-numbers` | Show line numbers alongside matches. |
| `-m NUM` | `--max-count NUM` | Stop searching a file after NUM matches. |
| `-B NUM` | `--before-context NUM` | Print NUM lines of context before each match. |
| `-A NUM` | `--after-context NUM` | Print NUM lines of context after each match. |
| `-C NUM` | `--context NUM` | Print NUM lines of context both before and after each match (shorthand for `-B NUM -A NUM`). |

### Colors

| Flag | Long Form | Description |
|------|-----------|-------------|
| | `--colors` | Enable colorized output (default). |
| | `--no-colors` | Disable colorized output. |
| | `--allow-match-colors` | Preserve ANSI color escape sequences that exist in the matched text. Other escape codes are still filtered. |
| | `--no-allow-match-colors` | Strip all ANSI escape sequences from matched text (default). |
| | `--set-colors [C C C C C C]` | Set the six output colors in order: filename, colon, line number, match text, error message, escape code. With no arguments, resets to defaults. |
| | `--remember` | Save current color settings to the config file. |

#### Available Color Names

`black` `red` `green` `yellow` `blue` `magenta` `cyan` `white`
`brightblack` `brightred` `brightgreen` `brightyellow` `brightblue` `brightmagenta` `brightcyan` `brightwhite`
`default`

#### Default Colors

| Element | Color |
|---------|-------|
| Filename | `brightgreen` |
| Colon separator | `brightblack` |
| Line number | `brightred` |
| Match text | `default` (terminal default) |
| Error message | `brightred` |
| Escape code display | `brightblue` |

## Multiple patterns

Patterns are **AND**ed. Give more than one pattern — a positional regex plus any number of
`-e` patterns — and a file produces no output at all unless *every* pattern is present.

```
grep "class" -e "def" -e "import" -rn *.py
```
Only files containing all three words produce output; each one then prints every line that
matched any of them.

To match **any** of several alternatives instead, put them in a single regex separated by
`|` — there is no `--any` flag:

```
grep "class|def|import" -rn *.py
```

### Patterns come before filenames

The **first non-option argument is always the search regex**, and only the arguments after it
are filename patterns. That holds even when you supplied every pattern with `-e`. So this does
not do what it looks like:

```
grep -i -l -e math -e logic "d:\book\*.html"     # WRONG
```

There is no positional regex before the path, so the *path* becomes the regex and no filename
pattern is given at all (it falls back to `*` in the current directory). Pass filename patterns
with `-f` instead:

```
grep -i -l -e math -e logic -f "d:\book\*.html"  # right
```

grep detects this case and warns, because the failure is otherwise silent — a path used as a
regex simply matches nothing:

```
$ grep -i -l -e math -e logic "d:\book\*.html"
Warning: 'd:\book\*.html' is being used as the search regex.
It matches 199 existing files, but the first non-option argument is always the
search regex -- even when every pattern was given with -e. Pass filename patterns with -f:
  grep -e math -e logic -f "d:\book\*.html"
```

Note that a Windows path often *is* a valid regex, so you can't rely on getting an error:
`\t` in `d:\temp\*` is a tab, and C++'s regex engine accepts unknown escapes like `\m` as
literal characters. The warning appears when the argument names files that actually exist and
no other filename pattern was supplied — the normal form below stays quiet, because there the
filename pattern is present:

```
grep "class" -e "def" -e "import" -rn *.py       # positional regex + -e patterns: fine
```

### Gate scope

Only the *scope* of the AND changes between modes. The printing rule is identical everywhere:
**print the lines that match, plus `-B`/`-A`/`-C` context around each, with `-----` between
non-contiguous groups.**

| | Gate scope |
|---|---|
| default | the whole file — every pattern must appear somewhere in it |
| `-P NUM` | a sliding NUM-line window — every pattern must appear within NUM lines of the others |

Because the two share a printing rule, `-P` with a NUM at least as large as the file is
exactly equivalent to the default whole-file gate. That equivalence is asserted by the test
suite.

### `-P` is window-scoped

Under `-P`, a matching line that never lands in a satisfying window is **not** printed. Given
a file with `ALPHA` on line 3, `BETA` on line 5 and `ALPHA` again on line 7:

```
$ grep -n -P 3 ALPHA -e BETA near.txt
near.txt:3:line 03 ALPHA here
near.txt:5:line 05 BETA here
```

Line 7 is absent: its `ALPHA` has no `BETA` within 3 lines, so it isn't part of a cluster.
`-C` still applies normally and can reach it as context:

```
$ grep -n -P 3 -C 2 ALPHA -e BETA near.txt
near.txt:1:line 01 filler
...
near.txt:7:line 07 ALPHA here
```

### Memory

The whole-file gate is implemented as a cheap extra pass over the file (bailing out as soon
as the last outstanding pattern is found) rather than as an unbounded proximity window, so
memory stays O(1) and arbitrarily large files still stream. Measured on a 400k-line file:
~6 MB for the default gate versus ~51 MB for `-P 400000`. Prefer the default over a huge
`-P` value.

## Short Flag Combining

Boolean short flags can be combined: `-ilrn` is equivalent to `-i -l -r -n`.

Flags that take a value consume the rest of the combined flag as their value: `-B3` is equivalent to `-B 3`, and `-ilB3` is equivalent to `-i -l -B 3`.

## Config File

Color settings are stored in `grep.colors.conf` in the same directory as the executable. The file uses INI format:

```ini
[general]
use_colors = True
allow_match_colors = False

[colors]
fncolor = brightgreen
coloncolor = brightblack
linecolor = brightred
normalcolor = default
errcolor = brightred
esccolor = brightblue
```

Use `--remember` to save the current settings. The config file is read on each run; command-line flags override its values.

## Examples

Search for "TODO" in all files in the current directory:
```
grep TODO
```

Case-insensitive search in `.py` files:
```
grep -i "def main" *.py
```

Recursive search with context:
```
grep -rn -C2 "error" *.log
```

Show only filenames that match:
```
grep -rl "import os" *.py
```

Search specific paths, excluding `node_modules`:
```
grep -r "useState" *.tsx -p src --x_paths node_modules
```

Find files containing both "class" and "def" anywhere in them:
```
grep -rl "class" -e "def" *.py
```

Proximity search — show the places where "class" and "def" appear within 5 lines:
```
grep -rn "class" -e "def" -P 5 *.py
```

Match any of several alternatives (use `|`, not `-e`):
```
grep -rn "class|def|import" *.py
```

Dotall mode (match across line boundaries):
```
grep --dotall "BEGIN.*?END" data.txt
```

Show files that do NOT match:
```
grep -L "deprecated" *.py
```

Set custom colors (filename=cyan, colon=white, lineno=yellow, text=default, error=red, esc=blue):
```
grep --set-colors cyan white yellow default red blue --remember "pattern" *.txt
```

## Escape Character Display

Control characters (bytes 0x00–0x1f, except LF and CR) found in matched text are displayed as `\xNN` in the escape color (default: bright blue) rather than being sent raw to the terminal.

With `--allow-match-colors`, ANSI color sequences (ESC `[` *digits* `m`) are passed through so pre-colored text renders correctly; all other escape codes are still filtered.

## Filenames and Encoding

Both builds emit UTF-8 and handle filenames containing characters your console's ANSI code page
can't represent (accents, `⋆`, CJK, emoji). No environment variable is needed — `grep.py`
reconfigures `sys.stdout`, and `grep.exe` sets the console output code page for the duration of
the run and restores it afterwards.

If you redirect output to a file, you get UTF-8 bytes.

## Differences from grep.py

- Uses C++ `std::regex` (ECMAScript grammar) instead of Python's `re` module. Most common patterns work identically; named groups use `(?<name>...)` syntax instead of Python's `(?P<name>...)`.
- On Windows, ANSI colors are enabled via `SetConsoleMode` (Windows 10 1511+) instead of the `colorama` package.
- Config file is named `grep.colors.conf` (not `grep.py.colors.conf`).

Output is otherwise byte-identical; `test_grep.py` asserts this on every case in its matrix.


## License

MIT - see [LICENSE](LICENSE). Free to use, modify and redistribute; provided
as-is, with no warranty.
