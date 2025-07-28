#todo: 
#option to make filespecs case sensitive with fnmatchcase
#take care of the abuse of global variables?
#add an option for multiline?
#put this on github
#oops, I got a "--" separating two files when I did `grep.py test  --context 10 -r`. must fix that. 
#i once got an invalid character error at an f-string line, wtf
#showing match results from binary files is problematic. it looks really messy, the lines tend to be really long, and it can do weird things to the terminal.
#grep.exe automatically detects binary files and just reports whether they match or not. 
#i get a re.PatternError in the file, but in the repl i get source.error, and it says there's no PatternError in re. wtf
#distinguish between file names and directory names in error messages?
#make colors an option?

from ast import Try
import os, re, argparse, fnmatch, sys
from fnmatch import fnmatch
from pathlib import Path
from collections import deque

black, darkred, darkgreen, darkyellow, darkblue, darkpurple, darkcyan, lightgray = ("\033["+str(x)+"m" for x in range(30, 38))
gray, red, green, yellow, blue, purple, cyan, white = ("\033[1;"+str(x)+"m" for x in range(30, 38))
if os.name=="nt":
  try:
    from colorama import just_fix_windows_console
    just_fix_windows_console()
  except:
    black, darkred, darkgreen, darkyellow, darkblue, darkpurple, darkcyan, lightgray = [""]*8
    gray, red, green, yellow, blue, purple, cyan, white = [""]*8
    print("To enable colored output, `pip install colorama`")

parser = argparse.ArgumentParser()
parser.add_argument("regex", help="regular expression pattern to search for")
parser.add_argument("files", nargs="*", help="search files matching these filename patterns")
parser.add_argument("-r", action="store_true", help="search directories recursively")
parser.add_argument("-i", action="store_true", help="make search case-insensitive")
parser.add_argument("--dotall", action="store_true", help="make '.' match newlines")
parser.add_argument("-p", nargs="*", help="search these paths")
parser.add_argument("--x_files", nargs="*", help="exclude these filename patterns from search")
parser.add_argument("--x_paths", nargs="*", help="exclude these paths from search")
parser.add_argument("-l", action="store_true", help="show only filenames")
parser.add_argument("-B", "--before-context", type=int, help="print this many lines of context preceding a match")
parser.add_argument("-A", "--after-context", type=int, help="print this many lines of context following a match")
parser.add_argument("-C", "--context", type=int, help="print this many lines of context both preceding and following a match")
parser.add_argument("-L", "--negate", action="store_true", help="show only files that contain no match")
parser.add_argument("-n", "--line_numbers", action="store_true", help="show line numbers")
parser.add_argument("-m", "--max-count", type=int, help="maximum number of matches to show")
args = parser.parse_args()

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

try:
  regexc = re.compile(args.regex.encode("utf-8"), *params)
except re.PatternError as e:
  print(red+"Regex pattern error: "+white+e.msg)
  sys.exit()

i_paths = args.p or None
if not args.p:
  if len(args.files)==1 and args.r:
    p, fn = os.path.split(args.files[0])
    i_paths = [p]
    i_files = [fn]
  if i_paths == [""]: 
    i_paths = ["."]

x_paths = args.x_paths or []
i_files = args.files or ["*"]
x_files = args.x_files or []

lines_since_match = before_context + after_context + 1

def is_subpath(path, directory):
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False

def ld(directory=None):
  try:
    r = os.listdir(directory)
  except (PermissionError, IOError) as e:
    print(red+("permission denied" if type(e) is PermissionError else "i/o error")+": "+white+p)
    return []
  else:
    return r

def walk(directory, exclude=[]):
  for fn in ld(directory):
    p = os.path.join(directory, fn)
    if os.path.isfile(p):
      yield (p, fn)
    elif os.path.isdir(p):
      if not any(is_subpath(p, x) for x in exclude):
        yield from walk(p, exclude)

