#!/usr/bin/env python3
"""Regression tests for grep.py / grep.exe.

Runs a matrix of invocations against BOTH implementations and checks two things:

  1. parity  -- the Python and C++ builds must produce byte-identical output
  2. expectations -- specific outputs for the multi-pattern AND semantics

Fixtures are written to a fresh temp directory and every command runs with that
directory as cwd, so the filename prefixes in the output are stable.

Usage:  python test_grep.py [-v]
        python test_grep.py --py-only     (skip the C++ build, e.g. if not built)
"""

import os, subprocess, sys, tempfile, shutil, textwrap

HERE    = os.path.dirname(os.path.abspath(__file__))
GREP_PY = os.path.join(HERE, "grep.py")
GREP_EXE = os.path.join(HERE, "grep.exe")

VERBOSE  = "-v" in sys.argv
PY_ONLY  = "--py-only" in sys.argv or not os.path.isfile(GREP_EXE)

# Deliberately NOT setting PYTHONUTF8 here: both builds are supposed to emit UTF-8 out of the
# box (grep.py reconfigures sys.stdout, grep.exe sets the console output code page), and the
# tests should exercise the configuration a user actually gets.

# A stale grep.exe silently degrades every parity assertion below into a no-op comparison
# against itself, which has already once been mistaken for a real source discrepancy.
if not PY_ONLY and os.path.getmtime(GREP_EXE) < os.path.getmtime(os.path.join(HERE, "grep.cpp")):
    print("WARNING: grep.exe is OLDER than grep.cpp -- run build.bat.\n"
          "         Parity results below may reflect a stale binary.\n")

# ── fixtures ────────────────────────────────────────────────────────────────

FIXTURES = {
    # ALPHA@3, BETA@15, 20 lines -- matches far apart
    "far.txt": "".join(
        f"line {i:02d} {'ALPHA is here' if i == 3 else 'BETA is here' if i == 15 else 'filler'}\n"
        for i in range(1, 21)),
    # ALPHA@3, BETA@5, ALPHA@7 -- trailing unpaired match
    "near.txt": "".join(
        f"line {i:02d} {'ALPHA here' if i in (3, 7) else 'BETA here' if i == 5 else 'filler'}\n"
        for i in range(1, 9)),
    # only ALPHA, no BETA at all
    "alphaonly.txt": "line 01 filler\nline 02 ALPHA is here\nline 03 filler\n",
    # a file in cwd that must NOT be picked up when a dir/spec filespec is given
    "cwdbait.txt": "ALPHA bait in cwd\n",
}
SUBDIR_FIXTURES = {
    "sub/inner.txt": "ALPHA here\nBETA here\n",
    # A filename containing U+22C6 STAR OPERATOR, which the Windows ANSI code page (cp1252)
    # cannot represent. Regression: the C++ build listed directories with
    # fs::path::string(), which THROWS on such names; the exception unwound past the entire
    # search into main's silent catch-all, so grep reported nothing at all for the whole
    # directory -- including plain.txt, which has nothing wrong with it.
    "uni/plain.txt": "ALPHA here\n",
    "uni/star \u22c6 name.txt": "ALPHA here\n",
}


def build_tree(root):
    for name, body in FIXTURES.items():
        with open(os.path.join(root, name), "w", newline="\n") as f:
            f.write(body)
    for relpath, body in SUBDIR_FIXTURES.items():
        full = os.path.join(root, relpath.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", newline="\n") as f:
            f.write(body)


# ── runners ─────────────────────────────────────────────────────────────────

def run(cmd, cwd):
    # Decode as UTF-8 with surrogateescape: both builds emit UTF-8, and surrogateescape keeps
    # any stray byte losslessly so comparisons stay exact instead of collapsing differing
    # bytes into U+FFFD.
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="surrogateescape")
    return r.stdout.replace("\r\n", "\n").strip("\n")


def run_py(args, cwd):
    return run([sys.executable, GREP_PY, "--no-colors"] + args, cwd)


def run_cpp(args, cwd):
    return run([GREP_EXE, "--no-colors"] + args, cwd)


# ── test harness ────────────────────────────────────────────────────────────

