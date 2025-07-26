#todo: 
#take care of the abuse of global variables?
#add an option for multiline?
#i once got an invalid character error at an f-string line, wtf
#showing match results from binary files is problematic. it looks really messy, the lines tend to be really long, and it can do weird things to the terminal.
#showing multiline output with --dotall is ugly, since the first line isn't aligned with the next lines.
#grep.exe automatically detects binary files and just reports whether they match or not. 
#distinguish between file names and directory names in error messages?
#--x_files * once gave "permission denied:" with no file name
#filter out terminal escape sequences (are they all below 32?) in match text. filtered out <32 but it still messes up the terminal.
#should we be nice to the users and change --x_paths and --x_files to --x-paths and --x-files?
#why is listing d:\ so slow even without a regex?
#add parameter for max_outofmemory?
#test out-of-memory conditions
#why does `grep.py --s` with anything directory following the s not generate an error? seems like a bug in argparse.
#options to exclude simlink files and/or simlink directories? gnu grep lets you do that and include symlink dirs that are on the command line.
#detect circular recursion by checking inodes?
#use os.scandir instead? it's faster because it uses a cache, but i'd have to figure out how to extract the filenames. it returns DirEntry objects.
# also, if it uses a cache, could some files be missing from the scan? texnickal texnical said yes.
# apparently i could use os.walk and not search certain directories because "<TeXNickAL> (You're allowed to alter the list of son-nodes it returns at each step.)"
#  “When topdown is True, the caller can modify the dirnames list in-place (perhaps using del or slice assignment), and walk() will only recurse into the subdirectories whose names remain in dirnames”
#  but os.walk uses scandir
#  os.walk has a follow_symlinks option
#issue: grep.py -R temp will show not only the symlinked dir temp but also teh symlinked dir temp\temp

import os, re, argparse, fnmatch, sys
from collections import deque
from pathlib import PurePath

parser = argparse.ArgumentParser()
parser.add_argument("regex", nargs="?", help="regular expression pattern to search for")
parser.add_argument("files", nargs="*", help="search files matching these filename patterns")
parser.add_argument("-f", nargs="*", help="search files matching these filename patterns. this option exists so you can search files even if you don't specify a regex")
parser.add_argument("-R", action="store_true", help="search directories recursively")
parser.add_argument("-r", action="store_true", help="search directories recursively, ignoring symlinks unless they're explicitly included")
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
parser.add_argument("-n", "--line_numbers", action="store_true", help="show line numbers")
parser.add_argument("--no-color", action="store_true", help="disable colorized output. grep.py will remember this setting in the future")
parser.add_argument("--set-colors", nargs="*", metavar="color", help="provide five color names to set the colors of filenames, colons, line numbers, match contents, and error messages to.\n"
                    "options are black, darkred, darkgreen, darkyellow, darkblue, darkmagenta, darkcyan, lightgray,  gray, red, green, yellow, blue, magenta, cyan, and white.\n"
                    "grep.py will remember the color settings in the future.\n"
                    "--set-colors with no options to restore colors to their defaults")

max_outofmemory = 5
 
if len(sys.argv) == 1:
  parser.print_help()
  sys.exit()
args = parser.parse_args()

filteresc = re.compile(r"[\0-\32]")

use_colors = not args.no_color

if args.no_color:
  d = os.path.dirname(os.path.abspath(__file__))
  cf = os.path.join(d, "grep.py.colors.conf")
  open(cf, "w").write("default default default default default")
  
if use_colors and os.name=="nt":
  try:
    from colorama import just_fix_windows_console
    just_fix_windows_console()
  except:
    use_colors = False    
    print("To enable colored output, `pip install colorama`")
    print()

if use_colors:
  colors = dict(zip("black, darkred, darkgreen, darkyellow, darkblue, darkmagenta, darkcyan, lightgray, gray, red, green, yellow, blue, magenta, cyan, white, default".split(", "), 
                     list(f"\033[0;{x}m" for x in range(30, 38)) + list(f"\033[1;{x}m" for x in range(30, 38))+["\033[0m"]))
