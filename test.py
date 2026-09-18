import os
def is_subpath(parent_path, child_path):
    # Smooth out relative path names, note: if you are concerned about symbolic links, you should use os.path.realpath too
    parent_path = os.path.abspath(parent_path)
    child_path = os.path.abspath(child_path)

    # Compare the common path of the parent and child path with the common path of just the parent path. Using the commonpath method on just the parent path will regularise the path name in the same way as the comparison that deals with both paths, removing any trailing path separator
    return os.path.commonpath([parent_path]) == os.path.commonpath([parent_path, child_path])



exclude = ["temp5"]
p = "d:\\temp4\\temp5"
print(exclude)
print(p)
if not any(is_subpath(p, x) for x in exclude):
  print(is_subpath(p, exclude[0]))	
  print("no exclusion")
print(is_subpath("d:\\temp4\\temp5", "temp5"))



def in_directory(file, directory, allow_symlink = False):
    #make both absolute    
    directory = os.path.abspath(directory)
    file = os.path.abspath(file)

    #check whether file is a symbolic link, if yes, return false if they are not allowed
    if not allow_symlink and os.path.islink(file):
        return False

    #return true, if the common prefix of both is equal to directory
    #e.g. /a/b/c/d.rst and directory is /a/b, the common prefix is /a/b
    return os.path.commonprefix([file, directory]) == directory

print(in_directory("temp5", "d:\\temp4\temp5"))


import os.path

def in_directory(file, directory):
    #make both absolute    
    directory = os.path.join(os.path.realpath(directory), '')
    file = os.path.realpath(file)

    #return true, if the common prefix of both is equal to directory
    #e.g. /a/b/c/d.rst and directory is /a/b, the common prefix is /a/b
    return os.path.commonprefix([file, directory]) == directory

print(in_directory("temp5", "d:\\temp4\temp5"))

import pathlib
p =PurePath("d:\\")

print(p.is_relative_to