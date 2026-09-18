#multiple-pattern matching. how it works:
#  - All patterns (positional regex + all -e patterns) are compiled into a regexcs list.
#  - Patterns are always AND'ed: a file produces no output at all unless EVERY pattern is present. To match any of
#    several alternatives instead, use a single regex with '|'.
#  - Only the GATE SCOPE differs between modes; the printing rule is the same everywhere, namely "print the lines that
#    match, plus -B/-A/-C context around each, with ----- between non-contiguous groups".
#      * without -P: gate scope is the whole file. Implemented as two passes — all_present_lines() scans for the
#        patterns (bailing out early as soon as the last one is found), then seek(0) and the normal output loop runs.
#        Two passes keeps memory O(1) so huge files still stream.
#      * with -P: gate scope is a sliding window. A history buffer of proximity + before_context + 1 lines is kept.
#        For each line all regexes are checked and last_match[idx] updated; entries older than proximity lines expire.
#        When every regex has a live match the window is satisfied, and the matching lines within it (expanded by
#        before/after context) are printed from the buffer. last_match is then cleared to look for the next window.
#  - -P is window-scoped: a matching line that never lands in a satisfying window is NOT printed.
#  - -l, -L, --dotall, -m, -B, -A, -C all work with both gate scopes.

#todo: (see known-issues.md for the tracked list; this block is the raw scratchpad)
#make it so 'grep.py -f *' prints every line of every file instead of just printing filenames
#take care of the abuse of global variables?
#add an option for multiline?
#showing multiline output with --dotall is ugly, since the first line isn't aligned with the next lines.
#grep.exe automatically detects binary files and just reports whether they match or not.
#distinguish between file names and directory names in error messages?
#should we be nice to the users and change --x_paths and --x_files to --x-paths and --x-files?
#why is listing d:\ so slow even without a regex?
#add parameter for max_err?
#test out-of-memory conditions
#detect circular recursion by checking inodes
#use os.scandir instead? it's faster because it uses a cache, but i'd have to figure out how to extract the filenames.
# it returns DirEntry objects.
# also, if it uses a cache, could some files be missing from the scan? texnickal texnical said yes.
# apparently i could use os.walk and not search certain directories because
# "<TeXNickAL> (You're allowed to alter the list of son-nodes it returns at each step.)"
#  "When topdown is True, the caller can modify the dirnames list in-place (perhaps using del or slice assignment),
#  and walk() will only recurse into the subdirectories whose names remain in dirnames"
#  but os.walk uses scandir
#  os.walk has a follow_symlinks option
#issue: grep.py -R temp will show not only the symlinked dir temp but also teh symlinked dir temp\temp
#add sanity check to make sure user doesn't use -r AND -R?
#should we have an --include-symlinks or just use -p? both would result in the same thing except for when the files would show up
# in the traversal. though we could have walk check all the i_paths for each directory that's a symlink. that shouldn't take a lot more
# cpu in most cases. that's what we're doing.
#we could show more error info, because i saw "PermissionError: [WinError 21] The device is not ready: 'd:\\'" when i didn't try/except
#automatically disable color if detected that output is being redirected to a file? can you even detect that?
#decoding everything as utf-8 distorts the output of binary files
#would it be better to remove the spaces after colors after error messages?
#detect invalid filespec before even searching anything and quit?
#think about changing set-colors so the user doesn't have to specify all six and remember the order
#add option for regex matching of filenames? directory names?
#show loading/saving grep.py.colors.conf errors at end of scroll instead of beginning?
#show notification to install colorama at the end rather than the beginning?
#if args.no_color and not args.allow_match_colors then set allow_match_colors = False even if the config file says it's True
#if there's an error opening the config file, show the error message using the colors specified in --set-colors if they were specified. but that will be really tricky.
# because we're also showing errors in the --set-colors parameter in whatever colors are in the config file. and one or the other has to be processed first.

import os, re, argparse, fnmatch, sys, configparser, glob
from collections import deque, defaultdict
from pathlib import PurePath

