"""Script to download GIT repositories from .git folders."""
import argparse
import hashlib
import logging
import os
import shutil
import struct
import time
import zlib

from dataclasses import dataclass

from urllib.parse import urlparse

import requests
import urllib3

import colorlog

ROOT_FILES = ["config",
              "COMMIT_EDITMSG",
              "description",
              "HEAD",
              "index",
              "packed-refs",
              "logs/HEAD"
             ]

@dataclass
class TreeNode():
    """Node of a tree, just a dataclass."""
    name: str
    digest: str
    parent: None|str

class TreeBuilder():
    """Class to build directory-tree from nodes information."""
    def __init__(self) -> None:
        """Initialization of internal structs."""
        self.relations: dict[None|str, list[TreeNode]] = {}

    def add(self, name: str, digest: str, parent: None|str) -> None:
        """Adds a node to a list."""
        #dir names must have / at the end
        node = TreeNode(name, digest, parent)
        children = self.relations.setdefault(parent, [])
        children.append(node)

    def get_tree(self, parent: None|str, parent_name: str = "") -> list[tuple[str, str]]:
        """Return subtree elements in tuples (abs_path, hash)."""
        ret = []
        children = self.relations.get(parent, [])
        for child in children:
            child_path = parent_name + child.name
            ret.append((child_path, child.digest))
            ret += self.get_tree(child.digest, child_path)
        return ret

class TransportException(Exception):
    """Class for transport exceptions."""

class BaseTransport():
    """Base class for transport implementations."""
    out_dir: str
    target: str
    def is_file_retrieved(self, relative_path: str) -> bool:
        """Checks is file exists in out dir."""
        out_path = os.path.join(self.out_dir, relative_path)
        return os.path.exists(out_path)

    def is_object_retrieved(self, digest: str) -> bool:
        """Checks if object exists in out dir."""
        path = "objects/" + digest[:2] + "/" + digest[2:]
        return self.is_file_retrieved(path)

    def try_retrieve_file(self, relative_path: str) -> bool:
        """Retrieve a file, save it to out dir, return success status."""
        if self.is_file_retrieved(relative_path):
            return True
        return self.retrieve_file(relative_path)

    def try_retrieve_object(self, digest: str) -> bool:
        """Retrieve an object by it's hash."""
        path = "objects/" + digest[:2] + "/" + digest[2:]
        return self.try_retrieve_file(path)

    def retrieve_file(self, relative_path: str) -> bool:
        """Actually retieve and overwrite file on disk."""
        raise NotImplementedError

    def get_object_content(self, digest: str) -> bytes:
        """Returns decompressed object content."""
        path = "objects/" + digest[:2] + "/" + digest[2:]
        return self.get_content(path, True)

    def get_content(self, relative_path: str, compressed: bool = False) -> bytes:
        """Read file from disc and decompress it if needed."""
        path = os.path.join(self.out_dir, relative_path)
        with open(path, "rb") as file:
            data = file.read()

        if compressed:
            try:
                data = zlib.decompress(data)
            except zlib.error:
                return b""
        return data

class NetTransport(BaseTransport):
    """HTTP(S) transport implementation. Target is URL"""
    def __init__ (self, target: str, tor_host: str, tor_port: int):
        """Initialize transport."""
        self.target = target
        self.proxies = {"http" : f"socks5://{tor_host}:{tor_port}",
                        "https" : f"socks5://{tor_host}:{tor_port}"
                       }
        self.headers = {"User-Agent" :
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0"
                       }

        #Check TOR first
        res = requests.get("http://check.torproject.org/",
                         headers = self.headers,
                         proxies = self.proxies,
                         verify = False,
                        )
        if res.content.find(b"Congratulations. This browser is configured to use Tor.") == -1:
            raise TransportException("TOR check failed!")

        #parse URL
        fragments = urlparse(target)
        #check scheme
        scheme = fragments.scheme.lower()
        if scheme not in ["http", "https"]:
            raise TransportException(f"Unsupported scheme {scheme}! Check URL!")
        #check path (and modify the target)
        path = fragments.path.lower()
        if not path.endswith("/"):
            path += "/"
            self.target += "/"
        if not path.endswith("/.git/"):
            raise TransportException("URL doesn't ends with .git!")

        self.out_dir = fragments.netloc

    def retrieve_file(self, relative_path: str) -> bool:
        """Actually retieve and overwrite file on disk."""
        in_path = self.target + relative_path
        out_path = os.path.join(self.out_dir, relative_path)

        sleep_time = 1
        try:
            res = requests.get(in_path,
                             headers = self.headers,
                             proxies = self.proxies,
                             verify = False,
                             allow_redirects = False
                            )
        except Exception as exception:
            logging.error(f"ERROR: error downloading {in_path}")
            if isinstance(exception, requests.exceptions.TooManyRedirects):
                return False
            time.sleep(sleep_time)
            sleep_time += 1

        if res.status_code != 200:
            return False
        os.makedirs(os.path.dirname(out_path), exist_ok = True)
        with open(out_path, "wb") as file:
            file.write(res.content)
        return True

