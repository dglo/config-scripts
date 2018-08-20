#!/usr/bin/env python
#
# Get a list of all DOMs not in the configuration or with zero
# high voltage.
#

from nicknames import *
from runConfig import *

if (len(sys.argv) != 2):
    print "Usage: %s <runconfig.xml>" % sys.argv[0]
    sys.exit(0)

rc = RunConfig(sys.argv[1], oldFormat=False)
nicks = nicknames()

goodList = []
for dc in rc.getDOMConfigs():
    for mbid in dc.getDOMs():
        # Get the HV setting
        hv = int(dc.getDOMSetting(mbid, 'pmtHighVoltage'))
        if (hv > 0):
            goodList.append(nicks.getDOMPosition(mbid))

omkeyString = "bad_doms = [ "

# List of complete deployed DOMs
nBad = 0
for string in xrange(1,87):
    for dom in xrange(1,64):
        if (dom > 60) and (string > 81):
            continue
        pos = [string, dom]
        if pos not in goodList:
            nBad = nBad+1
            omkeyString += " icetray.OMKey(%d,%d)," % (pos[0], pos[1])
            if (nBad % 3 == 0):
                omkeyString += "\n"

# Remove trailing comma, close brackets
omkeyString = omkeyString[:-1]
omkeyString += " ]"

print "Found %d bad DOMs" % nBad
print omkeyString

