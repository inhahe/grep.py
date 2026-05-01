#claude.ai implemented searching for multiple patterns within x lines of each other for me. here's what he said:
#How it works:
#  - All patterns (positional regex + all -e patterns) are compiled into a regexcs list.
#  - Without -P: multiple patterns are OR'd — any line matching any pattern is shown, using the existing context buffer
#  logic unchanged.
#  - With -P: a history buffer of proximity + before_context + 1 lines is maintained. For each line, all regexes are
#  checked and last_match[idx] is updated. Matches older than proximity lines expire. When all regexes have a live match,
#   the window (from earliest match to latest match, plus before/after context) is printed from the buffer. After
#  printing, last_match is cleared to find the next occurrence. The -- separator is printed between non-contiguous match
#  groups.
# - -l, -L, --dotall, -m, -B, -A, -C all work with the new modes.

#todo:
#fix 'grep -il centre old\*' returned a filename from the current directory along with filenames from old
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

from pickle import NONE
import os, re, argparse, fnmatch, sys, configparser
from collections import deque, defaultdict
from pathlib import PurePath
from types import NoneType

parser = argparse.ArgumentParser()
parser.add_argument("regex", nargs="?", help="regular expression pattern to search for")
parser.add_argument("files", nargs="*", help="search files matching these filename patterns")
parser.add_argument("-e", "--expression", action="append", metavar="pattern", help="specify additional regex patterns. can be repeated. without -P, any match is shown. with -P, all patterns must appear within the proximity window")
parser.add_argument("-P", "--proximity", type=int, metavar="num", help="all specified patterns must occur within num lines of each other")
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

regexcs = []
for pattern in all_patterns:
  try:
    regexc = re.compile(pattern.encode("utf-8"), *params)
  except re.PatternError as e:
    print(f"{c.errcolor}Regex pattern error in '{pattern}': {c.normalcolor}{', '.join(e.args)}{colors['default']}")
    sys.exit()
  regexcs.append(regexc)

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