# Emit UTF-8 no matter what the console's code page is. The filesystem encoding is already
# UTF-8, so without this a filename containing a character the ANSI code page lacks (e.g. U+22C6
# under cp1252) raises UnicodeEncodeError and degrades to "Error printing filename." -- once for
# every such file. grep.exe does the equivalent by setting the console output code page, and
# keeping the two in step is what lets test_grep.py assert byte-identical output for non-ASCII
# names. The error handling below is retained as a safety net for streams this can't fix.
try:
  sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
  pass  # Python < 3.7, or a stream that doesn't support reconfiguring

parser = argparse.ArgumentParser()
parser.add_argument("regex", nargs="?", help="regular expression pattern to search for")
parser.add_argument("files", nargs="*", help="search files matching these filename patterns")
parser.add_argument("-e", "--expression", action="append", metavar="pattern", help="specify additional regex patterns. can be repeated. ALL patterns must be present before any results are shown for a file. "
                    "without -P that means all patterns must appear somewhere in the file; with -P they must appear within the proximity window. "
                    "to match any of several alternatives instead, put them in one regex separated by '|'")
parser.add_argument("-P", "--proximity", type=int, metavar="num", help="require all patterns to occur within num lines of each other instead of anywhere in the file. "
                    "only matching lines inside a satisfying window are shown")
parser.add_argument("-f", nargs="*", help="search files matching these filename patterns. this option exists so you can search files even if you don't specify a regex")
parser.add_argument("-R", "--dereference-recursive", action="store_true", help="search directories recursively")
parser.add_argument("-r", "--recursive", action="store_true", help="search directories recursively, ignoring symlinked directories unless they're explicitly included")
parser.add_argument("-p", nargs="*", metavar="path", help="search these paths")
parser.add_argument("--x_files", nargs="*", metavar = "filespec", help="exclude these filename patterns from search")
parser.add_argument("--x_paths", nargs="*", metavar = "path", help="exclude these paths from search")
parser.add_argument("-i", action="store_true", help="make search case-insensitive")
parser.add_argument("-c", action="store_true", help="make filename matching case-sensitive regardless of your system's standard")
parser.add_argument("--dotall", action="store_true", help="make '.' match newlines")
parser.add_argument("-B", "--before-context", type=int, metavar="num", help="print this many lines of context preceding a match")
parser.add_argument("-A", "--after-context", type=int, metavar="num", help="print this many lines of context following a match")
parser.add_argument("-C", "--context", type=int, metavar="num", help="print this many lines of context both preceding and following a match")
parser.add_argument("-m", "--max-count", type=int, metavar="num", help="maximum number of matches to show")
parser.add_argument("-L", "--negate", action="store_true", help="show only files that contain no match")
parser.add_argument("-l", action="store_true", help="show only filenames")
parser.add_argument("-n", "--line-numbers", action="store_true", help="show line numbers")
parser.add_argument("--allow-match-colors", action=argparse.BooleanOptionalAction, help="show or don't show ANSI colors if they exist in the match text, but not other escape codes. "
                    "defaults to yes unless --remember was previously used")
parser.add_argument("--colors", action=argparse.BooleanOptionalAction, help="enable or disable colorized output.")
parser.add_argument("--set-colors", nargs="*", metavar="color", help="provide six color names to set the colors of filenames, colons, "
                    "line numbers, match contents, error messages and character escape codes to."
                    " options are black, darkred, darkgreen, darkyellow, darkblue, darkmagenta, darkcyan, lightgray,  gray, red, green, yellow, blue, magenta, cyan, and white."
                    " see https://i.sstatic.net/9UVnC.png to see colors for Windows Console, PowerShell, and Ubuntu."
                    " --set-colors with no options to use the defaults")
parser.add_argument("--remember", action="store_true", help="remember all color settings")

if len(sys.argv) == 1:
  parser.print_help()
  sys.exit()
args = parser.parse_args()

max_err = 5

config = configparser.ConfigParser()
class colorsclass:
  pass
