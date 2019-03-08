import sys
import zlib


f = open(sys.argv[1], "rb")
d = f.read()
f.close()

d = zlib.decompress(d)	
f = open(sys.argv[1] + ".out", "wb")
f.write(d)
f.close()
