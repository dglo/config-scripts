#!/usr/bin/env python
#

import sys
import getopt
import os
import re
import json
import math

from calibration import *
from runConfig import *
from nicknames import *

# Calibration settings rules
GAIN_SCINT = 4.7e6
GAIN_INICE = 1e7
GAIN_IT_HIGH = 5e6
GAIN_IT_LOW = 1e5

DISC_SCINT_PE = 0.5
DISC_INICE_PE = 0.25
DISC_IT_HIGH = [ 1020, 580 ]
DISC_IT_LOW  = [ 620, 560 ]

ATWD_FREQ_MHZ = 300.

# Maximum HV settings
MAX_HV = 3300
MAX_HV_SCINT = 2500

# Warning settings
WARN_HV_CHANGE = 15
WARN_SPE_DISC_CHANGE = 5
WARN_ATWD_FREQ_CHANGE = 5
WARN_ATWD_FREQ_CHANGE_MHZ = 0.5
WARN_MAX_GAIN_DIFF_PCT = 15

# Difference output log for plotting
OUTPUT_FILE = "calupdate.txt"

def usage():
    """ Print program usage """
    print "Usage: %s [-htsi] [-v ###] [-n new_config_name]" % (sys.argv[0]), \
        "[-c new_domconfig_name] [-g gain_file]",\
        "[-d disc_file] [-a atwd_file] [-b baseline_file]", \
        "[-r beacon_rate] run_config.xml calibration_dir"
    print "    -h       print this help message"
    print "    -t       test run; do not write out new configuration"
    print "    -s       save differences in settings for later plotting"
    print "    -i       do not update IceTop high voltage or beacon rate settings"
    print "    -g       gain override file"
    print "    -d       discriminator override file"
    print "    -a       ATWD override file"
    print "    -b       baseline override file"
    print "    -r       target beacon rate in Hz"
    print "    -v ###   version number of new configuration"
    print "    -n name  name of new configuration (top level)"
    print "    -c name  name of new configuration (DOM config base name)"    

def getGainExceptions(filename):
    gainExc = {}
    hvExc = {}
    if filename is not None:
        f = open(filename, "r")
        if not f:
            print >> sys.stderr, "ERROR: couldn't open gain exceptions file",filename
            sys.exit(-1)
        for line in f.readlines():

            if line.strip().startswith("#"):
                continue

            m = re.match("\s*([0-9a-f]+)\s+([-.0-9eE]+)\s+([-.0-9eE]+)\s*", line)
            if m:
                (mbid, hv, gain) = m.group(1,2,3)
                if hv != "-":
                    hvExc[mbid] = int(hv)
                if gain != "-":
                    gainExc[mbid] = float(gain)
        f.close()
    return (hvExc, gainExc)

    
def getDiscExceptions(filename):
    discExc = {}
    discExcPE = {}
    if filename is not None:
        f = open(filename, "r")
        if not f:
            print >> sys.stderr, "ERROR: couldn't open exceptions file",filename
            sys.exit(-1)
        for line in f.readlines():
            if line.strip().startswith("#"):
                continue
            m = re.match("\s*([0-9a-f]+)\s+(\d+)\s+(\d+).*", line)
            if m:
                (mbid, speDisc, mpeDisc) = m.group(1,2,3)
                discExc[mbid] = [int(speDisc), int(mpeDisc)]
            else:
                m = re.match("\s*([0-9a-f]+)\s+([0-9.]+).*", line)
                if m:
                    (mbid, speDiscPE) = m.group(1,2)
                    discExcPE[mbid] = speDiscPE
        f.close()
    return (discExc, discExcPE)

def getBaselineExceptions(filename):
    blExc = {}
    if filename is not None:
        f = open(filename, "r")
        if not f:
            print >> sys.stderr, "ERROR: couldn't open exceptions file",filename
            sys.exit(-1)
        for line in f.readlines():
            if line.strip().startswith("#"):
                continue
            m = re.match("\s*([0-9a-f]+)\s+.*", line)
            if m:
                mbid = m.group(1)
                # No baseline override; just recalculate
                blExc[mbid] = [0, 0, 0, 0, 0, 0]
        f.close()
    return blExc