c = colorsclass()
yescolors = dict(zip("black, red, green, yellow, blue, magenta, cyan, white, brightblack, brightred, brightgreen, brightyellow, brightblue, "
                  "brightmagenta, brightcyan, brightwhite, default".split(", "),
                  list(f"\033[0;{x}m" for x in range(30, 38)) + list(f"\033[1;{x}m" for x in range(30, 38))+["\033[0m"]))
nocolors = defaultdict(str)
defaultcolors = {"fncolor": "brightgreen", "coloncolor": "brightblack", "linecolor": "brightred", "normalcolor": "default", "errcolor": "brightred", "esccolor": "brightblue"}
fcolors = defaultcolors
usecolors = True if args.colors is None else args.colors
allowmatchcolors = False
colors = yescolors
cf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grep.py.colors.conf")
for fcolor in fcolors:
  setattr(c, fcolor, colors[fcolors[fcolor]])
if os.path.isfile(cf):
  try:
    confstring = open(cf, "r").read()
  except (PermissionError, IOError) as e:
    print(f'{c.errcolor}{"Permission error" if type(e) is PermissionError else "I/O error"}: {c.normalcolor}could not read from colors file "{cf}"')
  else:
    if not confstring == "":
      config.read_string(open(cf, "r").read())
      if args.set_colors is None:
        fcolors = dict(config["colors"])
      if args.colors is None:
        usecolors = config["general"].getboolean("use_colors")
      if args.allow_match_colors is None:
        allowmatchcolors = config["general"].getboolean("allow_match_colors")
if usecolors and os.name=="nt":
  try:
    from colorama import just_fix_windows_console
    just_fix_windows_console()
  except:
    usecolors = False
    print("To enable colored output, `pip install colorama`")
    print()
if not usecolors:
  colors = nocolors
if args.set_colors is not None:
  if args.set_colors == []:
    fcolors = defaultcolors
    colors = yescolors
  elif len(args.set_colors) != 6:
    print(f"{c.errcolor}Error: {c.normalcolor}wrong number of colors{colors['default']}")
    quit()
  else:
    invalidcolors = [color for color in args.set_colors if color not in colors]
    if invalidcolors:
      print(f"{c.errcolor}Orror: {c.normalcolor}invalid color(s) passed: {', '.join(invalidcolors)}{colors['default']}")
      quit()
    else:
      fcolors = dict(zip("fncolor, coloncolor, linecolor, normalcolor, errcolor, esccolor".split(", "), args.set_colors))
for fcolor in fcolors:
  setattr(c, fcolor, colors[fcolors[fcolor]])
saved_conf = False
if args.remember:
  try:
    cfo = open(cf, "w")
  except (PermissionError, IOError) as e:
    print(f'{"Permission error" if type(e) is PermissionError else "I/O error"}: could not write to colors file "{cf}"{colors["default"]}')
  else:
    config["general"] = {}
    config["general"]["use_colors"] = "True" if args.colors is None else str(args.colors)
    config["general"]["allow_match_colors"] = str(allowmatchcolors)
    config["colors"] = fcolors
    config.write(cfo)
    saved_conf = True

if args.allow_match_colors is not None:
  allowmatchcolors = args.allow_match_colors

if allowmatchcolors:
  filteresc = re.compile(r"[\x00-\x09\x0b-\x0c\x0e-\x1a\x1c-\x1f]|(?:\x1b(?!\[[0-9;]*m))")
else:
  filteresc = re.compile(r"[\x00-\x09\x0b-\x0c\x0e-\x1f]")

if args.c:
  from fnmatch import fnmatchcase as fnmatch
else:
  from fnmatch import fnmatch

if args.dotall:
  args.line_numbers = False

before_context = args.before_context or 0
after_context = args.after_context or 0
if args.context:
  before_context = after_context = args.context or 0

params = []
if args.dotall:
  params.append(re.DOTALL)
if args.i:
  params.append(re.I)

all_patterns = []
if args.regex:
  all_patterns.append(args.regex)
if args.expression:
  all_patterns.extend(args.expression)

def filespec_hit_count(pattern):
  """How many existing files 'pattern' matches as a glob. -1 if it can't be tried."""
  try:
    return len(glob.glob(pattern))
  except (OSError, ValueError):
    return -1