results = {"pass": 0, "fail": 0}
failures = []


def check(desc, args, cwd, expected=None):
    """Run both impls; assert parity, and the exact expected output if given."""
    got_py = run_py(args, cwd)
    got_cpp = None if PY_ONLY else run_cpp(args, cwd)

    problems = []
    if not PY_ONLY and got_py != got_cpp:
        problems.append("py/cpp MISMATCH\n--- py ---\n%s\n--- cpp ---\n%s" % (got_py, got_cpp))
    if expected is not None:
        exp = textwrap.dedent(expected).strip("\n")
        if got_py != exp:
            problems.append("EXPECTATION\n--- expected ---\n%s\n--- got ---\n%s" % (exp, got_py))

    if problems:
        results["fail"] += 1
        failures.append("%s\n  args: %s\n%s" % (desc, " ".join(args), "\n".join(problems)))
        print("  FAIL  %s" % desc)
    else:
        results["pass"] += 1
        print("  ok    %s" % desc)
        if VERBOSE and got_py:
            print(textwrap.indent(got_py, "          "))


def check_same(desc, args_a, args_b, cwd):
    """Assert two different invocations produce identical output (an invariant)."""
    a, b = run_py(args_a, cwd), run_py(args_b, cwd)
    ok = (a == b)
    if ok and not PY_ONLY:
        ok = (run_cpp(args_a, cwd) == run_cpp(args_b, cwd) == a)
    if ok:
        results["pass"] += 1
        print("  ok    %s" % desc)
    else:
        results["fail"] += 1
        failures.append("%s\n  A: %s\n%s\n  B: %s\n%s" %
                        (desc, " ".join(args_a), a, " ".join(args_b), b))
        print("  FAIL  %s" % desc)


