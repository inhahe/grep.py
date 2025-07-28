def process(p):
  global printing_context, lines_since_match, tracking_context, s
  lines_since_match = before_context + after_context + 1
  matched_one = False
  context_buffer = deque([None]*(max(before_context, after_context)+1))
  line_number = 0
  p = p.removeprefix(".\\")
  errprintingoutputcount = 0



def prn(p, ln=None, s=None):
  global errprintingoutputcount
  try:
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
  except UnicodeEncodeError:
    errprintingoutputcount += 1 
    if errprintingoutputcount <= max_err:
      if ln:
        print(f"{errcolor}error printing output (line {lncolor}{ln}{errcolor} of some file). `{normalcolor}set PYTHONUTF8=1{errcolor}` to solve this.")
      else:
        print(f"{errcolor}error printing output. `set PYTHONUTF8=1` to solve this.")            
    elif errprintingoutputcount == max_err+1:
      print(f"{errcolor}max errors-printing-output notifications exceeded for file.")
def decode(s):
  return s.decode("utf-8", errors="ignore").rstrip()    