else:
  colors = dict(zip("black, darkred, darkgreen, darkyellow, darkblue, darkmagenta, darkcyan, lightgray, gray, red, green, yellow, blue, magenta, cyan, white, default".split(", "), 
                     [""]*17))

d = os.path.dirname(os.path.abspath(__file__))
cf = os.path.join(d, "grep.py.colors.conf")

if args.set_colors == []:
  args.set_colors = "green gray red default red".split()
if args.set_colors:
  if len(args.set_colors) != 5:
    print(f"{colors['red']}error: {colors["default"]}wrong number of colors")
    quit()
  else:
    open(cf, "w").write(" ".join(args.set_colors))  
    fncolor, coloncolor, lncolor, normalcolor, errcolor = (colors.get(x, colors["default"]) for x in args.set_colors)
else:
  if os.path.isfile(cf):
    fncolor, coloncolor, lncolor, normalcolor, errcolor = (colors.get(x, colors["default"]) for x in open(cf).read().split())
  else:
    fncolor, coloncolor, lncolor, normalcolor, errcolor = colors["green"], colors["gray"], colors["red"], colors["default"], colors["red"]
            
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

if args.regex:
  try:
    regexc = re.compile(args.regex.encode("utf-8"), *params)
  except re.PatternError as e:
    print(f"{errcolor}Regex pattern error: {normalcolor}{', '.join(e.args)}")
    sys.exit()

i_paths = args.p or []
if not args.p:
  if len(args.files)==1 and args.r or args.R:
    p, fn = os.path.split(args.files[0])
    i_paths = [p]
    i_files = [fn]
  if i_paths == [""]: 
    i_paths = ["."]

i_files = (((args.files or []) + (args.f or []))) or ["*"]
x_paths = [list(PurePath(p).parts) for p in args.x_paths] if args.x_paths else []
x_files = args.x_files or []

lines_since_match = before_context + after_context + 1

def ld(directory):
  if not os.path.exists(directory):
    print(f"{errcolor}directory doesn't exist: {normalcolor}{directory}")
    return []
  elif not os.path.isdir(directory):
    print(f"{errcolor}is not a directory: {normalcolor}{directory}")
    return []
  else:
    try:
      r = os.listdir(directory)
    except (PermissionError, IOError) as e:
      print(f"{errcolor}{'permission denied' if type(e) is PermissionError else 'i/o error'}: {normalcolor}{p}")
      return []
    else:
      return r

def walk(directory, parts, exclude=[], ignore_symlinks=False, include_symlinks=[]):
  for fn in ld(directory): #todo: we should recursively pass the current parts list instead of using PurePath(p).parts for every p
    p = os.path.join(directory, fn)
    if os.path.isfile(p):
      yield (p, fn)
    elif os.path.isdir(p):
      parts2 = parts+[fn]
      if not (ignore_symlinks and os.path.islink(p) and not any(parts2[-len(x):] == x for x in include_symlinks)): #todo: is this right?
        if not any(parts2[-len(x):] == x for x in exclude): #this is really dirty but i don't know of a better solution do excludes how I want
          yield from walk(p, parts2, exclude, ignore_symlinks, include_symlinks)

def prn(p, ln=None, s=None):
  if not s:
    print(f"{normalcolor}{p}")
  else:
    s2 = s.decode("utf-8", errors="ignore").rstrip()
    s2 = filteresc.sub("", s2) #escape sequences still mess up the terminal. how is that? 
    p = p.removeprefix(".\\")
    if ln:
      print(f"{fncolor}{p}{coloncolor}:{lncolor}{ln}{coloncolor}:{normalcolor}{s2}")
    else:
      print(f"{fncolor}{p}{coloncolor}:{normalcolor}{s2}")

def decode(s):
  return s.decode("utf-8", errors="ignore").rstrip()    