def getATWDExceptions(filename):
    chipExc = {}
    bias0Exc = {}
    bias1Exc = {}
    if filename is not None:
        f = open(filename, "r")
        if not f:
            print >> sys.stderr, "ERROR: couldn't open ATWD exceptions file",filename
            sys.exit(-1)
        for line in f.readlines():
            if line.strip().startswith("#"):
                continue
            m = re.match("\s*([0-9a-f]+)\s+([-01])\s+([-.0-9eE]+)\s+([-.0-9eE]+)\s*", line)
            if m:
                (mbid, chip, bias0, bias1) = m.group(1,2,3,4)
                if chip != "-":
                    chipExc[mbid] = int(chip)
                if bias0 != "-":
                    bias0Exc[mbid] = int(bias0)
                if bias1 != "-":
                    bias1Exc[mbid] = int(bias1)

        f.close()
    return (chipExc, bias0Exc, bias1Exc)


# Get the integer rate setting (nominally also in Hz) that will
# result in a DOM pulser rate closest to the target rate in Hz.
# Note that the setting in the file can be higher, because domapp 
# rounds down to the next lowest setting possible in the FPGA.
def getRateSetting(rate):

    # FPGA clock divider setting
    s = int(26 + math.log(rate/(1e9/25))/math.log(2))
    if (s < 0):
        s = 0
    if (s > 17):
        s = 17
        
    # Actual FPGA rate in Hz
    rate_lo = (1e9/(25.0*(1<<26)))*(1<<s)
    rate_hi = 2*rate_lo
    # Is the next highest rate actually closer?
    if (math.fabs(rate-rate_lo) >= math.fabs(rate-rate_hi)) and (s < 17):
        s = s + 1

    # Now find integer requested rate that results in target FPGA rate
    # print "DEBUG: actual rate = ",(1e9/(25.0*(1<<26)))*(1<<s)
    rate_int = int(math.ceil(1e9/(25.0*(1<<26)))*(1<<s))
    # Make sure it worked
    if (int(26 + math.log(rate_int/(1e9/25))/math.log(2)) != s):
        print "WARNING: internal error calculating target rate!"
    
    return rate_int


