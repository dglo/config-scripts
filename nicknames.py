#!/usr/bin/env python
#
# nicknames.py
#

# Grab DOM positions, names, and DOM id out of the nicknames file
# Return various dictionaries keyed on mainboard ID
#

import sys

NICKNAMES = "ic86/nicknames.txt"

class nicknames:
    def __init__(self, nicknameFile=NICKNAMES):
        self.posDict = {}
        self.idDict = {}
        self.nameDict = {}                
        self.initializeDicts(nicknameFile)
        
    def initializeDicts(self, filename):
        try:
            f = open(filename, "r")
        except:
            print "ERROR: couldn't open nicknames file for MBID mapping."
            sys.exit(1)

        # Skip header
        f.readline() 
        for line in f.readlines():
            vals = line.split()
            if len(vals) >= 4:
                mbid = vals[0]
                name = vals[2]
                pos = vals[3]
                id = vals[1]
                self.nameDict[mbid] = name.strip()
                self.idDict[mbid] = id
                (string, dom) = pos.split("-")
                try:
                    self.posDict[mbid] = [ int(string), int(dom) ]
                except:
                    pass
        f.close()
        
    def getDOMPosition(self, mbid):
        if mbid in self.posDict:
            return self.posDict[mbid]
        else:
            return None

    def getDOMName(self, mbid):
        if mbid in self.nameDict:
            return self.nameDict[mbid]
        else:
            return None
    
    def getDOMID(self, mbid):        
        if mbid in self.idDict:
            return self.idDict[mbid]
        else:
            return None
        
    def findMBID(self, dom):
        # Is this a mainboard ID already?
        if dom in self.nameDict:
            return dom
        for mbid in self.nameDict:
            if dom == self.nameDict[mbid]:
                return mbid
            if (mbid in self.posDict):
                posStr = "%02d-%02d" % (self.posDict[mbid][0],
                                        self.posDict[mbid][1])
                if (dom == posStr):
                    return mbid    
            if (mbid in self.idDict) and (dom == self.idDict[mbid]):
                return mbid
        return None
            
if __name__ == "__main__":
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = NICKNAMES
    nicks = nicknames(nicknameFile=filename)
    for mbid in nicks.nameDict:
        print mbid, nicks.getDOMID(mbid), \
            nicks.getDOMName(mbid), nicks.getDOMPosition(mbid)

    
