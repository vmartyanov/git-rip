import sys
if (sys.version_info[0] != 3):
        print("This script requires Python version 3.x")
        exit(1)

import os
import shutil

if (len(sys.argv) != 3):
  print ("Wrong commandline!")
  print ("Usage:")
  print (os.path.basename(__file__) + " inDir outDir")
  exit(1)

inDir = sys.argv[1]
outDir = sys.argv[2]

if (not os.path.isdir(inDir) or not os.path.isdir(outDir)):
  print ("inDir and outDir must be a directory")
  exit(1)

logFileName = os.path.join(inDir, "names_from_git")
logFile = open(logFileName, "r")
for line in logFile:
  line = line.strip("\n\r")
  if (not line.endswith(" (OK)")):
    continue

  l = len(line)
  hash = line[l - len(" (OK)") - 40: l - len(" (OK)")]
  nameStart = line.find("[RESULT] ") + len("[RESULT] ")
  nameEnd = line.rfind(" - ")
  fileName = line[nameStart : nameEnd]

  fileName = fileName.split("/")[-1]
  ext = fileName
  l = fileName.split(".")
  if (len(l) < 2):    #no dot
    pass
  elif (len(l) == 2 and l[0] == ""):
    pass              #.name case
  else:
    ext = l[-1]

  srcPath = os.path.join(inDir, "wwwroot", ".git", "objects", hash[:2], hash[2:])

  dstDir = os.path.join(outDir, ext)
  if (not os.path.exists(dstDir)):
    os.makedirs(dstDir)
  shutil.copy(srcPath, dstDir)

logFile.close()