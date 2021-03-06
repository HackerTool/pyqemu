#!/usr/bin/env python

import glob
import struct
import math
import os
#import pygraphviz as pgv

class MemoryEvent:
	def __init__(self, address, value, size, iswrite):
		self.address = address
		self.value = value
		self.size = size
		self.iswrite = iswrite

	def __str__(self):
		return "Addr: 0x%x, Value: 0x%x, Size: %d, isWrite: %d"%(self.address, self.value, self.size, self.iswrite)

class FunctionEvent:
	def __init__(self, eip, call_type):
		self.call_type = call_type
		self.eip = eip

	def __str__(self):
		return "EIP: 0x%x, Type: %d"%(self.eip, self.call_type)

class ExecEvent:
	def __init__(self, addr):
		self.addr = addr

class TranslateEvent:
	def __init__(self, addr, icount, instructions, total_count, movcount):
		self.addr = addr
		self.icount = icount
		self.instructions = instructions
		self.total_count = total_count
		self.movcount = movcount

class Heuristic:
	def __init__(self, result_callback):
		self.result_callback = result_callback

	def result(self, result):
		self.result_callback(result)

	def feed(self, event):
		raise Exception("Implement in inherited class!")

class LogEventReader(Heuristic):
	def feed(self, event):
		self.result_callback(event)

class ArithHeuristic(Heuristic):
	instructions = {
		"mov":0,
		"xor":1,
		"shx":2,
		"and":3,
		"or":4,
		"rox":5,
		"mul":6,
		"div":7,
		"bit":8,
		"add":9,
		"other":10,
		"counter":11,
	}
	def __init__(self, *args):
		Heuristic.__init__(self, *args)
		self.callstack = [0]
		self.bblcache = {}
		self.detected = {}

	def get_insns(self, l):
		return map(lambda x: self.instructions[x], l)

	def _check_symmetric(self, bbl):
		match = 0
		symmetric_instructions = self.get_insns(["xor","shx","and","or","rox"])
		for insn in bbl.instructions:
			if insn in symmetric_instructions:
				match += 1
		quotient = float(match)/(bbl.total_count-bbl.movcount)
		if quotient >= 0.40:
			return quotient
		return None

	def _check_asymmetric(self, bbl):
		match = 0
		asymmetric_instructions = self.get_insns(["mul","div","add"])
		for insn in bbl.instructions:
			if insn in asymmetric_instructions:
				match += 1
		quotient = float(match)/(bbl.total_count-bbl.movcount)
		if quotient >= 0.1:
			return quotient
		return None

	def handle_translate_event(self, event):
		bbl = event
		if bbl.total_count >= 20:
			quotient = self._check_symmetric(bbl)
			if quotient is not None:
				self.result("Detected Symmetric cipher: 0x%x , percentage: %f"%(event.addr, quotient))
				
		if bbl.total_count >= 10:
			quotient = self._check_asymmetric(bbl)
			if quotient is not None:
				self.result("Detected Asymmetric cipher: 0x%x , percentage: %f"%(event.addr, quotient))
		

	def do_call(self, eip):
		self.callstack.append(eip)

	def do_ret(self):
		self.callstack.pop()

	def handle_function_event(self, event):
		if event.call_type == 0:
			self.do_call(event.eip)
		else:
			self.do_ret()


	def feed(self, event):
		if isinstance(event, TranslateEvent):
			self.handle_translate_event(event)
		elif isinstance(event, FunctionEvent):
			self.handle_function_event(event)



