import os
import sys
import zlib


for file in os.listdir(sys.argv[1]):
	f = open(os.path.join(sys.argv[1], file), "rb")
	d = f.read()
	f.close()

	try:
		d = zlib.decompress(d)
		f = open(os.path.join(sys.argv[1], file) + ".out", "wb")
		f.write(d)
		f.close()
	except:
		pass