def print_slot_hint(pattern, hits):
  """Explain that 'pattern' was consumed as the search regex, and how to pass it as a
  filespec instead. Only called when it demonstrably names files."""
  print(f"{c.normalcolor}It matches {hits} existing file{'' if hits == 1 else 's'}, but the "
        f"first non-option argument is always the{colors['default']}")
  print(f"{c.normalcolor}search regex -- even when every pattern was given with -e. Pass "
        f"filename patterns with -f:{colors['default']}")
  print(f"{c.normalcolor}  grep{''.join(f' -e {x}' for x in (args.expression or []))}"
        f" -f \"{pattern}\"{colors['default']}")

regexcs = []
for pattern_index, pattern in enumerate(all_patterns):
  try:
    regexc = re.compile(pattern.encode("utf-8"), *params)
  # re.error, not re.PatternError: the latter is merely an alias for it added in 3.13, so
  # naming it here would make this script fail to even catch a bad pattern on older Pythons.
  except re.error as e:
    print(f"{c.errcolor}Regex pattern error in '{pattern}': {c.normalcolor}{', '.join(e.args)}{colors['default']}")
    # all_patterns[0] is the positional argument whenever one was given. Only recommend -f
    # when the argument demonstrably names files -- otherwise it's just a broken regex and
    # telling the user to pass it as a filespec would be actively wrong.
    if pattern_index == 0 and args.regex:
      hits = filespec_hit_count(pattern)
      if hits > 0:
        print_slot_hint(pattern, hits)
      elif args.expression:
        print(f"{c.errcolor}Note: {c.normalcolor}all your patterns were given with -e, so this "
              f"argument was taken as the{colors['default']}")
        print(f"{c.normalcolor}search regex. If you meant it as a filename pattern, pass it "
              f"with -f.{colors['default']}")
    sys.exit()
  regexcs.append(regexc)

# The same trap, but for a filespec that happens to compile as a valid regex -- e.g.
# "d:\temp\*.txt" (\t is just a tab) in Python, or anything at all in C++, whose ECMAScript
# engine accepts unknown escapes like \m as literals. Nothing errors; the search simply runs
# with a nonsense pattern and reports nothing, which is a silent wrong answer. Warn when the
# positional names real files AND no filespec was supplied by any other means -- that last
# condition is what keeps the documented "grep 'class' -e 'def' *.py" usage quiet, since
# there args.files is non-empty.
if args.regex and args.expression and not (args.files or args.f):
  _hits = filespec_hit_count(args.regex)
  if _hits > 0:
    print(f"{c.errcolor}Warning: {c.normalcolor}'{args.regex}' is being used as the search "
          f"regex.{colors['default']}")
    print_slot_hint(args.regex, _hits)
    print()

proximity = args.proximity or 0

i_paths = args.p or ["."]
i_files = (((args.files or []) + (args.f or []))) or ["*"]
x_paths = [PurePath(p).parts for p in args.x_paths] if args.x_paths else []
x_files = args.x_files or []

def fe(s2):
  s3 = []
  laststart = -1
  start = 0
  for m in filteresc.finditer(s2):
    start = m.start()
    s3.extend((fr"{s2[laststart+1:start]}{c.esccolor}\x{ord(s2[start]):02x}{c.normalcolor}"))
    laststart = start
  s3.append(s2[laststart+1:])
  return ''.join(s3)

def ld(directory):
  if not os.path.exists(directory):
    print(f"{c.errcolor}directory doesn't exist: {c.normalcolor}{directory}")
    return []
  elif not os.path.isdir(directory):
    print(f"{c.errcolor}is not a directory: {c.normalcolor}{directory}")
    return []
  else:
    try:
      r = os.listdir(directory)
    except (PermissionError, IOError) as e:
      print(f"{c.errcolor}{'Permission denied' if type(e) is PermissionError else 'I/O error'}: {c.normalcolor}{directory}")
      return []
    else:
      return r

