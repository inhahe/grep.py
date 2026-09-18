try:
  open('.vs\\grep\\FileContentIndex\\82ef6f13-3543-47f7-b7b4-2f7a3ffc4fce.vsidx')
except PermissionError as e:
  for x in dir(e):
    print(x+":") 
    print(getattr(e, x, None))