def process(p):
  global s
  matched_one = False
  line_number = 0
  p = p.removeprefix(".\\")
  if p not in s:
    if not regexcs:
      prn(p)
      s.add(p)
      return
    try:
      inf = open(p, "rb")
    except (PermissionError, IOError) as e:
      print(f"{c.errcolor}{'Permission denied' if type(e) is PermissionError else 'I/O error'}: {c.normalcolor}{p}")
    else:
      if not args.dotall:
        if args.l or args.negate:
          try:
            if args.proximity is not None:
              # proximity mode: check if all patterns appear within proximity lines
              last_match = {}
              for line in inf:
                line_number += 1
                for idx, rc in enumerate(regexcs):
                  if rc.search(line):
                    last_match[idx] = line_number
                # expire old matches
                to_expire = [idx for idx, ln in last_match.items() if line_number - ln >= args.proximity]
                for idx in to_expire:
                  del last_match[idx]
                if len(last_match) == len(regexcs):
                  if args.l:
                    prn(p)
                  break
              else:
                if args.negate:
                  prn(p)
            else:
              # OR mode: any regex match counts
              m = False
              for line in inf:
                m = any(rc.search(line) for rc in regexcs)
                if m:
                  break
              if m:
                if args.l:
                  prn(p)
              else:
                if args.negate:
                  prn(p)
          except MemoryError:
            print(f"{c.errcolor}Out of memory: {c.normalcolor}{p}")
        else:
          outofmemorycount = 0
          num_matches = 0
          if args.proximity is not None:
            # proximity mode: find windows where all patterns match within proximity lines
            buf_size = args.proximity + before_context + 1
            prox_buffer = deque(maxlen=buf_size)
            last_match = {}  # regex index -> line_number
            last_printed_line = 0
            after_remaining = 0
            while True:
              try:
                line_number += 1
                line = inf.readline()
                if not line:
                  break
                prox_buffer.append((line_number, line))
                # check each regex against this line
                for idx, rc in enumerate(regexcs):
                  if rc.search(line):
                    last_match[idx] = line_number
                # expire matches that have fallen outside the proximity window
                to_expire = [idx for idx, ln in last_match.items() if line_number - ln >= args.proximity]
                for idx in to_expire:
                  del last_match[idx]
                # handle after_context from a previous proximity match
                if after_remaining > 0 and line_number > last_printed_line:
                  prn(p, line_number, line)
                  last_printed_line = line_number
                  after_remaining -= 1
                # check for complete proximity match
                elif len(last_match) == len(regexcs):
                  num_matches += 1
                  if args.max_count is not None and num_matches > args.max_count:
                    break
                  min_ln = min(last_match.values())
                  max_ln = max(last_match.values())
                  start_ln = max(min_ln - before_context, last_printed_line + 1)
                  if matched_one and start_ln > last_printed_line + 1:
                    print("-----")
                  for buf_ln, buf_line in prox_buffer:
                    if start_ln <= buf_ln <= max_ln and buf_ln > last_printed_line:
                      prn(p, buf_ln, buf_line)
                  last_printed_line = max(last_printed_line, max_ln)
                  matched_one = True
                  after_remaining = after_context
                  last_match.clear()
              except MemoryError:
                outofmemorycount += 1
                if outofmemorycount <= max_err:
                  print(f"{c.errcolor}out of memory on line {c.linecolor}{line_number}{c.errcolor}: {c.normalcolor}{p}")
                elif outofmemorycount == max_err+1:
                  print(f"{c.errcolor}max out-of-memory notifications exceeded for file: {c.normalcolor}{p}")
          else:
            # normal mode (single or OR'd patterns)
            before_buf = deque()
            last_printed_line = 0
            after_remaining = 0
            while True:
              try:
                line_number += 1
                line = inf.readline()
                if not line:
                  break
                m = any(rc.search(line) for rc in regexcs)
                if m:
                  num_matches += 1
                  if args.max_count is not None and num_matches > args.max_count:
                    break
                if before_context or after_context:
                  if m:
                    start = max(line_number - before_context, last_printed_line + 1)
                    if matched_one and start > last_printed_line + 1:
                      print("-----")
                    for bln, bline in before_buf:
                      if bln >= start and bln > last_printed_line:
                        prn(p, bln, bline)
                        last_printed_line = bln
                    if line_number > last_printed_line:
                      prn(p, line_number, line)
                      last_printed_line = line_number
                    after_remaining = after_context
                    matched_one = True
                  elif after_remaining > 0:
                    prn(p, line_number, line)
                    last_printed_line = line_number
                    after_remaining -= 1
                  before_buf.append((line_number, line))
                  if len(before_buf) > before_context:
                    before_buf.popleft()
                else:
                  if m:
                    prn(p, line_number, line)
              except MemoryError:
                outofmemorycount += 1
                if outofmemorycount <= max_err:
                  print(f"{c.errcolor}out of memory on line {c.linecolor}{line_number}{c.errcolor}: {c.normalcolor}{p}")
                elif outofmemorycount == max_err+1:
                  print(f"{c.errcolor}max out-of-memory notifications exceeded for file: {c.normalcolor}{p}")
      else:
        try:
          data = inf.read()
        except MemoryError:
          print(f"{c.errcolor}Out of memory: {c.normalcolor}{p}")
        else:
          if args.negate:
            if not any(rc.search(data) for rc in regexcs):
              prn(p)
          elif args.l:
            if any(rc.search(data) for rc in regexcs):
              prn(p)
          else:
            for rc in regexcs:
              for x in rc.findall(data):
                prn(p, None, x)
  s.add(p)

s = set()

if not (regexcs or args.p or args.x_files or args.x_paths or args.files or args.f or args.l or args.recursive or args.dereference_recursive):
  quit()

try:
  wasap = False
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
          wasap = True
      else:
        i_files2.append(spec)
    if not (wasap or i_files2):
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
          for fn in os.listdir(p):
            if fnmatch(fn, spec) and not any(fnmatch(fn, spec2) for spec2 in x_files): #we're considering x_fils but not i_files.
              fn2 = os.path.join(p, fn)
              if not os.path.isdir(fn2):
                process(os.path.join(p, fn))
      else:
        i_files2.append(spec)
    i_files2 = i_files2 or ["*"]
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
