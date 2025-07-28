import os
def walk(directory):
  directory = directory.rstrip("\\")
  for fn in os.listdir(directory):
    p = os.path.join(directory, fn)
    if os.path.isfile(p):
      yield (p, fn)
    elif os.path.isdir(p):
      yield from walk(p)

for p in walk("."): print(p)

def walk2(directory):
  directory = directory.rstrip("\\")
  for e in [os.path.join(directory, x) for x in os.listdir(directory)]:
    if os.path.isfile(e):
      yield e
    elif os.path.isdir(e):
      yield from walk2(e)

print("----")
for p in walk2("."): print(p)