class TaintGraphHeuristic(Heuristic):
	READ = 0
	WRITE = 1
	def __init__(self, *args):
		Heuristic.__init__(self,*args)
		self.graphstack = []
		self.callstack = []
		self.access_stack = []
		self.cycle = self.READ
		self.read_addresses = []
		self.write_addresses = []
		self.do_call(0x0)

		self.threshold = 3 #minimal quotient
		self.neighborhood = 8
		self.needed_edges = 8
		self.min_block_size = 4

	def do_call(self, eip):
		self.create_edges()
		self.graphstack.append({})
		self.callstack.append(eip)
		self.access_stack.append({})

	def do_ret(self):
		self.create_edges()
		eip = self.callstack.pop()
		access = self.access_stack.pop()
		l = len(self.graphstack[-1])
		if l >= 0:
			quotient,block  = self.analyze_graph(eip)
			access_num = 0
			for b in block:
				access_num += access[b]
			if quotient >= self.threshold and quotient >= float(len(block))*2/3 and len(block) >= 8:
				self.result("Taint - Graph size: %d Quotient: %f, Accesses in Block: %d,0x%x"%(len(block),quotient,access_num,eip))
		self.graphstack.pop()

	def get_blocks(self,eip):
		blocks = []
		cur_block = []
		keys = self.graph.keys()
		keys.sort()
		for key in keys:
			if len(cur_block) != 0 and (cur_block[-1]+1 != key or (len(filter(lambda x: abs(key-x)<self.neighborhood, self.graph[key])) < self.needed_edges)):
				blocks.append(cur_block)
				cur_block = []
			cur_block.append(key)

		if len(cur_block) > 0:
			blocks.append(cur_block)
		return filter(lambda x: len(x) >= self.min_block_size, blocks)

	def get_blocks_old(self):
		blocks = []
		cur_block = []
		for key in self.graph.keys():
			if len(cur_block) > 0 and cur_block[-1]+1 != key:
				blocks.append(cur_block)
				cur_block = []
			cur_block.append(key)
		if len(cur_block) > 0:
			blocks.append(cur_block)
		return blocks

	def block_quotient(self, block):
		num_edges = 0
		for i in block:
			for j in block:
				if i!=j and j in self.graph[i]:
					num_edges += 1
		return num_edges/len(block)

	def analyze_graph(self,eip):
		max_quotient = 0.0
		max_block = []
		for key,value in self.graph.items():
			self.graph[key] = set(value)
		blocks = self.get_blocks(eip)
		for block in blocks:
			block.sort()
			tmp = self.block_quotient(block)
			if tmp > max_quotient:
				max_quotient = tmp
				max_block = block
		return max_quotient,max_block

	def get_graph(self):
		return self.graphstack[-1]
	graph = property(get_graph)

	def create_edges(self):
		self.read_addresses = set(self.read_addresses)
		self.write_addresses = set(self.write_addresses)
		for r_addr in self.read_addresses:
			for w_addr in self.write_addresses:
				if not self.graph.has_key(r_addr):
					self.graph[r_addr] = []
				if not self.graph.has_key(w_addr):
					self.graph[w_addr] = []
				self.graph[r_addr].append(w_addr)
		self.read_addresses = []
		self.write_addresses = []
		
	def handle_mem_event(self, event):
		if event.iswrite == self.READ and self.cycle == self.WRITE:
			self.create_edges()
		self.cycle = event.iswrite
		size = event.size/8
		address = event.address
		address += size-1
		while size > 0:
			size -=1
			if not self.access_stack[-1].has_key(address):
				self.access_stack[-1][address] = 1
			else:
				self.access_stack[-1][address] += 1
			if event.iswrite == self.READ:
				self.read_addresses.append(address)
			elif event.iswrite == self.WRITE:
				self.write_addresses.append(address)
			address -= 1

	def handle_function_event(self, event):
		if event.call_type == 0:
			self.do_call(event.eip)
		else:
			self.do_ret()
		
	def feed(self, event):
		if isinstance(event, MemoryEvent):
			self.handle_mem_event(event)

		elif isinstance(event, FunctionEvent):
			self.handle_function_event(event)

class EntropyHeuristic(Heuristic):
	READ = 0
	WRITE = 1
	def __init__(self, *args):
		Heuristic.__init__(self, *args)
		self.callstack = []
		self.before_stack = []
		self.after_stack = []
		self.threshold = 0.3
		self.depth_stack = []
		self.do_call(0x0)

	def get_after_stack(self):
		return self.after_stack[-1]
	after = property(get_after_stack)

	def get_before_stack(self):
		return self.before_stack[-1]
	before = property(get_before_stack)

	def calc_entropy(self, d):
		data = d.values()
		histogramm = {}
		for i in range(256):
			histogramm[i] = float(0)
		for b in data:
			histogramm[b] += 1

		if len(data) < 100:
			return 0.0

		e_sum = 0.0
		for i in range(256):
			if histogramm[i] > 0:
				tmp_1 = float(histogramm[i])/len(data)
				tmp_2 = math.log(histogramm[i]/len(data))/math.log(2)
				e_sum += tmp_1*tmp_2
		scaled_entropy = (e_sum*-1)/math.log(min(len(data),256),2)
		return scaled_entropy


	def do_call(self, eip):
		self.callstack.append(eip)
		self.before_stack.append({})
		self.after_stack.append({})
		self.depth_stack.append(1)

	def do_ret(self):
		if len(self.depth_stack) > 1 and self.depth_stack[-1]+1 > self.depth_stack[-2]:
			self.depth_stack[-2] = self.depth_stack[-1]+1

		if self.depth_stack[-1] <= 3 and len(self.before) > 0 and len(self.after) > 16:
			before_entropy = self.calc_entropy(self.before)
			after_entropy = self.calc_entropy(self.after)
			diff = abs(before_entropy-after_entropy)
			#print "Before:\n%s"%self.before
			#print "After:\n%s"%self.after
			if before_entropy > 0.5 and after_entropy > 0.5 and diff > self.threshold:
				self.result("Entropy - diff: %f,0x%x"%(diff, self.callstack[-1]))
				#print "Before: %s"%("".join(map(chr,self.before.values())))
				#print "After: %s"%("".join(map(chr,self.after.values())))
			if before_entropy > 0:
				self.result("Entropy - before: %f,0x%x"%(before_entropy, self.callstack[-1]))
			if after_entropy > 0:
				self.result("Entropy - after: %f,0x%x"%(after_entropy, self.callstack[-1]))
		self.callstack.pop()
		self.before_stack.pop()
		self.after_stack.pop()
		self.depth_stack.pop()

	def handle_mem_event(self, event):
		size = event.size/8
		address = event.address
		address += size-1
		while size > 0:
			size -=1
			byte = (event.value >> (size*8)) &0xff
			if event.iswrite == self.READ:
				#self.after[address] = byte
				self.before[address] = byte
			elif event.iswrite == self.WRITE:
				self.after[address] = byte
			address -= 1

	def handle_function_event(self, event):
		if event.call_type == 0:
			self.do_call(event.eip)
		else:
			self.do_ret()

	def feed(self, event):
		if isinstance(event, MemoryEvent):
			self.handle_mem_event(event)
		elif isinstance(event, FunctionEvent):
			self.handle_function_event(event)

