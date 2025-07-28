# grep.py
My own grep in Python.

I made it because none of the greps for Windows I could find worked right. One that I found a long time ago, that I think did recursive directory searching before GNU's did, often crashes, and some regex patterns don't match things that they should match. Another one that I found more recently, but is still a port of a relatively old version of GNU grep, just hangs whenever I try to do recursion. And I figured making a simple one in Python that does what I need ought to be easy. Then I started adding more and more features because it was so easy.

- Can just list all matching files without a regex
- Can specify a list of paths to search
- Can specify a list of paths to exclude from search
- Can make filename matching case-sensitive even on OSs where that's not the standard
- Has colorized output, even on Windows if colorama is installed
- Can disable color, set your own colors, or load the defaults, and can remember the settings
- Can make "." match newlines

(Actually, I don't know how many of those things are available in the latest GNU grep.)

Other, standard grep functions it can do are
- show only files that don't match
- show only matching files, no match text
- show line numbers
- case-insensitive search
- match only up to a certain number of lines
- search directories recursively
- search directories recursively ignoring symlinked directories
- specify number of lines of context before and after matches, either separately or both at once

I've only tested it a little bit on Linux (I'm a Windows user), but it *should* work on any OS.

If you're on Windows, grep.py will not show color unless you `pip install colorama`.

The way path exclusion works, say your search criteria includes these directories, probably because you're using `-r` or `-R`
```
d:\temp  
d:\foo   
d:\a\bar\baz
```

`--x_files d:\temp foo bar\baz` will exclude `d:\temp`, `d:\foo`, and `d:\a\bar\baz`

Similarly, `-R` (excludes symlinked directories except those explicitly included) with `-p baz` will include `a\bar\baz` if you're searching from `a` even if `a\bar\baz` is a symlink, for better or worse.

The way recursion works is, say you do `grep.py -r d:\*.html *.txt *.md -p d:\foo\bar --x_files robots.txt index.html`  
It will search `d:\` recursively, but only searching for `*.html`. It will exclude `index.html`.   
It will search `d:\foo\bar` recursively for `*.txt` and `*.md` and will exclude `robots.txt`. 

grep.py will search the current directory by default, but if any paths are specified, it will exclude the current directory (unless the current directory is one of the paths specified).

-----

All this in ~350 lines of Python.
