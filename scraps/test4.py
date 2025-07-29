conf = """
[DEFAULT]
use_colors = True
allow_match_colors = False

[colors]
fncolor = green
coloncolor = gray
linecolor = red
normalcolor = default
errcolor = red
esccolor = blue
"""

import configparser
config = configparser.ConfigParser()
config.read_string(conf)
print(dict(config.items("colors")))
print(dict(config["colors"].items()))

#D:\visual studio projects\grep>test4.py
#{'use_colors': 'True', 'allow_match_colors': 'False', 'fncolor': 'green', 'coloncolor': 'gray', 'linecolor': 'red', 'normalcolor': 'default', 'errcolor': 'red', 'esccolor': 'blue'}
#{'fncolor': 'green', 'coloncolor': 'gray', 'linecolor': 'red', 'normalcolor': 'default', 'errcolor': 'red', 'esccolor': 'blue', 'use_colors': 'True', 'allow_match_colors': 'False'}