sparts = set()
def walk(directory, parts): #maybe we should make x_paths and i_paths and -r explicitly passed here even though they're
  global sparts             # never going to be changed.
  if not parts in sparts:
    for fn in ld(directory):
      p = os.path.join(directory, fn)
      if os.path.isfile(p):
        yield (p, fn)
      elif os.path.isdir(p):
        parts2 = parts+(fn,)
        if not (args.recursive and os.path.islink(p) and not any(parts2[-len(x):] == x for x in i_paths)): #todo: is this right?
          if not any(parts2[-len(x):] == x for x in x_paths): #this is really dirty but i don't know of a better solution do excludes
            yield from walk(p, parts2)                        # how I want
  sparts.add(parts)

error_printing = False
def prn(p, ln=None, s=None): #todo: add note about set pythonutf8
  global error_printing
  if s is None:
    try:
      print(f"{c.normalcolor}{p}")
    except UnicodeEncodeError:
      print(f"{c.errcolor}Error printing filename.")
      error_printing = True
  else:
    s2 = s.decode("utf-8", errors="ignore").rstrip()
    s2 = fe(s2)
    p = p.removeprefix(".\\")
    try:
      print(f"{c.fncolor}{p}", end="")
    except UnicodeEncodeError:
      print(f"{c.errcolor}Error printing filename", end="")
      error_printing = True
    else:
      if args.line_numbers:
        print(f"{c.coloncolor}:{c.linecolor}{ln}{c.coloncolor}:", end="")
      else:
        print(f"{c.coloncolor}:", end="")
      try:
        print(f"{c.normalcolor}{s2}")
      except UnicodeEncodeError:
        print(f"{c.errcolor}Error printing {'match text' if args.dotall else 'line'}")
        error_printing = True
def decode(s):
  return s.decode("utf-8", errors="ignore").rstrip()

def oom(p, line_number, count):
  """Report an out-of-memory event on one line, honouring max_err. Returns the new count."""
  count += 1
  if count <= max_err:
    print(f"{c.errcolor}out of memory on line {c.linecolor}{line_number}{c.errcolor}: {c.normalcolor}{p}")
  elif count == max_err+1:
    print(f"{c.errcolor}max out-of-memory notifications exceeded for file: {c.normalcolor}{p}")
  return count

def all_present_lines(inf, p):
  """Consume a line-based file and report whether every compiled regex matched somewhere.

  Bails out as soon as the last outstanding pattern is found, so files that do satisfy the
  gate usually aren't read to the end.

  This always gives the honest answer, including for a single pattern. Do NOT add a
  "len(regexcs) < 2 -> return True" shortcut here: -l/-L call this as their *only* match
  test, so short-circuiting makes single-pattern -l list every file and -L list none.
  Callers that follow up with a per-line pass (process_full) can skip this call themselves
  when there's only one pattern, because that later pass does the real filtering."""
  unmatched = set(range(len(regexcs)))
  line_number = 0
  outofmemorycount = 0
  while unmatched:
    try:
      line = inf.readline()
    except MemoryError:
      outofmemorycount = oom(p, line_number+1, outofmemorycount)
      continue
    if not line:
      break
    line_number += 1
    for idx in tuple(unmatched):
      if regexcs[idx].search(line):
        unmatched.discard(idx)
  return not unmatched

def process_dotall(p, inf):
  """--dotall reads the whole file at once, so the gate is always whole-file."""
  try:
    data = inf.read()
  except MemoryError:
    print(f"{c.errcolor}Out of memory: {c.normalcolor}{p}")
    return
  present = all(rc.search(data) for rc in regexcs)
  if args.negate:
    if not present:
      prn(p)
  elif args.l:
    if present:
      prn(p)
  elif present:
    for rc in regexcs:
      for x in rc.findall(data):
        prn(p, None, x)

