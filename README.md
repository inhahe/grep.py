# grep.py
My own grep in Python.

- Can just list all matching files without a regex
- Can specify a list of paths to search
- Can specify a list of paths to exclude from search
- Can make filename matching case-sensitive even on OSs where that's not the standard
- Has colorized output
- Can disable color or set your own colors, and it will remember what you set. Can also reset colors to their defaults
- Can make "." match newlines
- Other standard grep functions it can do are show only results that don't match, show line numbers, case-insensitive search, match only up to a certain number of items, search directories recursively, and specify number of lines of context before and after matches
- I've only tested it on Windows, but it *should* work on any OS

If you're on Windows, grep.py will not show color unless you `pip install colorama`.

The way path exclusion works, say your search criteria includes these directories:
d:\temp
d:\foo
d:\a\bar\baz

`--x_files d:\temp foo bar\baz` will exclude d:\temp, d:\foo, and d:\a\bar\baz.










