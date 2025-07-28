#todo: 
#do absolute and relative path specifications in grep.py's parameters mingle correctly?
#do i need to remove trailing "\" from excludes passed to walk?
#option to make filespecs case sensitive with fnmatchcase
#allow regex to be a list? then we have to think of a letter for the option
#take care of the abuse of global variables?
#add an option for multiline?
#put this on github
#for dotall, should we print newlines as "\n"'s?
#option to print x number of lines preceding and following the matched line (this is going to be either difficult or cpu and memory intensive for dotall)
#--max-count  - max number of matches to show
#--line-number - show line numbers
#oops, I got a "--" separating two files when I did `grep.py test  --context 10 -r`. must fix that. 

import os, re, argparse, fnmatch, sys
from pathlib import Path
from collections import deque

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
parser.add_argument("-B", "--before-context", help="print this many lines of context preceding a match")
parser.add_argument("-A", "--after-context", help="print this many lines of context following a match")
parser.add_argument("-C", "--context", help="print this many lines of context both preceding and following a match")
parser.add_argument("-L", "--negate", action="store_true", help="show only files that contain no match")
parser.add_argument("-n", "--line_numbers", action="store_true", help="show line numbers")
args = parser.parse_args()

if args.dotall:
  args.line_numbers = False

before_context = int(args.before_context) if args.before_context else 0
after_context = int(args.after_context) if args.after_context else 0
if args.context:
  before_context = after_context = int(args.context)

params = []
if args.dotall: 
  params.append(re.DOTALL)
if args.i:
  params.append(re.I)
regexc = re.compile(args.regex.encode("utf-8"), *params)

i_paths = args.p or ["."] 
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

def walk(directory, exclude=[]):
  directory = directory.rstrip("\\")
  for fn in os.listdir(directory):
    p = os.path.join(directory, fn)
    if os.path.isfile(p):
      yield (p, fn)
    elif os.path.isdir(p):
      if not any(is_subpath(p, x) for x in exclude):
        yield from walk(p, exclude)

def prn(p, ln, s):
  s2 = s.decode("utf-8", errors="ignore").rstrip()
  if args.line_numbers:
    print(f"{p}:{ln}:{s2}")
  else:
    print(f"{p}:{s2}")

def decode(s):
  return s.decode("utf-8", errors="ignore").rstrip()    

def process(p):
  global printing_context, lines_since_match, tracking_context
  context_buffer = deque([None]*(before_context+1))
  line_number = 0
  if p not in s:
    try:
      inf = open(p, "rb")
    except (PermissionError, IOError):
      print("could not open: " + p)
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
          for line in inf:
            line_number += 1
            if before_context or after_context:
              lines_since_match += 1
              context_buffer.popleft()
              context_buffer.append(line)
              if regexc.search(line):
                if lines_since_match <= after_context:
                  prn(p, line_number, line)
                elif lines_since_match > after_context + before_context:
                  for l in list(context_buffer)[-(lines_since_match-after_context):]:                 
                    if l: 
                      prn(p, l)
                elif after_context < lines_since_match <= after_context + before_context:
                  for l in list(context_buffer)[-(lines_since_match-after_context):]:                 
                    if l: prn(p, l)
                lines_since_match = 0
              else:
                if lines_since_match <= after_context:
                  prn(p, line_number, line)
                elif lines_since_match == after_context + before_context:
                  print("--")
            else:
              if regexc.search(line):
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
      s.update(p)

s = set()
if args.r:
  for path in i_paths:
    for p, fn in walk(path, x_paths):
      if any(fnmatch.fnmatch(fn, pat) for pat in i_files) and not any(fnmatch.fnmatch(fn, pat) for pat in x_files):
        process(p.removeprefix(".\\"))
else:
  for path in i_paths:
    for fn in os.listdir(None if path=="." else path):
      if any(fnmatch.fnmatch(fn, pat) for pat in i_files) and not any(fnmatch.fnmatch(fn, pat) for pat in x_files):
        p = fn if path=="." else os.path.join(path, fn)
        if os.path.isfile(p): 
          process(p)