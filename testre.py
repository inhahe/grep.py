import re
try:
  re.compile("eeee(eee")
except re.PatternError as e:
  for x in dir(e):
    print(x+":") 
    print(getattr(e, x))