class Logfile:
	def __init__(self, filename):
		self.name, self.pid, self.tid = filename.split(" ")[:3]
		self.filename = filename
		self.logfile = open(filename,"r")

	def next(self):
		line = self.logfile.readline().strip()
		if line == "":
			return None
		return line

class Dumpfile:
	MEM_ACCESS = 0
	FUNCTION   = 1
	BBLEXEC    = 2
	BBLTRANSLATE = 3

	def __init__(self, filename):
		self.name, self.pid, self.tid = filename.split(" ")[:3]
		self.filename = filename
		self.dumpfile = open(filename,"r")

	def get_bytes(self, count):
		s = self.dumpfile.read(count)
		if len(s) < count:
			raise EOFError
		return s

	def next(self):
		try:
			event_type = struct.unpack("B",self.get_bytes(1))[0]
		except EOFError:
			return None

		if event_type == self.MEM_ACCESS:
			return self.memory_event()
		elif event_type == self.FUNCTION:
			return self.function_event()
		elif event_type == self.BBLEXEC:
			return self.exec_event()
		elif event_type == self.BBLTRANSLATE:
			return self.translate_event()
		else:
			raise Exception("READ ERROR - unknown event: %d"%event_type)

	def exec_event(self):
		addr = struct.unpack("<I",self.get_bytes(4))[0]
		return ExecEvent(addr)

	def translate_event(self):
		icount,total_count,movcount,addr = struct.unpack("<IIII",self.get_bytes(16));
		instructions = struct.unpack("<"+"I"*icount, self.get_bytes(4*icount));
		return TranslateEvent(addr, icount, instructions, total_count, movcount)

	def function_event(self):
		eip,call_type = struct.unpack("<Ib",self.get_bytes(5))
		return FunctionEvent(eip,call_type)

	def memory_event(self):
		address,value,options = struct.unpack("<IIb",self.get_bytes(9))
		size = options >> 1
		iswrite = options & 1
		return MemoryEvent(address,value,size,iswrite)
		
		

class Dumpreader(list):
	def __init__(self, path):
		list.__init__(self)
		dumpfiles = glob.glob(path+"/*.dump")
		for dumpfile in dumpfiles:
			self.append(Dumpfile(dumpfile))

class HeuristicReader(list):
	def __init__(self, path):
		heuristicfiles = glob.glob(path+"/*.log")
		for logfile in heuristicfiles:
			self.append(Logfile(logfile))

def p(x):
	print x

def usage():
	print "%s <directory>"%sys.argv[0]

import sys
if __name__ == "__main__":
	if len(sys.argv) < 2:
		usage()
	else:
		if not sys.argv[1].endswith("/"):
			sys.argv[1]+="/"
		d = Dumpreader(sys.argv[1])
		h = HeuristicReader(sys.argv[1])
		for dumpfile in d:
			print "Analyzing %s"%dumpfile.filename
			h1 = TaintGraphHeuristic(p)
			h2 = EntropyHeuristic(p)
			h3 = ArithHeuristic(p)
			event = dumpfile.next()
			while event is not None:
				if isinstance(event, FunctionEvent) and event.call_type == 0:
					print "Calling 0x%x"%event.eip
				h1.feed(event)
				h2.feed(event)
				h3.feed(event)
				del(event)
				event = dumpfile.next()
		for logfile in h:
			l1 = LogEventReader(p)
			event = logfile.next()
			while event is not None:
				l1.feed(event)
				del(event)
				event = logfile.next()