class FileTransport(BaseTransport):
    """File transport, target is .git directory on disk."""
    def __init__ (self, target: str):
        """Initialize transport."""
        self.target = target
        self.out_dir = "out"

        #does target exists?
        if not os.path.exists(target):
            raise TransportException(f"{target} doesn't exists!")
        #is it a dir?
        if not os.path.isdir(target):
            raise TransportException(f"{target} is not a rirectory!")

    def retrieve_file(self, relative_path: str) -> bool:
        """Actually retieve and overwrite file on disk."""
        in_path = os.path.join(self.target, relative_path)
        out_path = os.path.join(self.out_dir, relative_path)

        if not os.path.exists(in_path):
            return False
        #create subdirs
        os.makedirs(os.path.dirname(out_path), exist_ok = True)
        shutil.copy(in_path, out_path)
        return True

class FileROTransport(BaseTransport):
    """Read-only file transport. No write/copy operations performed."""
    def __init__ (self, target: str):
        """Initialize transport."""
        self.target = target
        self.out_dir = target

        #does target exists?
        if not os.path.exists(target):
            raise TransportException(f"{target} doesn't exists!")
        #is it a dir?
        if not os.path.isdir(target):
            raise TransportException(f"{target} is not a rirectory!")

    def retrieve_file(self, relative_path: str) -> bool:
        """Always return False, because we don't retrieve anything."""
        return False

def parse_index(data: bytes, tree: TreeBuilder) -> set[str]:
    """Parse object hashes from index file."""
    ret: set[str] = set()
    if len(data) < 0x0C:
        logging.error("ERROR: bad index file!")
        return ret

    pos = 0x0C
    objects_count = struct.unpack(">L", data[0x8:0xC])[0]
    while objects_count:
        begin_pos = pos
        pos += 0x28     #10 dwords - timestamps, attributes etc

        digest = data[pos : pos + 20].hex()
        logging.info(f"Object {digest} found in index")
        pos += 20

        name_len = struct.unpack(">H", data[pos : pos + 2])[0]
        name_len &= 0xFFF
        pos += 2

        name = data[pos : pos + name_len].decode()
        tree.add("/" + name, digest, None)
        pos += name_len + 1         #1 - terminating zero

        entry_size = pos - begin_pos
        if (entry_size % 8) != 0:
            pos += (8 - (entry_size % 8))

        ret.add(digest)
        objects_count -= 1
    return ret

def parse_logs_head(data: bytes) -> set[str]:
    """Retrieve object hashes from logs/HEAD file."""
    ret = set()
    lines = data.split(b"\n")
    for line in lines:
        fields = line.split(b" ")
        if len(fields) < 2:
            break
        for i in range(2):      #first two fields are commit hashes
            digest = fields[i].decode()
            if digest == "0000000000000000000000000000000000000000":
                continue
            ret.add(digest)
            logging.info(f"Commit {digest} found in logs/HEAD")
    return ret

def parse_commit(data: bytes, tree: TreeBuilder) -> set[str]:
    """Parse commit, retieve objects from it."""
    ret: set[str] = set()
    pos = data.find(b"\x00")
    if pos == -1:
        logging.error("ERROR: can't find zero byte in commit!")
        return ret
    data = data[pos + 1:]

    lines = data.split(b"\n")
    for line in lines:
        if line.startswith(b"tree "):
            digest = line[len(b"tree "):].decode()
            tree.add("/", digest, None)
            ret.add(digest)
        elif line.startswith(b"parent "):
            digest = line[len(b"parent "):].decode()
            ret.add(digest)
    return ret

def parse_tree(data: bytes, tree: TreeBuilder, parent: str) -> set[str]:
    """Parse tree, retrieve it's children."""
    ret: set[str] = set()
    pos = data.find(b"\x00")
    if pos == -1:
        logging.error("ERROR: can't find zero byte in tree!")
        return ret
    data = data[pos + 1:]

    pos = 0
    while pos < len(data):
        start = data.find(0x20, pos)
        end = data.find(0x00, pos)
        name = data[start + 1 : end].decode(errors = "replace")
        if data[pos] != 0x31:
            name += "/"
        digest = data[end + 1 : end + 21].hex()
        tree.add(name, digest, parent)
        ret.add(digest)
        pos = end + 21
    return ret