def prn(p, ln, s):
  s2 = s.decode("utf-8", errors="ignore").rstrip()
  p = p.removeprefix(".\\")
  if args.line_numbers:
    print(f"{green}{p}{gray}:{red}{ln}{gray}:{white}{s2}")
  else:
    print(f"{green}{p}{gray}:{white}{s2}")

def decode(s):
  return s.decode("utf-8", errors="ignore").rstrip()    

def process(p):
  global printing_context, lines_since_match, tracking_context
  context_buffer = deque([None]*(before_context+1))
  line_number = 0
  if p not in s:
    try:
      inf = open(p, "rb")
    except (PermissionError, IOError) as e:
#      strerror = getattr(e, "strerror", None)
#      if strerror:
#        print(f"{red}could not open ({strerror}): {white}{p}")
#      else:
#        print(f"{red}could not open ({type(e)}: {white}{p}")
#      if strerror:
#        print(f"{red}{strerror}: {white}{p}")
#      else:
#        print(f"{red}{type(e)}: {white}{p}")
      print(red+("permission denied" if type(e) is PermissionError else "i/o error")+": "+white+p)
    else:
      if not args.dotall:
        if args.l or args.negate:
          for line in inf:
            if regexc.search(line):
              if not args.negate: 
                print(p)
              break
          else:
            if args.negate:
              print(p)

        else:
          num_matches = 0
          for line in inf:
            line_number += 1
            m = regexc.search(line)
            if m:
              num_matches += 1
              if args.max_count is not None and num_matches > args.max_count:
                break

            if before_context or after_context:
              lines_since_match += 1
              context_buffer.popleft()
              context_buffer.append(line)
              if m:
                if lines_since_match <= after_context:
                  prn(p, line_number, line)
                elif lines_since_match > after_context + before_context:
                  for l in list(context_buffer)[-(lines_since_match-after_context):]:                 
                    if l: 
                      prn(p, line_number, l)
                elif after_context < lines_since_match <= after_context + before_context:
                  for l in list(context_buffer)[-(lines_since_match-after_context):]:                 
                    if l: prn(p, line_number, l)
                lines_since_match = 0
              else:
                if lines_since_match <= after_context:
                  prn(p, line_number, line)
                elif lines_since_match == after_context + before_context:
                  print("--")
            else:
              if m:
                prn(p, line_number, line)
      else:
        data = inf.read()
        m = regexc.search(data)
        if m:
          if args.l:
            print(p)
          else:
            prn(p, None, m.group())
        else:
          if args.negate:
            print(p)
      s.add(p)

def n(p, fn, i_p, i_f):
  for path in i_p:
    for p, fn in walk(path, x_paths):
      if any(fnmatch(fn, pat) for pat in i_f) and not any(fnmatch(fn, pat) for pat in x_files):
        process(p.removeprefix(".\\"))

def n2(p, i_f):
  for fn in ld(None if p=="." else p):
    if any(fnmatch(fn, pat) for pat in i_f) and not any(fnmatch(fn, pat) for pat in x_files):
      if p:
        #p = fn if p=="." else os.path.join(p, fn)
        p2 = os.path.join(p, fn)
      if os.path.isfile(p2): 
        process(p2)

try: #can we make this code even less redundant?
  s = set()
  if args.r:
    for pf in i_files:
      p, spec = os.path.split(pf)
      if p:
        n(p, spec, [p], [spec])
      else:
        n(p, spec, i_paths or ["."], i_files)
  else:
    if i_paths:
      for spec in i_files:
        p, fspec = os.path.split(spec)
        if p:
          n2(p, [fspec])
        else:
          for path in i_paths:
            #n2(None if path=="." else path, i_files)
            n2(path, i_files)
    else:
     for f in i_files:
       p, spec = os.path.split(f)
       if p:
         n2(p, [spec])
       else:
         n2(".", [spec])

  if not s:
    print("No files matched your criteria.")

except KeyboardInterrupt:
  print("^C")
  quit()