def process(p):
  global printing_context, lines_since_match, tracking_context, s
  lines_since_match = before_context + after_context + 1
  matched_one = False
  context_buffer = deque([None]*(max(before_context, after_context)+1))
  line_number = 0
  p = p.removeprefix(".\\")
  if p not in s:
    if not args.regex:
      prn(p)
      s.add(p)
      return
    try:
      inf = open(p, "rb")
    except (PermissionError, IOError) as e:
      print(f"{errcolor}{'permission denied' if type(e) is PermissionError else 'i/o error'}: {normalcolor}{p}")
    else:
      if not args.dotall:
        if args.l or args.negate:
          try: 
            m = False
            for line in inf:
              m = regexc.search(line)
              if m:
                break
            if m:
              if args.l:
                prn(p)
            else:
              if args.negate:
                prn(p)
          except MemoryError:
            print("f{errcolor}out of memory: {normalcolor}{p}")
        else:
          outofmemory = 0
          num_matches = 0
          while True:
            try:
              line_number += 1
              line = inf.readline()
              if not line:
                break
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
                  if lines_since_match > before_context + after_context:
                    if matched_one: #if I weren't retarded, I could based this on lines_since_matched, before_context and after_context alone.
                      print("--")
                    for l in list(context_buffer)[-before_context-1:]:                 
                      if l: 
                        prn(p, line_number, l)
                  elif after_context < lines_since_match <= after_context + before_context:
                    for l in list(context_buffer)[-(lines_since_match-after_context):]:                 
                      if l:  
                        prn(p, line_number, l)
                  else:
                    prn(p, line_number, l)
                  lines_since_match = 0
                  matched_one = True
                else:
                  if lines_since_match <= after_context:
                    prn(p, line_number, line)
              else:
                if m:
                  prn(p, line_number, line)
            except MemoryError:
              outofmemory += 1 
              if outofmemory <= max_outofmemory:
                print("f{errcolor}out of memory on line {lncolor}line_number{errcolor}: {normalcolor}{p}")
              elif outofmemory == max_outofmemory+1:
                print("f{errcolor}max out-of-memory notifications exceeded for file: {normalcolor}{p}")
      else:
        try: 
          data = inf.read()
        except MemoryError:
          print("f{errcolor}out of memory: {normalcolor}{p}")
        else:
          if args.negate:
            if not regexc.search(data):
              prn(p)
          elif args.l:
            if regexc.search(data):
              prn(p)
          else:
            for x in regexc.findall(data):
              prn(p, None, x)
  s.add(p)

#n and n2 slightly slow down operations by making some things iterate over a list with one value 
def n(p, fn, i_p, i_f, ignore_symlinks=False, include_symlinks=[]):
  for path in i_p:
    for p, fn in walk(path, [path], x_paths, ignore_symlinks):
      if any(fnmatch(fn, pat) for pat in i_f) and not any(fnmatch(fn, pat) for pat in x_files):
        process(p)

def n2(p, i_f):
  for fn in ld(p):
    if any(fnmatch(fn, pat) for pat in i_f) and not any(fnmatch(fn, pat) for pat in x_files):
      if p:
        p2 = os.path.join(p, fn)
      else:
        p2 = fn #is this right?
      if os.path.isfile(p2): 
        process(p2)

s = set()
if not args.regex:
  if not (args.p or args.x_files or args.x_paths or args.files or args.f or args.l or args.r or args.R):
    quit()

try: 
  if args.r or args.R:
    for pf in i_files:
      p, spec = os.path.split(pf)
      if p:
        n(p, spec, [p], [spec], ignore_symlinks=args.r, include_symlinks=[p]+i_paths)
      else:
        n(p, spec, i_paths or ["."], i_files, ignore_symlinks=args.r, include_symlinks=i_paths)
  else: #can we make the following code simpler?
    if i_paths:
      for spec in i_files:
        p, fspec = os.path.split(spec)
        if p:
          n2(p, [fspec])
        else:
          for path in i_paths:
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
  print(f"{colors['magenta']}^C{colors['default']}")
  quit()
print(colors["default"], end="")
