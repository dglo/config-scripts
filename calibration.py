#!/usr/bin/env python
#
# calibration.py
#
# Support code for parsing DOMCal result XML files.
#

from __future__ import print_function
from builtins import str
from builtins import range
from builtins import object
import sys
import getopt
import os
import glob
import re
import math

from lxml import etree

DEFAULT_MPE_SETTING = 560
DEFAULT_SPE_SETTING = 560
DEFAULT_HV_SETTING = 0
DEFAULT_FREQ_SETTING = 800

DEFAULT_BASELINE = 128

DAC_BIAS_VOLTAGE = 7

#--------------------------------------------------------------------------------
E_CHARGE = 1.60217646e-19

class CalibrationResults(object):
    """Object collecting DOMCal XML calibration results"""

    # FIX ME better finding
    def __init__(self, directory, filter="*/domcal*.xml"):
        self.path = directory
        self.cal = {}
        
        # Look for all the calibration results in the directory
        calList = glob.glob(self.path+"/"+filter)
        if not calList:
            # print >> sys.stderr, "No calibration results found in",directory
            return
            
        for filename in calList:
            m = re.match(".*domcal_([0-9a-f]+)\.xml", filename)
            if not m:
                print("Didn't understand filename convention of ",filename,", skipping",
                      file=sys.stderr)
                continue
            mbid = m.group(1)

            try:
                parser = etree.XMLParser(remove_comments=False, remove_pis=False)
                tree = etree.parse(filename, parser=parser)                
            except:
                print("WARNING: error parsing file",filename,", skipping",
                      file=sys.stderr)
                continue
            
            if tree:
                self.cal[mbid] = tree.getroot()
            else:
                print("Couldn't parse calibration file",filename,"skipping",
                      file=sys.stderr)
                
    def __str__(self):
        str = ""
        if self.cal:
            for mbid in self.cal:
                str += mbid+"\n"
                root = self.cal[mbid]
                str += repr(root.tag)+repr(root.attrib)+"\n"
                for child in root:
                    str += "    "
                    str += repr(child.tag)+repr(child.attrib)+repr(child.text)+"\n"
                    for gchild in child:
                        str += "    "
                        str += "    "
                        str += repr(gchild.tag)+repr(gchild.attrib)+repr(gchild.text)+"\n"
        return str

    def exists(self, mbid):
        return (self.cal is not None) and (mbid in self.cal)
    
    def getGain(self, mbid, hv):
        if hv == 0:
            return 0.
        hvGainCal = self.getFitCal(mbid, 'hvGainCal')
        if hvGainCal is None:
            print("Missing HV/gain calibration for MBID",mbid, file=sys.stderr)
            return -1
        (b, m) = hvGainCal
        return math.pow(10., m*math.log10(hv) + b)

    def getBaseline(self, mbid, atwd, ch):

        vBias = self.getDAC(mbid, DAC_BIAS_VOLTAGE)*5./4096.        
        baseline = 0.        
        for bin in range(128):
            filters = [['id', str(atwd)], ['channel', str(ch)], ['bin', str(bin)]]
            atwdCal = self.getFitCal(mbid, 'atwd', filters=filters)
            if atwdCal is None:
                print("Missing ATWD calibration for MBID",mbid, file=sys.stderr)
                return DEFAULT_BASELINE
            (b, m) = atwdCal            
            baseline += (vBias-b)/m
        return int(baseline/128.0 + 0.5)


    def getHVSetting(self, mbid, gain):
        if (gain == 0.):
            return 0
        hvGainCal = self.getFitCal(mbid, 'hvGainCal')
        if hvGainCal is None:
            print("Missing HV/gain calibration for MBID",mbid, file=sys.stderr)
            return DEFAULT_HV_SETTING
        (b, m) = hvGainCal
        hv = math.pow(10., (math.log10(gain) - b) / m)
        return int(hv*2 + 0.5)
    
    def getSPEDisc(self, mbid, speFrac, gain):        
        if gain == 0:
            return DEFAULT_SPE_SETTING
        # Non-HV discriminator calibration is fallback
        speDiscCal = self.getFitCal(mbid, 'discriminator', filters=[['id', 'spe']])
        if speDiscCal is None:
            print("No valid discriminator calibration found!", file=sys.stderr)
            return DEFAULT_SPE_SETTING            
        else:
            (b, m) = speDiscCal
        # Use PMT discriminator calibration if it exists and is OK
        pmtDiscCal = self.getFitCal(mbid, 'pmtDiscCal')
        if pmtDiscCal is None:
            print("Missing PMT discriminator setting for MBID",mbid, file=sys.stderr)
            print("WARNING: falling back to pulser discriminator calibration", file=sys.stderr)
        else:
            (b1, m1) = pmtDiscCal
            # DOMCal 7.6.0 had a bug that resulted in garbage here if the HV was off
            if math.isnan(b1) or math.isnan(m1) or (b1 > 0) or (m1 < 0):
                print("Bad PMT discriminator setting for MBID",mbid, file=sys.stderr)
                print("WARNING: falling back to pulser discriminator calibration", file=sys.stderr)
            else:
                (b, m) = (b1, m1)
        return int(((gain * speFrac * E_CHARGE * 1e12 - b) / m) + 0.5)

    def getSPEThresh(self, mbid, speDisc, gain):
        '''Return the threshold in PE for a given discriminator setting and gain'''
        if gain == 0:
            return 0
        pmtDiscCal = self.getFitCal(mbid, 'pmtDiscCal')
        if pmtDiscCal is None:
            print("Missing PMT discriminator setting for MBID",mbid, file=sys.stderr)
            return DEFAULT_SPE_SETTING
        (b, m) = pmtDiscCal
        # DOMCal 7.6.0 had a bug that resulted in garbage here if the HV was off
        if math.isnan(b) or math.isnan(m) or (b > 0) or (m < 0):            
            print("Bad PMT discriminator setting for MBID",mbid, file=sys.stderr)
            return DEFAULT_SPE_SETTING
        return (m * speDisc + b) / (gain * E_CHARGE * 1e12)
    
    def getATWDFreqSetting(self, mbid, atwd, freq):
        freqCal = self.getFitCal(mbid, 'atwdfreq', [['atwd', str(atwd)]])
        if freqCal is None:
            print("Bad ATWD frequency calibration for MBID",mbid,"chip",atwd, file=sys.stderr)
            return DEFAULT_FREQ_SETTING
        (c0, c1, c2) = freqCal
        try:
            bias = int((-c1 + math.sqrt(c1*c1 - 4*(c0-freq)*c2))/(2*c2) + 0.5)
        except ValueError:
            print("Bad ATWD frequency calibration for MBID",mbid,"chip",atwd, file=sys.stderr)
            return DEFAULT_FREQ_SETTING
        return bias

    def getATWDFreq(self, mbid, atwd, bias):
        freqCal = self.getFitCal(mbid, 'atwdfreq', [['atwd', str(atwd)]])
        if freqCal is None:
            print("Bad ATWD frequency calibration for MBID",mbid,"chip",atwd, file=sys.stderr)
            return None
        (c0, c1, c2) = freqCal
        try:
            freq_mhz = c2*bias*bias + c1*bias + c0
        except ValueError:
            print("Bad ATWD frequency calibration for MBID",mbid,"chip",atwd, file=sys.stderr)
            return None
        return freq_mhz

    # FIX ME this is awful; clean it up
    def getFitCal(self, mbid, name, filters=None):
        fit = None
        fitParams = None
        passFilt = False
        if mbid not in self.cal:
            return None
        root = self.cal[mbid]

        # Look for the named calibration results and apply the filters
        # to select certain chips, bins, etc.
        results = root.findall(name)
        if results is not None:
            for r in results:
                # Check filters
                passFilt = True
                if filters is not None:
                    passFilt = True
                    for filt in filters:
                        passFilt = passFilt and (r.get(filt[0]) == filt[1])
                if passFilt:
                    fit = r.find('fit')
                    
        # Pull out the linear or quadratic fit components
        if fit is not None:
            if fit.get('model') == "quadratic":
                fitParams = [None, None, None]
                for p in fit.findall('param'):
                    if p.get('name') == "c0":
                        fitParams[0] = float(p.text)
                    elif p.get('name') == "c1":
                        fitParams[1] = float(p.text)
                    elif p.get('name') == "c2":
                        fitParams[2] = float(p.text)                                
            elif fit.get('model') == "linear":
                fitParams = [None, None]
                for p in fit.findall('param'):
                    if p.get('name') == "slope":
                        fitParams[1] = float(p.text)
                    elif p.get('name') == "intercept":
                        fitParams[0] = float(p.text)            
            else:
                print("Error parsing calibration results: unknown fit model", file=sys.stderr)
        return fitParams            


    def getDAC(self, mbid, dac):
        dacs = self.cal[mbid].findall('dac')
        for d in dacs:
            if d.get('channel') == str(dac):
                return int(d.text)
        return None

    def getDeltaT(self, mbid, isATWD, chip):
        delta_t = None
        if isATWD:
            tag = 'atwd_delta_t'
        else:
            tag = 'fadc_delta_t'
        deltas = self.cal[mbid].findall(tag)
        for t in deltas:
            d = t.find('delta_t')
            if d is None:
                print("Error parsing calibration results: can't find delta_t", file=sys.stderr)
                return None
            if (isATWD and t.attrib.get('id') == str(chip)) or not isATWD:
                delta_t = float(d.text)
        return delta_t

