#eee

import re

filteresc = re.compile(r"[\x00-\x1F]") 
filteresc = re.compile(r"[\x00-\x09\x0b-\x1f]")

def fe(s2):
  s3 = []
  laststart = 0
  for m in filteresc.finditer(s2):
    start = m.start()
    s3.extend((fr"{s2[laststart+1:start]}\x{ord(s2[start]):02x}"))
    laststart = start
  s3.append(s2[laststart+1:])
  return ''.join(s3)

a = "a"+chr(0)+"b"
print(fe(a))
a = "1"+a
print(fe(a))
a = "test\ntest"
print(fe(a))