import pefile
import os
import avl
import glob

class DLLHandler:
	def __init__(self, dlldir):
		self.dlldir = dlldir
		self.tree = avl.new()
		self.known_libs = {}

	def loadDLL(self, filename, imagebase):
		filename = filename.lower()
		if self.known_libs.has_key(filename):
			return
		if not imagebase in self.tree:
			try:
				nocasefilename = self._emulateFilenameNoCase(filename)
				if nocasefilename is None:
					raise IOError
				lib = DLLFile(nocasefilename, imagebase)
				self.tree.insert(lib)
				self.known_libs[filename] = lib
			except IOError:
				print "Could not load dll: %s"%filename
				self.known_libs[filename] = None

	def getLibByName(self, filename):
		filename = filename.lower()
		if self.known_libs.has_key(filename):
			return self.known_libs[filename]
		return None

	def getLib(self, address):
		try:
			lib = self.tree.at_most(address)
		except ValueError:
			return None
		if lib.includes(address):
			return lib
		else:
			return None

	def _emulateFilenameNoCase(self, filename):
		filelist = glob.glob(self.dlldir+"/*")
		filelist = map(lambda x: x.lower(), filelist)
		for file in filelist:
			if os.path.basename(file) == filename:
				return file
		return None

class DLLFile(dict):
	def __init__(self, filename, imagebase):
		self.imagebase = imagebase
		self.filename = os.path.basename(filename)

		dict.__init__(self)
		print "Loading %s"%filename
		# Load functions
		lib = pefile.PE(filename)
		self.size = lib.OPTIONAL_HEADER.SizeOfImage
		if hasattr(lib,"DIRECTORY_ENTRY_EXPORT"):
			for function in lib.DIRECTORY_ENTRY_EXPORT.symbols:
				self[imagebase+function.address] = (function.ordinal, function.address, function.name)
		del(lib)

	def includes(self, address):
		return self.imagebase <= address < self.imagebase+self.size
	def __len__(self):
		return self.size
	def __int__(self):
		return self.imagebase
	def __str__(self):
		return self.filename
	def __eq__(self, other):
		other = int(other)
		return self.imagebase == other
	def __lt__(self, other):
		other = int(other)
		return self.imagebase < other
	def __le__(self, other):
		other = int(other)
		return self.imagebase <= other
	def __ne__(self, other):
		other = int(other)
		return self.imagebase != other
	def __ge__(self, other):
		other = int(other)
		return self.imagebase >= other
	def __gt__(self, other):
		other = int(other)
		return self.imagebase > other