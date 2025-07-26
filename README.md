# grep.py
My own grep in Python.

- Can just list all matching files without a regex
- Can specify a list of paths to search
- Can specify a list of paths to exclude from search
- Can make filename matching case-sensitive even on OSs where that's not the standard
- Has colorized output
- Can disable color or set your own colors, and it will remember what you set. Can also reset colors to their defaults
- Can make "." match newlines

Other, standard grep functions it can do are
- show only files that don't match
- show only matching files, no match text
- show line numbers
- case-insensitive search
- match only up to a certain number of lines
- search directories recursively
- specify number of lines of context before and after matches, either separately or both at once

I've only tested it on Windows, but it *should* work on any OS.

If you're on Windows, grep.py will not show color unless you `pip install colorama`.

The way path exclusion works, say your search criteria includes these directories:  
```
d:\temp  
d:\foo   
d:\a\bar\baz
```

`--x_files d:\temp foo bar\baz` will exclude `d:\temp`, `d:\foo`, and `d:\a\bar\baz`.

Similarly, `-R` (excludes symlinks except those explicitly included) with `-p baz` will include `a\bar\baz` if you're searching from `a` even if `a\bar\baz` is a symlink, for better or worse.

The way recursion works is, say you do `grep.py -r d:\*.html *.txt *.md -p d:\foo\bar --x_files robots.txt index.html`  
It will search `d:\` recursively, but only searching for `*.html`. It will exclude `index.html`.   
It will search the current directory and `d:\foo\bar` recursively for `*.txt` and `*.md` and will exclude `robots.txt`. 

grep.py will search the current directory by default, but if any paths are specified, it will exclude the current directory (unless the current directory is one of the paths specified).

-----

All this in ~300 lines of Python.
