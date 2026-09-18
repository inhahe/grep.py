from pathlib import Path
def is_subpath(path, directory): #directory is the subpath.
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
        return True
    except ValueError:
        return False

print(is_subpath("d:\\temp", "temp"))