def main():
    """
    Update a pDAQ run configuration with new calibration settings:
    new PMT high voltage, new SPE and (for IceTop) MPE discriminator
    settings.  Cross-check existence of calibration results vs. DOMs
    in the configuration.
    """
    #---------------------------------------------------
    # Parse command-line options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "htsid:g:a:b:r:v:n:c:",
                     ["help", "test", "save", "icetop", 
                      "disc", "gain", "atwd", "baseline", "rate",
                      "version", "name", "domname"])
    except getopt.GetoptError as err:
        print str(err)
        usage()
        sys.exit(2)

    dryrun = False
    savePlotResults = False
    icetopDisable = False
    cfgVersion = None
    cfgNewName = None
    cfgDomName = None
    discFile = None
    gainFile = None
    atwdFile = None
    baselineFile = None
    beaconRate = None
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-t", "--test"):
            dryrun = True
        elif o in ("-s", "--save"):
            savePlotResults = True
        elif o in ("-i", "--icetop"):
            icetopDisable = True                        
        elif o in ("-v", "--version"):
            cfgVersion = int(a)
        elif o in ("-n", "--name"):
            cfgNewName = a
        elif o in ("-c", "--domname"):
            cfgDomName = a            
        elif o in ("-d", "--disc"):
            discFile = a
        elif o in ("-g", "--gain"):
            gainFile = a            
        elif o in ("-a", "--atwd"):
            atwdFile = a
        elif o in ("-b", "--baseline"):
            baselineFile = a
        elif o in ("-r", "--rate"):
            beaconRate = float(a)
        else:
            assert False, "unhandled option"

    if len(args) != 2:
        usage()
        sys.exit(2)

    cfgName = args[0]
    calDir = args[1]

    # Parse the exception files
    (hvExc, gainExc) = getGainExceptions(gainFile)
    (discExc, discExcPE) = getDiscExceptions(discFile)
    (chipExc, bias0Exc, bias1Exc) = getATWDExceptions(atwdFile)
    blExc = getBaselineExceptions(baselineFile)
    if hvExc:
        print "Applying",len(hvExc),"HV exceptions from",gainFile
    if gainExc:
        print "Applying",len(gainExc),"gain exceptions from",gainFile
    if discExc:
        print "Applying",len(discExc),"discriminator exceptions from",discFile
    if discExcPE:
        print "Applying",len(discExcPE),"discriminator PE exceptions from",discFile
    #if chipExc is not None:
    #    print "Applying",len(chipExc),"ATWD chip selection exceptions from",atwdFile
    if bias0Exc:
        print "Applying",len(bias0Exc),"ATWD0 bias exceptions from",atwdFile
    if bias1Exc:
        print "Applying",len(bias1Exc),"ATWD1 bias exceptions from",atwdFile
    if blExc:
        print "Applying",len(blExc),"ATWD baseline exceptions from",baselineFile

    # Parse the run configuration files
    try:
        rc = RunConfig(cfgName, oldFormat=False)
    except RunConfigException:
        print "WARNING: couldn't parse run configuration; trying old format..."
        rc = RunConfig(cfgName, oldFormat=True)
        
    # DOM positions, names, etc.
    nicks = nicknames()

    # Lists for saving results
    (hvDiffList, hvDiffListIT, gainDiffList, gainDiffListIT,
     speDiscList, speDiscListIT, speDiscPEList, atwdFreqList,
     atwdFreqMHzList) = ([], [], [], [], [], [], [], [], [])
    (hvDiffListScint, gainDiffListScint, speDiscListScint) = ([],[],[])	

    # Iterate over the configuration files
    for domCfg in rc.getDOMConfigs():
        for mbid in domCfg.getDOMs():

            # Read the calibration results for this DOM
            f = "domcal_%s.xml" % (mbid)
            cal = CalibrationResults(calDir, filter=f)

            # Try subdirectory (for unvetted results)
            if not cal.exists(mbid):
                f = "*/domcal_%s.xml" % (mbid)
                cal = CalibrationResults(calDir, filter=f)

            if not cal.exists(mbid):
                print "WARNING: no calibration results for", mbid, \
                      nicks.getDOMPosition(mbid), nicks.getDOMName(mbid)
                continue
            
            (string, dompos) = nicks.getDOMPosition(mbid)
            isIceTop = (string <= 86) and (dompos > 60) and (dompos < 65)
            if isIceTop:
                isLowGain = (dompos % 2 == 0)
            isScint = (string <= 86) and (dompos > 64)
            #-----------------------------------------------------
            # Determine new HV setting
            if mbid in gainExc:
                gain = gainExc[mbid]
            else:
                if isIceTop:
                    if isLowGain:
                        gain = GAIN_IT_LOW
                    else:
                        gain = GAIN_IT_HIGH
                elif isScint:
                    gain = GAIN_SCINT
                else:
                    gain = GAIN_INICE

            if mbid in hvExc:
                hvSetNew = hvExc[mbid]
                gain = cal.getGain(mbid, hvSetNew/2.)
            else:
                hvSetNew = cal.getHVSetting(mbid, gain)

            # Make sure HV is in range
            if not isScint and (hvSetNew > MAX_HV):
                print "WARNING: HV setting %d for %s too high!  Clamping!\n" % (hvSetNew, mbid)
                hvSetNew = MAX_HV
            elif isScint and (hvSetNew > MAX_HV_SCINT):
                print "WARNING: HV setting %d for scintillator %s too high!  Clamping!\n" \
                      % (hvSetNew, mbid)
                hvSetNew = MAX_HV_SCINT
                
            hvSetOld = int(domCfg.getDOMSetting(mbid, 'pmtHighVoltage'))

            hvDiff = (hvSetNew-hvSetOld)/2.
            gainOld = cal.getGain(mbid, hvSetOld/2.)
            if gain > 0:
                gainDiffPct = (gain-gainOld)/gain*100.
                if (math.fabs(gainDiffPct) > WARN_MAX_GAIN_DIFF_PCT):
                    print "WARNING: large gain change (%.1f%%)" % (gainDiffPct),\
                        mbid, "%02d-%02d" % (string, dompos), \
                        nicks.getDOMName(mbid), "%.1f %.1f" \
                        % (math.log10(cal.getGain(mbid, hvSetOld/2.)), math.log10(gain))
            else:
                gainDiffPct = 0.
                
            if isIceTop:
                hvDiffListIT.append(hvDiff)
                gainDiffListIT.append(gainDiffPct)
            elif isScint:
                hvDiffListScint.append(hvDiff)
                gainDiffListScint.append(gainDiffPct)
            else:
                hvDiffList.append(hvDiff)
                gainDiffList.append(gainDiffPct)                

            # If desired, ignore all IceTop high voltage changes
            # unless specifically overridden in the HV exceptions list
            if isIceTop and icetopDisable and not (mbid in hvExc):
                if abs(hvDiff) > WARN_HV_CHANGE:
                    print "WARNING: large HV change predicted, but disabled for IceTop (%.1f V)" % (hvDiff),\
                          mbid, "%02d-%02d" % (string, dompos), \
                          nicks.getDOMName(mbid), hvSetOld, hvSetNew
            else:
                if abs(hvDiff) > WARN_HV_CHANGE:
                    print "WARNING: large HV change (%.1f V)" % (hvDiff),\
                          mbid, "%02d-%02d" % (string, dompos), \
                          nicks.getDOMName(mbid), hvSetOld, hvSetNew

                if not dryrun:
                    domCfg.setDOMSetting(mbid, 'pmtHighVoltage', hvSetNew)
                
            #-----------------------------------------------------
            # Discriminator settings            
            if mbid in discExc:
                (speDiscNew, mpeDiscNew) = discExc[mbid]
            elif mbid in discExcPE:
                if isIceTop:
                    print "WARNING: SPE-only discriminator override applied to IceTop DOM!"
                speDiscNew = cal.getSPEDisc(mbid, discExcPE[mbid], gain)
                mpeDiscNew = speDiscNew+100
            else:
                if isIceTop:
                    if isHighGain:
                        (speDiscNew, mpeDiscNew) = DISC_IT_HIGH
                    else:
                        (speDiscNew, mpeDiscNew) = DISC_IT_LOW
                elif isScint:
                    speDiscNew = cal.getSPEDisc(mbid, DISC_SCINT_PE, gain)
                    mpeDiscNew = speDiscNew+100
                else:
                    # Note: use new gain
                    speDiscNew = cal.getSPEDisc(mbid, DISC_INICE_PE, gain)
                    mpeDiscNew = speDiscNew+100

            speDiscOld = int(domCfg.getDOMSetting(mbid, 'speTriggerDiscriminator'))

            speDiscDiff = speDiscNew-speDiscOld
            if isIceTop:
                speDiscListIT.append(speDiscDiff)
            elif isScint:
                speDiscListScint.append(speDiscDiff)
            else:    
	        speDiscList.append(speDiscDiff)
                oldDiscPE = cal.getSPEThresh(mbid, speDiscOld, gain)
                speDiscPEList.append(DISC_INICE_PE-oldDiscPE)

            # Do not check IceTop differences
            if not isIceTop and (abs(speDiscDiff) > WARN_SPE_DISC_CHANGE):
                print "WARNING: large SPE discriminator change (%d counts)" % (speDiscDiff),\
                      mbid, "%02d-%02d" % (string, dompos), \
                      nicks.getDOMName(mbid), speDiscOld, speDiscNew

            if not dryrun:
                domCfg.setDOMSetting(mbid, 'speTriggerDiscriminator', speDiscNew)
                domCfg.setDOMSetting(mbid, 'mpeTriggerDiscriminator', mpeDiscNew)                

            #-----------------------------------------------------
            # Determine new ATWD frequency (trigger bias) settings

            atwdFreqNew = [ None, None ]
            if mbid in bias0Exc:
                atwdFreqNew[0] = bias0Exc[mbid]
            else:
                atwdFreqNew[0] = cal.getATWDFreqSetting(mbid, 0, ATWD_FREQ_MHZ)
            if mbid in bias1Exc:
                atwdFreqNew[1] = bias1Exc[mbid]
            else:
                atwdFreqNew[1] = cal.getATWDFreqSetting(mbid, 1, ATWD_FREQ_MHZ)

            atwdFreqOld = [ int(domCfg.getDOMSetting(mbid, 'atwd0TriggerBias')),
                            int(domCfg.getDOMSetting(mbid, 'atwd1TriggerBias'))]
            atwdFreqMHzOld = (cal.getATWDFreq(mbid, 0, atwdFreqOld[0]),
                              cal.getATWDFreq(mbid, 1, atwdFreqOld[1]))

            if (abs(atwdFreqNew[0]-atwdFreqOld[0]) > WARN_ATWD_FREQ_CHANGE) or \
               (abs(atwdFreqNew[1]-atwdFreqOld[1]) > WARN_ATWD_FREQ_CHANGE):
                print "WARNING: large ATWD trigger bias change",\
                      mbid, "%02d-%02d" % (string, dompos), \
                      nicks.getDOMName(mbid), atwdFreqOld, atwdFreqNew

            if ((mbid not in bias0Exc) and (math.fabs(ATWD_FREQ_MHZ-atwdFreqMHzOld[0]) > WARN_ATWD_FREQ_CHANGE_MHZ)) or \
               ((mbid not in bias1Exc) and (math.fabs(ATWD_FREQ_MHZ-atwdFreqMHzOld[1]) > WARN_ATWD_FREQ_CHANGE_MHZ)):
                print "WARNING: large ATWD sampling speed change",\
                      mbid, "%02d-%02d" % (string, dompos), \
                      nicks.getDOMName(mbid), "(%.2f, %.2f MHz)" % (ATWD_FREQ_MHZ-atwdFreqMHzOld[0],ATWD_FREQ_MHZ-atwdFreqMHzOld[1])
                
            atwdFreqList.append(atwdFreqNew[0]-atwdFreqOld[0])
            atwdFreqList.append(atwdFreqNew[1]-atwdFreqOld[1])
            atwdFreqMHzList.append(ATWD_FREQ_MHZ-atwdFreqMHzOld[0])
            atwdFreqMHzList.append(ATWD_FREQ_MHZ-atwdFreqMHzOld[1])

            if not dryrun:
                domCfg.setDOMSetting(mbid, 'atwd0TriggerBias', atwdFreqNew[0])
                domCfg.setDOMSetting(mbid, 'atwd1TriggerBias', atwdFreqNew[1])

            #-----------------------------------------------------
            # FIX ME ADD CHIP SELECT 

            #-----------------------------------------------------
            # In special cases, recalculate or update the ATWD baselines
            if mbid in blExc:
                blOld = domCfg.getDOMBaselines(mbid)
                blNew = [[0,0,0],[0,0,0]]
                for chip in xrange(2):
                    for ch in xrange(3):
                        blNew[chip][ch] = cal.getBaseline(mbid, chip, ch)

                print "WARNING: updating ATWD baselines", \
                      mbid, "%02d-%02d" % (string, dompos), \
                      nicks.getDOMName(mbid), blOld, blNew

                if not dryrun:
                    domCfg.setDOMBaselines(mbid,blNew)

            #-----------------------------------------------------
            # If request, calculate the required beacon rate setting
            if (beaconRate is not None) and not (isIceTop and icetopDisable):
                rateSetting = getRateSetting(beaconRate)
                pulserMode = domCfg.getDOMSetting(mbid, 'pulserMode')
                if (pulserMode == 'beacon'):
                    if not dryrun:
                        domCfg.setDOMSetting(mbid, 'pulserRate', rateSetting)
                else:
                    print "WARNING: unexpected pulser mode",pulserMode,"for MBID",mbid
            
    # Save updated run configuration files
    if not dryrun:
        # Fix me deal with user specifying only some of these
        if (cfgNewName is not None) and (cfgVersion is not None) and (cfgDomName is not None):
            rc.write(newName=cfgNewName, newVersion=cfgVersion, newDomCfgName=cfgDomName)
        else:
            rc.write()

    # Save results for plotting
    if savePlotResults:
        print "Saving differences in calibration to file",OUTPUT_FILE
        f = open(OUTPUT_FILE, 'w')
        plotResults = {"hvDiffList":hvDiffList,
                       "hvDiffListIT":hvDiffListIT,
                       "gainDiffList":gainDiffList,
                       "gainDiffListIT":gainDiffListIT,
                       "speDiscList":speDiscList,
                       "speDiscPEList":speDiscPEList,
                       "speDiscListIT":speDiscListIT,
                       "hvDiffListScint":hvDiffListScint,
                       "gainDiffListScint":gainDiffListScint,
                       "speDiscListScint":speDiscListScint,
                       "atwdFreqList":atwdFreqList,
                       "atwdFreqMHzList":atwdFreqMHzList}
        json.dump(plotResults, f)
        f.close()

if __name__ == "__main__":
    main()