# FIX ME turn into tests
if __name__ == "__main__":
    TESTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ic86/test")
    cal = CalibrationResults(TESTDIR, filter="domcal*.xml")

    # Test with HV
    try:
        testid = 'eaf3fe2cc0e2'
        assert cal.exists(testid)
        print("Calibration settings for DOM", testid)

        loggain = math.log10(cal.getGain(testid, 1300))
        assert(abs(loggain-6.992) < 0.001)
        print("log(gain) at 1300V: ", loggain)
        
        hv = cal.getHVSetting(testid, 1e7)
        assert(hv == 2606)
        print("HV setting for 1e7 gain:",hv)
        
        disc = cal.getSPEDisc(testid, 0.25, 1e7)
        assert(disc == 565)
        print("Disc. setting of 0.25 PE at 1e7 gain:", disc)
        
        thresh = cal.getSPEThresh(testid, 560, 1e7)
        assert(abs(thresh-0.197) < 0.001)
        print("Threshold at DAC setting of 560:", thresh)
        
        (bias0, bias1) = (cal.getATWDFreqSetting(testid, 0, 300.), cal.getATWDFreqSetting(testid, 1, 300.))
        assert(bias0 == 827)
        assert(bias1 == 820)
        print("Trigger bias setting at 300 MHz:", bias0, bias1)
        
        (bl0_0, bl0_1, bl0_2) = cal.getBaseline(testid, 0, 0), \
                                cal.getBaseline(testid, 0, 1), \
                                cal.getBaseline(testid, 0, 2)
        assert(bl0_0 == 128)
        assert(bl0_1 == 130)
        assert(bl0_2 == 135)
        print("Average baselines for chip 0:", (bl0_0, bl0_1, bl0_2))
        
        (bl1_0, bl1_1, bl1_2) = cal.getBaseline(testid, 1, 0), \
                                cal.getBaseline(testid, 1, 1), \
                                cal.getBaseline(testid, 1, 2)
        assert(bl1_0 == 130)
        assert(bl1_1 == 135)
        assert(bl1_2 == 139)
        print("Average baselines for chip 1:", (bl1_0, bl1_1, bl1_2))
        
        dt0 = cal.getDeltaT(testid, True, 0)
        assert(dt0 == 0.0)
        print("Delta T for chip 0:", dt0)
        
        dt1 = cal.getDeltaT(testid, True, 1)
        assert(abs(dt1-(-0.421)) < 0.001)
        print("Delta T for chip 1:", dt1)
        
        dt_fadc = cal.getDeltaT(testid, False, 0)
        assert(abs(dt_fadc-(-112.67)) < 0.01)
        print("Delta T for FADC:", dt_fadc)
        
        # Test without HV
        testid = '9ed5742a784d'
        assert(cal.exists(testid))
        print("Calibration settings for DOM",testid)
        
        (bias0, bias1) = (cal.getATWDFreqSetting(testid, 0, 300.), cal.getATWDFreqSetting(testid, 1, 300.))
        assert(bias0 == 902)
        assert(bias1 == 914)
        print("Trigger bias setting at 300 MHz:", bias0, bias1)
        
        (bl0_0, bl0_1, bl0_2) = cal.getBaseline(testid, 0, 0), \
                                cal.getBaseline(testid, 0, 1), \
                                cal.getBaseline(testid, 0, 2)
        assert(bl0_0 == 125)
        assert(bl0_1 == 130)
        assert(bl0_2 == 133)
        print("Average baselines for chip 0:", (bl0_0, bl0_1, bl0_2))
        
        # Will use non-PMT disc cal
        disc = cal.getSPEDisc(testid, 0.25, 1e7)
        assert(disc == 569)
        print("Discriminator setting for 0.25PE:", disc)
        print("===PASS===")
    except AssertionError:
        print("===FAIL===")
        
