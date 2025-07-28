#todo: 
#`--x_paths .` doesn't seem to work.
#do absolute and relative path specifications in grep.py's parameters mingle correctly?
#do i need to remove trailing "\" from excludes passed to walk?
#option to make filespecs case sensitive with fnmatchcase
#allow regex to be a list? then we have to think of a letter for the option
#apparently putting 'regex' as the first add_argument won't make it the first option, so it will probably be confused by the nargs="*"'s, so we have to use -s regex
#should i open all files as utf-8 and add errors=ignore?
#take out the ".\" from file printed file paths?
#take care of the abuse of global variables?
#find a way to allow regex to be a positional argument in the first position and f to be a positional argument in the second position
#add an option for multiline?

import os, re, argparse, fnmatch, sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-s", required=True, help="regular expression pattern to search for")
parser.add_argument("-r", action="store_true", help="search directories recursively")
parser.add_argument("-i", action="store_true", help="make search case-insensitive")
parser.add_argument("--dotall", action="store_true", help="make '.' match newlines")
parser.add_argument("-f", nargs="*", help="search files matching these filespecs")
parser.add_argument("-p", nargs="*", help="search these paths")
parser.add_argument("--x_files", nargs="*", help="exclude filespecs from search")
parser.add_argument("--x_paths", nargs="*", help="exclude paths from search")
args = parser.parse_args()

params = []
if args.dotall: 
  params.append(re.DOTALL)
if args.i:
  params.append(re.I)
regexc = re.compile(args.s.encode("utf-8"), *params)

i_paths = args.p or ["."] 
x_paths = args.x_paths or []
i_files = args.f or ["*"]
x_files = args.x_files or []

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

def process(p):
  if p not in s:
    try:
      inf = open(p, "rb")
    except:
      print("could not open: " + p)
    else:
      if not args.dotall:
        for line in open(p, "rb"):
          if regexc.search(line):
            print(p+":" + line.decode("utf-8", errors="ignore").rstrip())
    s.update(p)

s = set()
if args.r:
  for path in i_paths:
    for p, fn in walk(path, x_paths):
      if any(fnmatch.fnmatch(fn, pat) for pat in i_files) and not any(fnmatch.fnmatch(fn, pat) for pat in x_files):
        process(p)
