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
import argparse
import urllib.parse

import requests

sys.path.append("C:\\Programming\\python_lib")
import mva.log as log
import mva.git as git
import net2
log.fileName = "log"

def TransformURL(inURL):
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
		return None
	
	return outURL
	
def CheckTor():
	log.Info("Checking TOR...")
	net2.SetProxy("socks5", "127.0.0.1", 9150)
	try:
		if (not net2.CheckTor()):
			log.Error("TOR isn't used!")
		else:
			log.Info("TOR is properly configured!")
			return True
	except:
		log.Error("Error checking TOR!")

	return False

def CreateDirs(baseDir):
	mustHaveDirs = [os.path.join(baseDir, "objects"), os.path.join(baseDir, "refs"), os.path.join(baseDir, "logs")]
	# "objects" and "refs" are needed to run "git fsck"
	for path in mustHaveDirs:
		if (not os.path.exists(path)):
			os.makedirs(path)

def GetFileContent(absPath):
	try:
		f = open(absPath, "rb")
	except:
		return b""
	data = f.read()
	f.close()
	return data

def GetDecompressedObject(baseDir, objName):
	absPath = os.path.join(baseDir, "objects", objName[:2], objName[2:])
	compressed = GetFileContent(absPath)
	if (len(compressed) == 0):				#empty file, or it doesn't exists
		return b""
	return zlib.decompress(compressed)

def RetrieveFile(target, relPath, baseDir, fromNetwork, compressed = True):
	finalPath = os.path.join(baseDir, relPath)
	finalPath = finalPath.replace("/", os.sep)
	if (os.path.exists(finalPath)):
		return True
	
	finalUrl = target + "/" + relPath
	
	if (fromNetwork):
		sleepTime = 1
		while(1):
			try:
				data = net2.GET(finalUrl, 30).content
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

def RetrieveRootFiles(target, baseDir, fromNetwork = True):
	rootFiles = ["config", "COMMIT_EDITMSG", "description", "HEAD", "index", "packed-refs", "logs/HEAD"]
	
	for file in rootFiles:
		if (not RetrieveFile(target, file, baseDir, fromNetwork, compressed = False)):
			log.Info("No " + file + " found")
		else:
			log.Info(file + " file retrieved")

def ParseLogsHead(absPath):
	out = set()
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
	
def ProcessObject(target, objName, baseDir, gitTree, fromNetwork):
	outSet = set()
	
	relPath = "objects/" + objName[:2] + "/" + objName[2:]
	if (not RetrieveFile(target, relPath, baseDir, fromNetwork)):
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
	
def Main():
	processedObjects = set()
	gitTree = git.GitTree()
	
	argparser = argparse.ArgumentParser(description='Rip off data from .git directory')
	argparser.add_argument("targetURL", help = "Target URL")
	argparser.add_argument("--from-file", default = False, action='store_const', const=True, help = "Target is a directory, not URL")

	args = argparser.parse_args()
	
	if (args.from_file):
		url = args.targetURL
		outDir = "out"
	else:
		url = TransformURL(args.targetURL)
		if (url == None):
			return
		outDir = urllib.parse.urlparse(url).netloc
	
	log.Info("Working with " + url)
	log.Info("Saving results to " + outDir)
	CreateDirs(outDir)
	
	if (not CheckTor()):
		return
	
	RetrieveRootFiles(url, outDir, not args.from_file)
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
			result, tmpList = ProcessObject(url, obj, outDir, gitTree, fromNetwork = not args.from_file)
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
		result, tmpList = ProcessObject(url, obj, outDir, gitTree, fromNetwork = not args.from_file)
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