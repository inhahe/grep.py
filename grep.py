#todo: 
#take care of the abuse of global variables?
#add an option for multiline?
#showing multiline output with --dotall is ugly, since the first line isn't aligned with the next lines.
#grep.exe automatically detects binary files and just reports whether they match or not. 
#distinguish between file names and directory names in error messages?
#should we be nice to the users and change --x_paths and --x_files to --x-paths and --x-files?
#why is listing d:\ so slow even without a regex?
#add parameter for max_err?
#test out-of-memory conditions
#why does `grep.py --s` with anything directory following the s not generate an error? seems like a bug in argparse.
#detect circular recursion by checking inodes
#use os.scandir instead? it's faster because it uses a cache, but i'd have to figure out how to extract the filenames. 
# it returns DirEntry objects.
# also, if it uses a cache, could some files be missing from the scan? texnickal texnical said yes.
# apparently i could use os.walk and not search certain directories because 
# "<TeXNickAL> (You're allowed to alter the list of son-nodes it returns at each step.)"
#  “When topdown is True, the caller can modify the dirnames list in-place (perhaps using del or slice assignment), 
#  and walk() will only recurse into the subdirectories whose names remain in dirnames”
#  but os.walk uses scandir
#  os.walk has a follow_symlinks option
#issue: grep.py -R temp will show not only the symlinked dir temp but also teh symlinked dir temp\temp
#add sanity check to make sure user doesn't use -r AND -R?
#find out the long parameter names for -r and -R
#should we have an --include-symlinks or just use -p? both would result in the same thing except for when the files would show up 
# in the traversal. though we could have walk check all the i_paths for each directory that's a symlink. that shouldn't take a lot more
# cpu in most cases. that's what we're doing.
#we could show more error info, because i saw "PermissionError: [WinError 21] The device is not ready: 'd:\\'" when i didn't try/except
#automatically disable color if detected that output is being redirected to a file?
#decoding everything as utf-8 distorts the output of binary files
#would it be better to remove the spaces after colors after error messages?
#no-color automatically saving the setting might be annoying to users who are using --no-color just to output to a file...

from ast import Pass
import os, re, argparse, fnmatch, sys
from collections import deque
from pathlib import PurePath
from urllib.request import proxy_bypass

parser = argparse.ArgumentParser()
parser.add_argument("regex", nargs="?", help="regular expression pattern to search for")
parser.add_argument("files", nargs="*", help="search files matching these filename patterns")
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
parser.add_argument("-n", "--line_numbers", action="store_true", help="show line numbers")
parser.add_argument("--no-color", action="store_true", help="disable colorized output. grep.py will remember this setting in the future")
parser.add_argument("--set-colors", nargs="*", metavar="color", help="provide five color names to set the colors of filenames, colons, line numbers, match contents, and error messages to.\n"
                    "options are black, darkred, darkgreen, darkyellow, darkblue, darkmagenta, darkcyan, lightgray,  gray, red, green, yellow, blue, magenta, cyan, and white.\n"
                    "grep.py will remember the color settings in the future.\n"
                    "--set-colors with no options to restore colors to their defaults")

max_err = 5
 
if len(sys.argv) == 1:
  parser.print_help()
  sys.exit()
args = parser.parse_args()

use_colors = not args.no_color

filteresc = re.compile(r"[\x00-\x1F]") 

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
if os.path.isfile(cf):
  fncolor, coloncolor, lncolor, normalcolor, errcolor = (colors.get(x, colors["default"]) for x in open(cf).read().split())
else:
 fncolor, coloncolor, lncolor, normalcolor, errcolor = colors["green"], colors["gray"], colors["red"], colors["default"], colors["red"]
if args.set_colors == []:
  args.set_colors = "green gray red default red".split()
if args.set_colors:
  if len(args.set_colors) != 5:
    print(f"{errcolor}error: {normalcolor}wrong number of colors")
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