def main():
    root = tempfile.mkdtemp(prefix="greptest.")
    try:
        build_tree(root)
        print("fixtures in %s" % root)
        print("mode: %s\n" % ("python only" if PY_ONLY else "python + c++ parity"))

        # ── single pattern: unchanged behaviour ─────────────────────────
        print("single pattern")
        check("one pattern, plain", ["-n", "ALPHA", "far.txt"], root, """
            far.txt:3:line 03 ALPHA is here
        """)
        check("one pattern, no match", ["-n", "ZZZ", "far.txt"], root, "")

        # ── whole-file AND gate (the new default) ───────────────────────
        print("\nwhole-file AND gate")
        check("both present -> matching lines only",
              ["-n", "ALPHA", "-e", "BETA", "far.txt"], root, """
            far.txt:3:line 03 ALPHA is here
            far.txt:15:line 15 BETA is here
        """)
        check("one missing -> nothing at all",
              ["-n", "ALPHA", "-e", "BETA", "alphaonly.txt"], root, "")
        check("three patterns, all present",
              ["-n", "ALPHA", "-e", "BETA", "-e", "line 01", "far.txt"], root, """
            far.txt:1:line 01 filler
            far.txt:3:line 03 ALPHA is here
            far.txt:15:line 15 BETA is here
        """)
        check("three patterns, one missing",
              ["-n", "ALPHA", "-e", "BETA", "-e", "NOPE", "far.txt"], root, "")
        check("AND with -C 2 groups and separates",
              ["-n", "-C", "2", "ALPHA", "-e", "BETA", "far.txt"], root, """
            far.txt:1:line 01 filler
            far.txt:2:line 02 filler
            far.txt:3:line 03 ALPHA is here
            far.txt:4:line 04 filler
            far.txt:5:line 05 filler
            -----
            far.txt:13:line 13 filler
            far.txt:14:line 14 filler
            far.txt:15:line 15 BETA is here
            far.txt:16:line 16 filler
            far.txt:17:line 17 filler
        """)
        check("no context -> no ----- separators",
              ["-n", "ALPHA", "-e", "BETA", "far.txt"], root, """
            far.txt:3:line 03 ALPHA is here
            far.txt:15:line 15 BETA is here
        """)

        # ── -P is window scoped ─────────────────────────────────────────
        print("\n-P window gate (window-scoped)")
        check("-P 3: unpaired trailing match is NOT shown",
              ["-n", "-P", "3", "ALPHA", "-e", "BETA", "near.txt"], root, """
            near.txt:3:line 03 ALPHA here
            near.txt:5:line 05 BETA here
        """)
        check("-P 1: never satisfied -> nothing",
              ["-n", "-P", "1", "ALPHA", "-e", "BETA", "near.txt"], root, "")
        check("-P 3 -C 2: context reaches the unpaired match",
              ["-n", "-P", "3", "-C", "2", "ALPHA", "-e", "BETA", "near.txt"], root, """
            near.txt:1:line 01 filler
            near.txt:2:line 02 filler
            near.txt:3:line 03 ALPHA here
            near.txt:4:line 04 filler
            near.txt:5:line 05 BETA here
            near.txt:6:line 06 filler
            near.txt:7:line 07 ALPHA here
        """)
        check("-P does not print the lines merely between matches",
              ["-n", "-P", "99", "ALPHA", "-e", "BETA", "far.txt"], root, """
            far.txt:3:line 03 ALPHA is here
            far.txt:15:line 15 BETA is here
        """)

        # ── the invariant that ties the two gates together ──────────────
        print("\ninvariant: -P >= file length == whole-file gate")
        for extra in ([], ["-C", "2"], ["-B", "1"], ["-A", "1"]):
            label = " ".join(extra) or "no context"
            check_same("-P 99 == no -P  (%s)" % label,
                       ["-n", "-P", "99"] + extra + ["ALPHA", "-e", "BETA", "far.txt"],
                       ["-n"] + extra + ["ALPHA", "-e", "BETA", "far.txt"],
                       root)

        # ── -l / -L ─────────────────────────────────────────────────────
        print("\n-l / -L use the same gate")
        check("-l both present", ["-l", "ALPHA", "-e", "BETA", "far.txt"], root, "far.txt")
        check("-l one missing", ["-l", "ALPHA", "-e", "BETA", "alphaonly.txt"], root, "")
        check("-L one missing", ["-L", "ALPHA", "-e", "BETA", "alphaonly.txt"], root,
              "alphaonly.txt")
        check("-L both present", ["-L", "ALPHA", "-e", "BETA", "far.txt"], root, "")
        check("-l -P 3 window gate", ["-l", "-P", "3", "ALPHA", "-e", "BETA", "near.txt"],
              root, "near.txt")
        check("-l -P 1 unsatisfiable", ["-l", "-P", "1", "ALPHA", "-e", "BETA", "near.txt"],
              root, "")

        # ── -l / -L with a SINGLE pattern ───────────────────────────────
        # Regression: the whole-file gate short-circuited to "satisfied" whenever there were
        # fewer than two patterns, which is right for process_full (its per-line loop does the
        # real filtering) but catastrophic for -l/-L, whose ONLY match test is the gate. The
        # effect was that single-pattern -l listed every file it opened and -L listed none.
        # Every -l/-L case above uses two patterns, so nothing caught it.
        print("\n-l / -L with one pattern (regression: gate short-circuit)")
        check("-l one pattern, present", ["-l", "ALPHA", "far.txt"], root, "far.txt")
        check("-l one pattern, absent", ["-l", "ZZZ", "far.txt"], root, "")
        check("-L one pattern, present", ["-L", "ALPHA", "far.txt"], root, "")
        check("-L one pattern, absent", ["-L", "ZZZ", "far.txt"], root, "far.txt")
        check("-l one pattern over a glob lists only real matches",
              ["-l", "BETA", "*.txt"], root, """
            far.txt
            near.txt
        """)
        check("-L one pattern over a glob lists only real non-matches",
              ["-L", "BETA", "*.txt"], root, """
            alphaonly.txt
            cwdbait.txt
        """)
        check("-l one pattern with -P", ["-l", "-P", "3", "BETA", "*.txt"], root, """
            far.txt
            near.txt
        """)
        check("-l one pattern with --dotall", ["--dotall", "-l", "ZZZ", "far.txt"], root, "")

        # ── the "filespec landed in the regex slot" trap ─────────────────
        # The positional argument fills the 'regex' slot before 'files', so when every pattern
        # is given with -e, a lone trailing filespec becomes the search regex. It may not even
        # fail to compile ('\t' is a tab in Python; C++'s ECMAScript engine accepts unknown
        # escapes like '\m' as literals), in which case the search silently runs with a
        # nonsense pattern and reports nothing. The compile-failure message differs between the
        # two regex engines, so only this engine-independent warning path is parity-tested.
        print("\nfilespec consumed as the regex (regression: silent empty result)")
        check("warns when the positional names files and no filespec was given",
              ["-l", "-e", "ALPHA", "sub/inner.txt"], root, """
            Warning: 'sub/inner.txt' is being used as the search regex.
            It matches 1 existing file, but the first non-option argument is always the
            search regex -- even when every pattern was given with -e. Pass filename patterns with -f:
              grep -e ALPHA -f "sub/inner.txt"
        """)
        check("-f is the documented way to say it, and searches normally",
              ["-l", "-e", "ALPHA", "-f", "sub/inner.txt"], root, "sub\\inner.txt")
        check("stays quiet for the documented positional-regex-plus-e usage",
              ["-l", "ALPHA", "-e", "BETA", "*.txt"], root, """
            far.txt
            near.txt
        """)
        check("stays quiet when the positional names nothing on disk",
              ["-l", "-e", "ALPHA", "NoSuchThing"], root, "")

        # ── filenames outside the ANSI code page ────────────────────────
        print("\nnon-ANSI filenames (regression: silent empty result)")
        check("an unrepresentable filename doesn't hide its siblings",
              ["-l", "ALPHA", "uni/*.txt"], root, """
            uni\\plain.txt
            uni\\star \u22c6 name.txt
        """)
        check("and its contents are searchable",
              ["-n", "ALPHA", "uni/star \u22c6 name.txt"], root, """
            uni\\star \u22c6 name.txt:1:ALPHA here
        """)

        # ── --dotall ────────────────────────────────────────────────────
        print("\n--dotall uses the whole-file gate")
        check("dotall AND satisfied", ["--dotall", "-l", "ALPHA", "-e", "line 20", "far.txt"],
              root, "far.txt")
        check("dotall AND unsatisfied", ["--dotall", "-l", "ALPHA", "-e", "NOPE", "far.txt"],
              root, "")

        # ── -m ──────────────────────────────────────────────────────────
        print("\n-m interacts with the gate")
        check("-m 1 after gate passes",
              ["-n", "-m", "1", "ALPHA", "-e", "BETA", "far.txt"], root, """
            far.txt:3:line 03 ALPHA is here
        """)

        # ── path-qualified filespec must not leak cwd files ─────────────
        print("\npath-qualified filespec (regression: cwd leak)")
        check("dir/spec does not also scan cwd",
              ["-n", "ALPHA", "sub/inner.txt"], root, """
            sub\\inner.txt:1:ALPHA here
        """)
        check("dir/spec glob does not also scan cwd",
              ["-n", "ALPHA", "sub/*.txt"], root, """
            sub\\inner.txt:1:ALPHA here
        """)
        check("bare filename in cwd still works",
              ["-n", "ALPHA", "cwdbait.txt"], root, """
            cwdbait.txt:1:ALPHA bait in cwd
        """)
        check("recursive dir/spec still works",
              ["-rn", "ALPHA", "sub/*.txt"], root, """
            sub\\inner.txt:1:ALPHA here
        """)

        # ── recursion + AND ─────────────────────────────────────────────
        print("\nrecursion combined with the gate")
        # far.txt and near.txt both contain ALPHA and BETA; sub/inner.txt does too.
        # alphaonly.txt and cwdbait.txt have only ALPHA, so the gate rejects them.
        check("-rl AND rejects files missing a pattern",
              ["-rl", "ALPHA", "-e", "BETA"], root, """
            far.txt
            near.txt
            sub\\inner.txt
        """)

    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n%d passed, %d failed" % (results["pass"], results["fail"]))
    if failures:
        print("\n" + "=" * 70)
        for f in failures:
            print(f + "\n" + "-" * 70)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