def process_names(p, inf):
  """-l / -L: only the gate result matters, no file content is printed."""
  line_number = 0
  try:
    if args.proximity is not None:
      satisfied = False
      last_match = {}
      for line in inf:
        line_number += 1
        for idx, rc in enumerate(regexcs):
          if rc.search(line):
            last_match[idx] = line_number
        for idx in [i for i, ln in last_match.items() if line_number - ln >= args.proximity]:
          del last_match[idx]
        if len(last_match) == len(regexcs):
          satisfied = True
          break
    else:
      satisfied = all_present_lines(inf, p)
  except MemoryError:
    print(f"{c.errcolor}Out of memory: {c.normalcolor}{p}")
    return
  if satisfied:
    if args.l:
      prn(p)
  elif args.negate:
    prn(p)

def process_full(p, inf):
  """Print matching lines plus -B/-A/-C context. The gate scope is the only thing that
  varies: a sliding window with -P, otherwise the whole file."""
  outofmemorycount = 0
  num_matches = 0
  line_number = 0
  last_printed_line = 0
  after_remaining = 0
  matched_one = False

  def emit(ln, text):
    """Print one line, inserting a ----- separator when it isn't contiguous with the last.

    Separators only make sense when context was requested -- without -B/-A/-C every printed
    line is itself a match, so a separator between each pair would just be noise (and plain
    grep doesn't print them either). Keeping this conditional is what makes "-P >= the file's
    length" produce byte-identical output to the whole-file gate."""
    nonlocal last_printed_line, matched_one
    if matched_one and ln > last_printed_line + 1 and (before_context or after_context):
      print("-----")
    prn(p, ln, text)
    last_printed_line = ln
    matched_one = True

  if args.proximity is not None:
    # Gate scope is a sliding window. Only matching lines inside a satisfied window get
    # printed, each expanded by before/after context -- the lines merely *between* two
    # matches are not printed unless context reaches them.
    prox_buffer = deque(maxlen=args.proximity + before_context + 1)
    last_match = {}  # regex index -> most recent matching line number
    while True:
      try:
        line = inf.readline()
        if not line:
          break
        line_number += 1
        hits = [idx for idx, rc in enumerate(regexcs) if rc.search(line)]
        prox_buffer.append((line_number, line, bool(hits)))
        for idx in hits:
          last_match[idx] = line_number
        # expire matches that have fallen outside the proximity window
        for idx in [i for i, ln in last_match.items() if line_number - ln >= args.proximity]:
          del last_match[idx]
        if len(last_match) == len(regexcs):
          num_matches += 1
          if args.max_count is not None and num_matches > args.max_count:
            break
          # The satisfied window runs from the earliest live match to the current line.
          # max(last_match.values()) is always line_number: the set can only *become*
          # complete on a line where some pattern matched.
          min_ln = min(last_match.values())
          wanted = set()
          for bln, bline, bmatch in prox_buffer:
            if bmatch and min_ln <= bln <= line_number:
              wanted.update(range(max(bln - before_context, 1), bln + after_context + 1))
          for bln, bline, bmatch in prox_buffer:
            if bln in wanted and bln > last_printed_line:
              emit(bln, bline)
          # after-context past the completing match is still unread, so stream it
          after_remaining = after_context
          last_match.clear()
        elif after_remaining > 0 and line_number > last_printed_line:
          emit(line_number, line)
          after_remaining -= 1
      except MemoryError:
        outofmemorycount = oom(p, line_number, outofmemorycount)
    return

  # Gate scope is the whole file: require every pattern before printing anything. Done as
  # a separate pass rather than a giant proximity window so memory stays O(1). With a
  # single pattern the gate can't reject anything the per-line loop below wouldn't also
  # skip, so the extra pass is pure cost and is skipped.
  if len(regexcs) > 1:
    if not all_present_lines(inf, p):
      return
    inf.seek(0)
  before_buf = deque()
  while True:
    try:
      line = inf.readline()
      if not line:
        break
      line_number += 1
      m = any(rc.search(line) for rc in regexcs)
      if m:
        num_matches += 1
        if args.max_count is not None and num_matches > args.max_count:
          break
      if before_context or after_context:
        if m:
          start = max(line_number - before_context, last_printed_line + 1)
          for bln, bline in before_buf:
            if bln >= start and bln > last_printed_line:
              emit(bln, bline)
          if line_number > last_printed_line:
            emit(line_number, line)
          after_remaining = after_context
        elif after_remaining > 0:
          emit(line_number, line)
          after_remaining -= 1
        before_buf.append((line_number, line))
        if len(before_buf) > before_context:
          before_buf.popleft()
      else:
        # no context requested; emit() suppresses separators in this case
        if m:
          emit(line_number, line)
    except MemoryError:
      outofmemorycount = oom(p, line_number, outofmemorycount)

