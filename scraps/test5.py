import argparse
parser = argparse.ArgumentParser(description="My parser")
parser.add_argument("--my_bool", type=bool)
cmd_line = ["--my_bool", "no"]
parsed_args = parser.parse_args(cmd_line)
print(parsed_args.my_bool)
