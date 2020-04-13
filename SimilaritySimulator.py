#Description: The following simulates a single level cache system with Non-Uniform Cache Access (NUCA) times using a PIN memory trace as input
#The simulated system uses XY routing for moving cache blocks between cores, and assumes a square grid topology
#The simulator supports both an LFU or an LRU eviction policy.
#Once the trace has been processed, it dumps various statistics to a text file
from math import log
from math import sqrt
from enum import Enum

class ReplacementPolicy(Enum):
    LFU = 0
    LRU = 1
    
class Block:
    def __init__(self, size):
        self.numUses = 0
        self.valid = 0
        self.tag = 0
        self.data = [0] * size

#A single slice is assigned to every core in the system
#Data blocks are assigned to slices using an S-NUCA policy
class Slice:
    def __init__(self, size, blockSize, numWays, replacementPolicy):
        numBlocks = int(size/blockSize)
        self.numWays = numWays
        self.numSetsPerSlice = int(numBlocks/numWays)
        self.blocks = [Block(blockSize*8) for i in range (numBlocks)]
        self.setOrderings = [list(range(numWays)) for i in range(self.numSetsPerSlice)]
        self.replacementPolicy = replacementPolicy
                             
    def read(self, set, tag):
        sliceSet = set % self.numSetsPerSlice
        setStartIdx = sliceSet * self.numWays

        for i in range(self.numWays):
            if self.blocks[i + setStartIdx].tag == tag and self.blocks[i + setStartIdx].valid:

                if self.replacementPolicy == ReplacementPolicy.LFU:
                   self.blocks[i + setStartIdx].numUses += 1
                elif self.replacementPolicy == ReplacementPolicy.LRU:
                   #Move readIdx to front of ordering to indicate this block is the most recently used
                   readIdx = i
                   self.setOrderings[sliceSet] = list(filter(lambda idx: idx != readIdx, self.setOrderings[sliceSet]))
                   self.setOrderings[sliceSet].insert(0, readIdx)
                else:
                    assert 0

                return self.blocks[i + setStartIdx].data

        return None

    def inject(self, set, tag, data):
        sliceSet = set % self.numSetsPerSlice
        setStartIdx = sliceSet * self.numWays
        victimIdx = -1

        if self.replacementPolicy == ReplacementPolicy.LRU:
            #Identify the least recently used block and then update ordering to move the new block into MRU position
            setOrdering = self.setOrderings[sliceSet]
            victimIdx = setOrdering[-1]
            self.setOrderings[sliceSet] = self.setOrderings[sliceSet][:-1]
            self.setOrderings[sliceSet].insert(0, victimIdx)
            victimIdx += setStartIdx

        elif self.replacementPolicy == ReplacementPolicy.LFU:
            #Eject the least frequently used block and replace it with the block to be injected
            victimIdx = setStartIdx
            numLeastUses = self.blocks[setStartIdx].numUses

            for i in range(self.numWays):
                if self.blocks[i + setStartIdx].numUses < numLeastUses:
                    victimIdx = i + setStartIdx
                    numLeastUses = self.blocks[victimIdx].numUses

            self.blocks[victimIdx].numUses = 1

        else: assert 0

        self.blocks[victimIdx].valid = 1
        self.blocks[victimIdx].tag = tag
        self.blocks[victimIdx].data = data

        return

    #Returns None if block not in system, does not automatically fetch and inject block (call inject function for this)
    def write(self, set, tag, blockOffset, data):
        sliceSet = set % self.numSetsPerSlice
        setStartIdx = sliceSet * self.numWays

        for i in range(self.numWays):
            if self.blocks[i + setStartIdx].tag == tag and self.blocks[i + setStartIdx].valid:
                for (byteIdx, byte) in enumerate(data):
                    self.blocks[i + setStartIdx].data[blockOffset + byteIdx] = byte

                if self.replacementPolicy == ReplacementPolicy.LFU:
                   self.blocks[i + setStartIdx].numUses += 1
                elif self.replacementPolicy == ReplacementPolicy.LRU:
                   #Move writeIdx to front of ordering                                                                                                                                                     
                   writeIdx = i
                   self.setOrderings[sliceSet] = list(filter(lambda idx: idx != writeIdx, self.setOrderings[sliceSet]))
                   self.setOrderings[sliceSet].insert(0, writeIdx)
                else:
                    assert(0)

                return self.blocks[i + setStartIdx].data

        return None

    #There are minor inconsistencies in some PIN traces
    # When a discrepancy between the memory trace and the simulated cache system is found, the system is updated to correct the discrepancy
    # Effectively, this function finds the block in the system that does not match the trace, and updates the data in it to resolve this
    def correctBlock(self, set, tag, data):
        sliceSet = set % self.numSetsPerSlice
        setStartIdx = sliceSet * self.numWays

        for i in range(self.numWays):
            if self.blocks[i + setStartIdx].tag == tag and self.blocks[i + setStartIdx].valid:
                self.blocks[i + setStartIdx].data = data

                if self.replacementPolicy == ReplacementPolicy.LFU:
                    self.blocks[i + setStartIdx].numUses += 1
                elif self.replacementPolicy == ReplacementPolicy.LRU:
                    # Move correctBlockIdx to front of ordering
                    correctBlockIdx = i
                    self.setOrderings[sliceSet] = list(
                        filter(lambda idx: idx != correctBlockIdx, self.setOrderings[sliceSet]))
                    self.setOrderings[sliceSet].insert(0, correctBlockIdx)
                    correctBlockIdx += setStartIdx
                else:
                    assert 0
        return

