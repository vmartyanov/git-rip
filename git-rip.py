import sys
if (sys.version_info[0] != 3):
	print("This script requires Python version 3.x")
	exit(1)

import os
import time
import zlib
import shutil
import struct
import socket
import hashlib
import argparse
import urllib.parse

from typing import Set

import requests

try:
	import mva.log as log
	import mva.git as git
	import mva.net as net
except ImportError:
	print ("You need this lib to run the script: https://github.com/vmartyanov/PythonLib")
	exit(1)
log.fileName = "log"

def TransformURL(inURL: str) -> str:
	outURL = inURL
	if (outURL.endswith('/')):			#cut off the last slash if exists
		outURL = outURL[:-1]
	
	if (not outURL.endswith(".git")):
		log.Warning("There is no .git dir in URL!")
	
	components = urllib.parse.urlparse(inURL)
		
	if (components.scheme == ""):
		log.Warning("No protocol specified! Assuming HTTP")
		outURL = "http://" + inURL
	elif (components.scheme != "http" and components.scheme != "https"):
		log.Error("Unknown scheme " + components.scheme)
		return ""
	
	return outURL
	
def CheckTor(hostname: str, port: int) -> bool:
	log.Info("Checking TOR on " + hostname + ":" + str(port) + "...")
	net.SetProxy("socks5", hostname, port)
	try:
		if (not net.CheckTor()):
			log.Error("TOR isn't used!")
		else:
			log.Info("TOR is properly configured!")
			return True
	except:
		log.Error("Error checking TOR!")

	return False

def CreateDirs(baseDir: str) -> None:
	mustHaveDirs = [os.path.join(baseDir, "objects"), os.path.join(baseDir, "refs"), os.path.join(baseDir, "logs")]
	# "objects" and "refs" are needed to run "git fsck"
	for path in mustHaveDirs:
		if (not os.path.exists(path)):
			os.makedirs(path)

def GetFileContent(absPath: str) -> bytes:
	try:
		f = open(absPath, "rb")
	except:
		return b""
	data = f.read()
	f.close()
	return data

def GetDecompressedObject(baseDir: str, objName: str) -> bytes:
	ret = b""
	absPath = os.path.join(baseDir, "objects", objName[:2], objName[2:])
	compressed = GetFileContent(absPath)
	if (len(compressed) == 0):				#empty file, or it doesn't exists
		return ret
	
	try:
		ret = zlib.decompress(compressed)
	except:
		pass
	return ret

def RetrieveFile(target: str, relPath: str, baseDir: str, fromNetwork: bool, userAgent: str, compressed: bool = True) -> bool:
	finalPath = os.path.join(baseDir, relPath)
	finalPath = finalPath.replace("/", os.sep)
	if (os.path.exists(finalPath)):
		return True
	
	finalUrl = target + "/" + relPath
	
	if (fromNetwork):
		sleepTime = 1
		while(1):
			try:
				data = net.GET(finalUrl, 30, userAgent = userAgent).content
				break
			except BaseException as e :
				log.Error("Error downloading " + finalUrl + " (" + str(e) + ")")
				#Endless redirect loop - exit
				if (isinstance(e, requests.exceptions.TooManyRedirects)):
					return False
				time.sleep(sleepTime)
				sleepTime = sleepTime + 1
	else:
		finalUrl = finalUrl.replace("/", os.sep)
		data = GetFileContent(finalUrl)
		if (data == None):
			return False
	
	#check format
	if (compressed):
		if (len(data) < 2):
			#Yes, we can receive zero length response
			return False
		if (data[0] != 0x78 or data[1] != 0x01):
			return False
	else:
		if (data.decode(errors = "ignore").lower().find("<!doctype html") != -1):
			return False
		if (data.decode(errors = "ignore").lower().find("<html>") != -1):
			return False
	
	if (not os.path.exists(os.path.dirname(finalPath))):
		os.makedirs(os.path.dirname(finalPath))
	f = open(finalPath, "wb")
	f.write(data)
	f.close()
	return True

def RetrieveRootFiles(target: str, baseDir: str, userAgent: str, fromNetwork: bool = True) -> None:
	rootFiles = ["config", "COMMIT_EDITMSG", "description", "HEAD", "index", "packed-refs", "logs/HEAD"]

	for file in rootFiles:
		if (not RetrieveFile(target, file, baseDir, fromNetwork, userAgent, compressed = False)):
			log.Info("No " + file + " found")
		else:
			log.Info(file + " file retrieved")

def ParseLogsHead(absPath: str) -> Set[str]:
	out: Set[str] = set()
	try:
		file = open(absPath, "r", errors = "ignore")#ignore errors for comments in national langs
	except:
		return out
	for line in file:
		commitName = line.split()[1]
		log.Info("Commit " + commitName + " found in logs/HEAD")
		out.add(commitName)
	file.close()
	return out
	