i_paths = args.p or ["."]
i_files = (((args.files or []) + (args.f or []))) or ["*"]
x_paths = [PurePath(p).parts for p in args.x_paths] if args.x_paths else []
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
      print(f"{errcolor}{'permission denied' if type(e) is PermissionError else 'i/o error'}: {normalcolor}{directory}")
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
  if not s:
    try:
      print(f"{normalcolor}{p}")
    except UnicodeEncodeError:
      print(f"{errcolor}error printing filename.")            
      error_printing = True
  else:
    s2 = s.decode("utf-8", errors="ignore").rstrip()
    s2 = filteresc.sub("", s2) 
    p = p.removeprefix(".\\")
    try:
      print(f"{fncolor}{p}", end="")
    except UnicodeEncodeError:
      print(f"{errcolor}error printing filename", end="")
      error_printing = True
    else:
      if args.line_numbers:
        print(f"{coloncolor}:{lncolor}{ln}{coloncolor}:", end="")
      else:
        print(f"{coloncolor}:", end="")
      try:
        print(f"{normalcolor}{s2}")#debug
      except UnicodeEncodeError:
        print(f"{errcolor}error printing {'match text' if args.dotall else 'line'}")
        error_printing = True
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
            print(f"{errcolor}out of memory: {normalcolor}{p}")
        else:
          outofmemorycount = 0
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
                    if matched_one: #if I weren't retarded, I could based this on lines_since_matched, before_context \and after_context alone.  i think?
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
              outofmemorycount += 1 
              if outofmemorycount <= max_err:
                print(f"{errcolor}out of memory on line {lncolor}line_number{errcolor}: {normalcolor}{p}")
              elif outofmemorycount == max_err+1:
                print(f"{errcolor}max out-of-memory notifications exceeded for file: {normalcolor}{p}")
      else:
        try: 
          data = inf.read()
        except MemoryError:
          print(f"{errcolor}out of memory: {normalcolor}{p}")
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

s = set()

if not (args.regex or args.p or args.x_files or args.x_paths or args.files or args.f or args.l or args.recursive or args.dereference_recursive):
  quit()

try: 
  i_files2 = []
  if args.recursive or args.dereference_recursive:
    for pf in i_files:
      p, spec = os.path.split(pf)
      if p:
        for p2, fn in walk(p, (p,)):
          if fnmatch(fn, spec) and not any(fnmatch(fn, spec2) for spec2 in x_files): #we're considering x_fils but not i_files. 
            process(p2)                                                              # that may be considered inconsistent.
      else:
        i_files2.append(spec)
    i_files2 = i_files2 or ["*"]
    for p in i_paths:
      for p, fn in walk(p, (p,)):
        if any(fnmatch(fn, spec2) for spec2 in i_files2) and not any(fnmatch(fn, spec3) for spec3 in x_files):
          process(p)
  else:
   for pf in i_files:
     p, spec = os.path.split(pf)
     if p:
       try:
         fns = os.listdir(p)
       except (PermissionError, IOError) as e:
         print(f"{errcolor}{'permission denied' if type(e) is PermissionError else 'i/o error'}: {normalcolor}{p}")
       else:
         for fn in fns:
           if fnmatch(fn, spec) and not any(fnmatch(fn, spec2) for spec2 in x_files): #we're considering x_fils but not i_files. 
             fn2 = os.path.join(p, fn)
             if not os.path.isdir(fn2):
               process(os.path.join(p, fn))                                                              # that may be considered inconsistent.
         else:
           i_files2.append(spec)
     i_files2 = i_files2 or ["*"]
     for path in i_paths:
       try:
         fns = os.listdir(path)
       except (PermissionError, IOError) as e:
         print(f"{errcolor}{'permission denied' if type(e) is PermissionError else 'i/o error'}: {normalcolor}{path}")
       else:
         for fn in fns:
           p = os.path.join(path, fn)
           if not os.path.isdir(p):
             if any(fnmatch(fn, spec) for spec in i_files2) and not any(fnmatch(fn, spec2) for spec2 in x_files):
               process(p)
  if not s:
    print("No files matched your criteria.")
except KeyboardInterrupt:
  print()
  print(f"{colors['magenta']}^C")
if error_printing:
  print()
  print(f"{normalcolor}There were errors printing results. `set PYTHONUTF8=1` to resolve this.") 
print(colors["default"], end="")
