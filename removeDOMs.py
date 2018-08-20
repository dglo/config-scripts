#!/usr/bin/env python
#

import sys
import getopt
import os

from calibration import *
from runConfig import *
from nicknames import *

def usage():
    """ Print program usage """
    print "Usage: %s [-h] [-v ###] [-n new_config_name]" % (sys.argv[0]), \
          "[-l dom_list] run_config.xml [dom1 dom2...]"
    print "    -h       print this help message"
    print "    -l       list of DOMs to remove"
    print "    -v ###   version number of new configuration"
    print "    -n name  name of new configuration (top level)"
    print "    -c name  name of new configuration (DOM config base name)"
    print "   dom       can be specified by position, MBID, or name"

def main():
    """
    Remove DOMs from a pDAQ run configuration.
    """
    #---------------------------------------------------
    # Parse command-line options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hl:v:n:c:",
                     ["help", "list", "version", "name", "domname"])
    except getopt.GetoptError as err:
        print str(err)
        usage()
        sys.exit(2)

    cfgVersion = None
    cfgNewName = None
    cfgDomName = None
    domFile = None
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-v", "--version"):
            cfgVersion = int(a)
        elif o in ("-n", "--name"):
            cfgNewName = a
        elif o in ("-c", "--domname"):
            cfgDomName = a            
        elif o in ("-l", "--list"):
            domFile = a                        
        else:
            assert False, "unhandled option"

    if len(args) < 1:
        usage()
        sys.exit(2)

    cfgName = args[0]

    # DOM positions, names, etc.
    nicks = nicknames()

    domList = []
    if (len(args) > 1):
        domList = [ nicks.findMBID(d) for d in args[1:] ]

    
    if domFile is not None:
        f = open(domFile, "r")
        if not f:
            print >> sys.stderr, "Error: couldn't open DOM list file", domFile
            sys.exit(-1)
            
        for line in f.readlines():
            val = line.rstrip()
            if len(val)==0:
                # skip blank lines
                continue
            
            d = nicks.findMBID(val)
            if d is not None:
                try:                
                    int(d, 16)
                    domList.append(d)                    
                except ValueError:
                    print >> sys.stderr, "Skipping invalid mbid: ", vals[0]
                    continue                

    if cfgNewName is None or \
            cfgVersion is None or \
            cfgDomName is None:
        print >> sys.stderr, "Usage!"
        print >> sys.stderr, ("Warning if you do not specify -v -n and -c "
                              "this program will overwrite configuration "
                              "files (bad)!")
        print >> sys.stderr, "-"*60
        usage()
        sys.exit(-1)
    
    print "Removing", len(domList), "DOMs from configuration", cfgName

    # Parse the run configuration files
    try:
        rc = RunConfig(cfgName, oldFormat=False)
    except RunConfigException:
        print "WARNING: couldn't parse run configuration; trying old format..."
        rc = RunConfig(cfgName, oldFormat=True)
        
    for mbid in domList:
        (string, dompos) = nicks.getDOMPosition(mbid)
        if rc.removeDOM(mbid):
            print "Removed DOM", mbid, "%02d-%02d" % (string, dompos), \
                nicks.getDOMName(mbid)
        else:
            print ("WARNING: couldn't find DOM %s %02d-%02d %s "
                   "to remove!") % (mbid, string,
                                    dompos, nicks.getDOMName(mbid))

            
    # Save updated run configuration files
    # Fix me deal with user specifying only some of these

    if (cfgNewName is not None) and \
            (cfgVersion is not None) and \
            (cfgDomName is not None):
        rc.write(newName=cfgNewName,
                 newVersion=cfgVersion,
                 newDomCfgName=cfgDomName)
    else:
        rc.write()

if __name__ == "__main__":
    main()