def ProcessObject(target, objName, baseDir, gitTree, fromNetwork, userAgent):
	outSet = set()
	
	relPath = "objects/" + objName[:2] + "/" + objName[2:]
	if (not RetrieveFile(target, relPath, baseDir, fromNetwork, userAgent)):
		return (0, outSet)
	
	data = GetDecompressedObject(baseDir, objName)
	objType = git.GetObjectType(data)
	if (objType == None):
		log.Warning("Strange object without type in " + objName)
		return (1, outSet)

	pos = data.find(0x00)
	if (pos == -1):
		return (1, outSet)
	objData = data[pos + 1:]
		
	if (objType == "blob"):
		pass
	elif (objType == "commit"):
		objData = objData.decode(errors = "ignore")
		lines = objData.split('\n')
		for line in lines:
			fields = line.split()
			if (len(fields) < 2):
				continue

			if (fields[0] == "tree" or fields[0] == "parent"):
				if (fields[0] == "tree"):
					gitTree.Add(git.GitFile(fields[1], "", "dir"), None)
				log.Info("Found object " + fields[1] + " in commit " + objName)
				outSet.add(fields[1])
	elif (objType == "tree"):
		treeObjects = git.GetTreeFileObjs(objData)
		for o in treeObjects:
			log.Info("Found object " + o.hash + " in " + objName)
			outSet.add(o.hash)
			gitTree.Add(o, objName)
	else:
		log.Warning("Unknown object type " + objType + " in " + objName)
		
	return (1, outSet)
	
def GetObjectsFromIndex(baseDir, gitTree):
	ret = set()
	indexData = GetFileContent(os.path.join(baseDir, "index"))
	
	if (not git.CheckIndexSignature(indexData)):
		log.Error("It's not a git index!")
		return ret
	
	if (git.GetIndexVersion(indexData) != 0x02):
		log.Error("It could be an unsupported version of index")
		return ret
		
	indexEntriesCount = git.GetIndexElementsCount(indexData)
	log.Info(str(indexEntriesCount) + " elements in index")

	indexObjects = git.GetIndexFileObjs(indexData)
	for o in indexObjects:
		gitTree.Add(o, None)
		ret.add(o.hash)

	return ret
	
def PrintHashes(outDir):
	h = hashlib.sha1()
	h.update(GetFileContent(os.path.join(outDir, "index")))
	indexHash = h.digest().hex()
	
	h = hashlib.sha1()
	h.update(GetFileContent(os.path.join(outDir, "logs", "HEAD")))
	headHash = h.digest().hex()
	
	log.Result("Hashes: " + indexHash + " " + headHash)
	
def Main():
	processedObjects = set()
	gitTree = git.GitTree()

	argparser = argparse.ArgumentParser(description='Rip off data from .git directory')
	argparser.add_argument("targetURL", help = "Target URL")
	argparser.add_argument("--from-file", default = False, action='store_const', const=True, help = "Target is a directory, not URL")
	argparser.add_argument("--tor-host", default = "127.0.0.1", nargs = '?', help = "Hostname of tor proxy")
	argparser.add_argument("--tor-port", default = 9150, nargs = '?', help = "Portnumber of tor proxy")
	argparser.add_argument("--user-agent", default = None, nargs = '?', help = "User-agent")

	args = argparser.parse_args()

	if (args.from_file):
		url = args.targetURL
		outDir = "out"
	else:
		url = TransformURL(args.targetURL)
		if (url == ""):
			return
		outDir = urllib.parse.urlparse(url).netloc

	log.Info("Working with " + url)
	log.Info("Saving results to " + outDir)
	CreateDirs(outDir)

	if (not args.from_file):
		if (not CheckTor(args.tor_host, args.tor_port)):
			return

	RetrieveRootFiles(url, outDir, args.user_agent, not args.from_file)
	PrintHashes(outDir)
	objSet = ParseLogsHead(os.path.join(outDir, "logs", "HEAD"))
	objectsCount = len(objSet)
	while (objectsCount != 0):
		success = 0
		nextLevelSet = set()
		currentID = 0
		
		while (len(objSet) != 0):
			currentID = currentID + 1
			obj = objSet.pop()
			log.Info("Retrieving object " + obj + " (" + str(currentID) + "/" + str(objectsCount) + ")")
			
			processedObjects.add(obj)
			result, tmpList = ProcessObject(url, obj, outDir, gitTree, not args.from_file, args.user_agent)
			nextLevelSet = nextLevelSet | tmpList
			success = success + result

		log.Result(str(success) + "/" + str(objectsCount))
		objSet = nextLevelSet - processedObjects
		objectsCount = len(objSet)
		
	indexSet = GetObjectsFromIndex(outDir, gitTree)
	objSet = indexSet - processedObjects
	objectsCount = len(objSet)
	currentID = 0
	success = 0
	for obj in objSet:
		currentID = currentID + 1
		log.Info("Retrieving object " + obj + " (" + str(currentID) + "/" + str(objectsCount) + ")")
		result, tmpList = ProcessObject(url, obj, outDir, gitTree, not args.from_file, args.user_agent)
		success = success + result
	log.Result(str(success) + "/" + str(objectsCount))

	nameLines = []
	dupLines = []
	log.fileName = "names_from_git"
	for hash, name in gitTree.GetFiles():
		s = name + " - " + hash
		if (s in dupLines):
			continue
		dupLines.append(s)
		if (os.path.exists(os.path.join(outDir, "objects", hash[:2], hash[2:]))):
			s = s + " (OK)"
		else:
			s = s + " (file missing)"
		nameLines.append(s)

	nameLines.sort()
	for line in nameLines:
		log.Result(line)
Main()