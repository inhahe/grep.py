#todo: 
#`--x_paths .` doesn't seem to work.
#do absolute and relative path specifications in grep.py's parameters mingle correctly?
#do i need to remove trailing "\" from excludes passed to walk?
import os, re, argparse, fnmatch
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-r", action="store_true", help="search directories recursively")
parser.add_argument("-i", action="store_true", help="make search case-insensitive")
parser.add_argument("--dotall", action="store_true", help="make '.' match newlines")
parser.add_argument("-f", nargs="*", help="search files matching these filespecs")
parser.add_argument("-p", nargs="*", help="search these paths")
parser.add_argument("--x_filespecs", nargs="*", help="exclude filespecs from search")
parser.add_argument("--x_paths", nargs="*", help="exclude paths from search")
args = parser.parse_args()
paths = args.p or ["."] 
x_paths = args.x_paths or []

def is_subpath(path, directory):
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False

def walk(directory, exclude=[]):
  directory = directory.rstrip("\\")
  for e in [os.path.join(directory, x) for x in os.listdir(directory)]:
    if os.path.isfile(e):
      yield e
    elif os.path.isdir(e):
      if not any(is_subpath(e, x) for x in exclude):
        walk(e)

if args.r:
  for path in paths:
    for path2 in walk(path, x_paths):
      print(path2)
    
    