def process(p):
  global s
  p = p.removeprefix(".\\")
  if p in s:
    return
  s.add(p)
  if not regexcs:
    prn(p)
    return
  try:
    inf = open(p, "rb")
  except (PermissionError, IOError) as e:
    print(f"{c.errcolor}{'Permission denied' if type(e) is PermissionError else 'I/O error'}: {c.normalcolor}{p}")
    return
  with inf:
    if args.dotall:
      process_dotall(p, inf)
    elif args.l or args.negate:
      process_names(p, inf)
    else:
      process_full(p, inf)

s = set()

if not (regexcs or args.p or args.x_files or args.x_paths or args.files or args.f or args.l or args.recursive or args.dereference_recursive):
  quit()

try:
  had_dir_spec = False   # true once a path-qualified "dir/spec" filespec has been handled
  i_files2 = []
  if args.recursive or args.dereference_recursive:
    for pf in i_files:
      p, spec = os.path.split(pf)
      if p:
        if not spec:
          print(f"{c.errcolor}invalid filespec: {c.normalcolor}{pf}")
        else:
          sparts.clear() #because we're searching different filespecs now, so we need to re-traverse the same directories
          for p2, fn in walk(p, (p,)):
            if fnmatch(fn, spec) and not any(fnmatch(fn, spec2) for spec2 in x_files): #we're considering x_files but not i_files. also x_paths but not i_paths.
              process(p2)                                                              # it makes sense to me, but it is a bit contradictory.
          sparts.clear()
          had_dir_spec = True
      else:
        i_files2.append(spec)
    if not (had_dir_spec or i_files2):
      i_files2 = ["*"]
    for p in i_paths:
      for p, fn in walk(p, (p,)):
        if any(fnmatch(fn, spec2) for spec2 in i_files2) and not any(fnmatch(fn, spec3) for spec3 in x_files):
          process(p)
  else:
    for pf in i_files:
      p, spec = os.path.split(pf)
      if p:
        if not spec:
          print(f"{c.errcolor}invalid filespec: {c.normalcolor}{pf}")
        else:
          for fn in ld(p):
            if fnmatch(fn, spec) and not any(fnmatch(fn, spec2) for spec2 in x_files): #we're considering x_fils but not i_files.
              fn2 = os.path.join(p, fn)
              if not os.path.isdir(fn2):
                process(os.path.join(p, fn))
          had_dir_spec = True
      else:
        i_files2.append(spec)
    # Only fall back to "*" when no filespec at all was given. A path-qualified
    # filespec (dir/spec) has already been handled above, so defaulting to "*"
    # here would additionally scan i_paths (default ".") and report unrelated
    # files from the current directory.
    if not (had_dir_spec or i_files2):
      i_files2 = ["*"]
    for path in i_paths:
      for fn in ld(path):
        p = os.path.join(path, fn)
        if not os.path.isdir(p):
          if any(fnmatch(fn, spec) for spec in i_files2) and not any(fnmatch(fn, spec2) for spec2 in x_files):
            process(p)
  if not s:
    print("No files matched your criteria.")
except KeyboardInterrupt:
  print()
  print(f"{colors['magenta']}^C")
if saved_conf:
  print()
  print(f'{c.normalcolor}Color settings were saved to "{cf}"')
elif args.remember:
  print(f'{c.normalcolor}Failed to save color settings to "{cf}"')
if error_printing:
  print()
  print(f"{c.normalcolor}There were errors printing results. `set PYTHONUTF8=1` to resolve this.{colors['default']}")
print(colors["default"], end="")