class Cache:
    def __init__(self, numSlices, sliceSize, blockSize, numWays, replacementPolicy):
        size = numSlices * sliceSize
        numBlocks = int(size/blockSize)
        numSets = int(numBlocks/numWays)
        assert(log(blockSize, 2).is_integer())
        assert(log(numSets, 2).is_integer())

        self.slices = [Slice(sliceSize, blockSize, numWays, replacementPolicy) for i in range (numSlices)]
        self.numSetsPerSlice = int(numBlocks/(numSlices*numWays))

        self.numBlockBits = int(log(blockSize, 2))
        self.numSetBits = int(log(numSets, 2))

        self.numSlices = numSlices
                             
    def getTag (self, address):
        return address >> (self.numBlockBits + self.numSetBits)

    def getSet (self, address):
        return (address >> self.numBlockBits) & int((1 << self.numSetBits) - 1)

    def getBlockOffset (self, address):
        return address & int((1 << self.numBlockBits) - 1)

    def read(self, address):
        tag = self.getTag(address)
        set = self.getSet(address)
        slice = int(set // self.numSetsPerSlice)

        return (slice, self.slices[slice].read(set, tag))

    def inject(self, address, blockData):
        tag = self.getTag(address)

        set = self.getSet(address)
        slice = int(set // self.numSetsPerSlice)

        return self.slices[slice].inject(set, tag, blockData)
        
    def correctBlock(self, address, blockData):
        tag = self.getTag(address)

        set = self.getSet(address)
        slice = int(set // self.numSetsPerSlice)

        return self.slices[slice].correctBlock(set, tag, blockData)

    def write(self, address, data):
        tag = self.getTag(address)
        set = self.getSet(address)
        blockOffset = self.getBlockOffset(address)
        slice = int(set // self.numSetsPerSlice)

        return (slice, self.slices[slice].write(set, tag, blockOffset, data))

    #Network topology dependent and routing dependent
    def getNumHops (self, coreID1, coreID2):
        #Assumes grid topology, XY routing
        gridDim = sqrt(self.numSlices)
        #Assumes topology is square
        assert (gridDim.is_integer())
        gridDim = int(gridDim)

        numXHops = abs(coreID1 % gridDim - coreID2 % gridDim)
        numYHops = abs(coreID1 // gridDim - coreID2 // gridDim)

        return numXHops + numYHops

    #Network topology dependent function and routing dependent
    def getNeighbours (self, coreID):
        #Assumes grid topology, XY routing
        gridDim = sqrt(self.numSlices)
        assert(gridDim.is_integer())
        gridDim = int(gridDim)
        neighbours = []

        #Up
        if (coreID >= gridDim):
            neighbours.append(coreID - gridDim)
        #Down
        if (coreID < gridDim * (gridDim - 1)):
            neighbours.append(coreID + gridDim)
        #Right
        if (coreID % gridDim < gridDim - 1):
            neighbours.append(coreID + 1)
        #Left
        if (coreID % gridDim > 0):
            neighbours.append(coreID - 1)

        return neighbours

numCores = 16
sliceSize = 1024 #bytes. Should be approximately 1/numCores of working set size
blockSize = 64 #bytes
numWays = 2

#Toggle replacement policy here
cache = Cache(numCores, sliceSize, blockSize, numWays, ReplacementPolicy.LRU)

numReadMisses = 0
numReadHits = 0
numWriteMisses = 0
numWriteHits = 0

numInstrs = 0
numCacheInconsistencies = 0
numCacheReadHits = 0

with open("memTrace.out") as traceFile:
    for line in traceFile:
        tokens = line.split()
        data = tokens[7:]
        instr = tokens[0:7]
        blockData = next(traceFile).split()
        instr.append(data)
        instr.append(blockData)

        #Read in blank new line
        next(traceFile)
        address = int(instr[3])

        traceBlock = [int(byte, 16) for byte in instr[8]]

        numInstrs += 1

        if numInstrs % 1000000 == 0:
            with open("statistics.txt", "a") as statisticsFile:
                statisticsFile.write("#Instructions: %d\n"%(numInstrs))
                statisticsFile.write("#Inconsistencies: %d\n"%(numCacheInconsistencies))
                statisticsFile.write("#Num cache read hits: %d\n"%(numCacheReadHits))
                statisticsFile.write("#Num total hits: %d\n\n"%(numCacheReadHits+numWriteHits))

        if instr[0] == 'R':
            cacheBlock = cache.read(address)
            if cacheBlock[1] != None:
                #Ensure the block read from the simulated cache is identical to the block in the trace
                #If not, correct
                if cacheBlock [1] != traceBlock:
                    numCacheInconsistencies += 1
                    cache.correctBlock(address, traceBlock)

                numCacheReadHits += 1
                blockCoreID = cacheBlock[0]
                requestingCoreID = int(instr[1]) % numCores

                #Will be used in future extentions of system
                #NUCA system: Certain addresses take longer to access than others (higher number of hops)
                numHops = cache.getNumHops(requestingCoreID, blockCoreID)
            else:
                numReadMisses += 1
                cache.inject(address, traceBlock)

        else:
            dataWrite = [int(byte, 16) for byte in instr[7]]
            cacheBlock = cache.write(address, dataWrite)
            if cacheBlock [1] == None:
                numWriteMisses += 1
                cache.inject(address, traceBlock)
            else:
                numWriteHits += 1
                #Ensure the block read from the simulated cache is identical to the block in the trace
                #If not, correct
                if cacheBlock[1] != traceBlock:
                    numCacheInconsistencies += 1
                    cache.correctBlock(address, traceBlock)