def parse_object(data: bytes, tree: TreeBuilder, parent: str) -> set[str]:
    """Retrieve object children."""
    #get object type
    pos = data.find(b" ")       #search space
    if pos == -1:
        logging.error("ERROR: Can't find object type!")
        return set()
    object_type = data[:pos]

    #blobs are files, do not parse them
    if object_type == b"blob":
        return set()
    if object_type == b"commit":
        return parse_commit(data, tree)
    if object_type == b"tree":
        return parse_tree(data, tree, parent)

    logging.error(f"ERROR: Unknown object type {object_type!r}")
    return set()

def objects_loop(transport: BaseTransport, tree: TreeBuilder, objects: set[str]) -> set[str]:
    """Recursively going through objects, returns unique objects."""
    ret = set()
    objects_count = len(objects)
    while objects_count != 0:
        next_level = set()
        index = 0
        success_count = 0
        while objects:
            index += 1
            digest = objects.pop()
            ret.add(digest)
            logging.info(f"Retrieving object {digest} ({index}/{objects_count})")
            if not transport.try_retrieve_object(digest):
                continue
            object_data = transport.get_object_content(digest)
            new_objects = parse_object(object_data, tree, digest)
            for i in new_objects:
                logging.info(f"Found object {i} in {digest}")
            next_level |= new_objects
            success_count += 1
        logging.debug(f"Retrieved {success_count}/{objects_count}")
        objects = next_level - ret
        objects_count = len(objects)
    return ret

def main() -> None:
    """Main function."""

    #enable logging
    colorlog.setup("git-rip.log")
    #disable logging from urllib3
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
    urllib3.disable_warnings()

    #parse cmdline
    argparser = argparse.ArgumentParser(description='Rip off data from .git directory')
    argparser.add_argument("target", help = "Target URL/directory/etc")
    argparser.add_argument("--transport",
                           choices = ["NET", "FILE"],
                           default = "NET",
                           help = "Type of transport"
                          )
    argparser.add_argument("--tor-host",
                           default = "127.0.0.1",
                           nargs = '?',
                           help = "TOR proxy host"
                          )
    argparser.add_argument("--tor-port", default = 9150, nargs = '?', help = "TOR proxy port")
    args = argparser.parse_args()

    transport: BaseTransport = BaseTransport()
    try:
        if args.transport == "NET":
            transport = NetTransport(args.target, args.tor_host, args.tor_port)
        elif args.transport == "FILE":
            transport = FileTransport(args.target)
    except TransportException as exception:
        logging.error(f"ERROR: {str(exception)}")
        return

    #print target and out dir
    logging.info(f"Working with {transport.target}, saving to {transport.out_dir}")

    #===============================
    #
    #Do the work!
    #
    #===============================

    #Get root files:
    for file_name in ROOT_FILES:
        logging.info(f"Retrieving {file_name}")
        if transport.try_retrieve_file(file_name):
            logging.info(f"{file_name} retrieved")
        else:
            logging.error(f"ERROR: No {file_name} found")

    #print hashes of index and logs/HEAD
    hash1 = hashlib.sha1(transport.get_content("index")).hexdigest()
    hash2 = hashlib.sha1(transport.get_content("logs/HEAD")).hexdigest()
    logging.debug(f"Hashes: {hash1} {hash2}")

    tree = TreeBuilder()

    #Get objects from logs/HEAD and process them
    objects = parse_logs_head(transport.get_content("logs/HEAD"))
    processed = objects_loop(transport, tree, objects)

    #Get objects from index and process them
    objects = parse_index(transport.get_content("index"), tree)
    objects = objects - processed
    logging.debug(f"{len(objects)} new objects from index")
    objects_loop(transport, tree, objects)

    #drop names_from_git
    items = tree.get_tree(None)
    items.sort()
    lines = []

    #list of dirs without children
    just_dirs = []
    for path, digest in items:
        if transport.is_object_retrieved(digest):
            resolution = "OK"
        else:
            resolution = "file missing"

        if path.endswith("/"):
            if tree.get_tree(digest):
                continue
            if path not in just_dirs:
                just_dirs.append(path)
        else:
            line = f"{path} - {digest} - ({resolution})"
            if line not in lines:
                lines.append(line)

    #add dirs we found, but without children
    for dir_path in just_dirs:
        for line in lines:
            if line.startswith(dir_path):
                break
        else:
            lines.append(dir_path)

    lines.sort()
    with open("names_from_git", "w") as file:
        for line in lines:
            file.write(line + "\n")


if __name__ == "__main__":
    main()
