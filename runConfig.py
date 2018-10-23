#!/usr/bin/env python
#
# runConfig.py
#
# Support code for parsing and modifying IceCube pDAQ run configurations,
# including changes to the DOM and trigger configurations.
#

import sys
import os

from lxml import etree

#-------
# exception raised not finding any
# domconfigs in a runconfig
class RunConfigException(Exception):
    pass

#---------------------------------------------

class XMLConfig:
    """XML element tree for configuration files"""
    def __init__(self, filename):
        self.path = os.path.dirname(filename)
        if not self.path:
            self.path = "."        
        self.filename = os.path.basename(filename)
        self.modified = False

        parser = etree.XMLParser(remove_comments=False, remove_pis=False)
        self.tree = etree.parse(filename, parser=parser)
        if self.tree:
            self.root = self.tree.getroot()
        else:
            self.root = None
            print >> sys.stderr, "Couldn't parse configuration file", filename
            sys.exit(-1)

    def __str__(self):
        str = ""
        if self.root is not None:
            str += repr(self.root.tag)+repr(self.root.attrib)+"\n"
            for child in self.root:
                str += repr(child.tag)+repr(child.attrib)+repr(child.text)+"\n"
        return str

    def write(self, filename=None):
        if self.tree is not None:
            if filename is None:
                filename = self.filename
            self.tree.write(self.path+"/"+filename, xml_declaration=True)
            
#--------------------------------------------------

class DOMConfig(XMLConfig):
    """XML element tree for DOM configuration"""

    BASELINEPARENT = "pedestalSettings"
    BASELINETAG = "averagePedestal"

    ATWDDICT = {'A':0, 'B':1}
    
    def __init__(self, filename):
        XMLConfig.__init__(self, filename)

    # FIX ME this must be really slow!
    def getDOMSetting(self, mbid, setting):
        for dom in self.root.findall('domConfig'):
            if dom.get('mbid') == mbid:
                t = dom.find(setting).text
                if t is not None:
                    t = t.strip()
                return t
        return None

    def setDOMSetting(self, mbid, setting, value):
        for dom in self.root.findall('domConfig'):
            if dom.get('mbid') == mbid:
                self.modified = True                
                dom.find(setting).text = str(value)

    def getDOMBaselines(self, mbid):
        blArr = [[0, 0, 0], [0, 0, 0]]
        for dom in self.root.findall('domConfig'):
            if dom.get('mbid') == mbid:
                for child in dom.find(DOMConfig.BASELINEPARENT):
                    if child.tag == DOMConfig.BASELINETAG:
                        atwd = DOMConfig.ATWDDICT[child.get('atwd')]
                        ch = int(child.get('ch'))
                        bl = int(child.text)
                        blArr[atwd][ch] = bl
        return blArr


    def setDOMBaselines(self, mbid, blArr):        
        for dom in self.root.findall('domConfig'):
            if dom.get('mbid') == mbid:
                for child in dom.find(DOMConfig.BASELINEPARENT):
                    if child.tag == DOMConfig.BASELINETAG:
                        atwd = DOMConfig.ATWDDICT[child.get('atwd')]
                        ch = int(child.get('ch'))
                        child.text = str(blArr[atwd][ch])
                        self.modified = True                        
                return                        
    
    def getDOMs(self):
        domList = []
        for dom in self.root.findall('domConfig'):
            domList.append(dom.get('mbid'))
        return domList

    def removeDOM(self, mbid):
        for dom in self.root.findall('domConfig'):
            if dom.get('mbid') == mbid:
                self.root.remove(dom)
                self.modified = True                
                return True
        return False
    
#-----------------------------------------------------
    
class RunConfig(XMLConfig):
    """Tree of XML element trees for DAQ top-level 
    run and child configurations."""
    
    DOMPATH = "domconfigs"

    # Old format
    DOMTAG  = "domConfigList"
    # New format    
    STRINGHUB = "stringHub"
    DOMATTRIB = "domConfig"
    
    TRIGPATH = "trigger"
    TRIGTAG = "triggerConfig"
    
    def __init__(self, filename, oldFormat=False):
        XMLConfig.__init__(self, filename)
        self.trigroot = None
        self.domCfgs = {}
        self.oldFormat = oldFormat
        
        # Recursively parse trigger and DOM configs
        for child in self.root:

            trig = (child.tag == RunConfig.TRIGTAG)
            if self.oldFormat:
                dom = (child.tag == RunConfig.DOMTAG)
            else:
                dom = (child.tag == RunConfig.STRINGHUB)

            if not trig and not dom:
                continue
                    
            filename = None
            if trig:
                filename = os.path.join(self.path,
                                        RunConfig.TRIGPATH,
                                        "%s.xml" % child.text)
            elif dom:
                if self.oldFormat:
                    filename = os.path.join(self.path,
                                            RunConfig.DOMPATH,
                                            child.text+".xml")            
                    hub = child.get('hub')
                    self.domCfgs[hub] = DOMConfig(filename)
                else:
                    dom_fname = child.get(RunConfig.DOMATTRIB)
                    filename = os.path.join(self.path,
                                            RunConfig.DOMPATH,
                                            "%s.xml" % dom_fname)
                
                    hub = child.get('hubId')
                    self.domCfgs[hub] = DOMConfig(filename)

            if trig:
                self.trigroot = XMLConfig(filename)

        if len(self.domCfgs)==0:
            # This class as is does not understand OLD config
            # files, check for this problem by noting if there
            # are no domCfgs
            raise RunConfigException("No dom configs found in %s (old format?)" % 
                                     self.filename)

    def write(self, newName=None, newVersion=None, newDomCfgName=None):

        if (self.root is None) or (self.tree is None):
            return        
        # Save referenced files
        for child in self.root:
            if ((self.oldFormat and (child.tag == RunConfig.DOMTAG)) or
                (not self.oldFormat and (child.tag == RunConfig.STRINGHUB))):
                if self.oldFormat:
                    hub = child.get('hub')
                else:
                    hub = child.get('hubId')
                    
                if (newVersion is not None) and (newDomCfgName is not None):
                    # IceTop hubs
                    h = int(hub)
                    if (h >= 200) and (h < 220):                    
                        hubName = "%02dt" % (h-200)
                    else:
                        hubName = "%02di" % (h)
                        
                    newDomName = "sps-%s-%s-%d" % (hubName,
                                                   newDomCfgName,
                                                   newVersion)
                    if self.domCfgs[hub].modified:
                        if self.oldFormat:
                            child.text = newDomName
                        else:
                            child.set(RunConfig.DOMATTRIB, newDomName)
                        self.modified = True                        
                        self.domCfgs[hub].write(newDomName+".xml")
                else:
                    self.domCfgs[hub].write()
                                
        if (newVersion is not None) and (newName is not None):
            filename = "%s-V%d.xml" % (newName, newVersion)
        else:
            filename = self.filename
        self.tree.write(self.path+"/"+filename, xml_declaration=True)
        
    def getHubs(self):
        return self.domCfgs.keys()

    def removeDOM(self, mbid):
        for h in self.domCfgs:
            removed = self.domCfgs[h].removeDOM(mbid)
            if removed:
                return True
        return False
    
    def getDOMConfigs(self):
        return self.domCfgs.values()

if __name__ == "__main__":
    rc = RunConfig(sys.argv[1], oldFormat=False)

    testhub = '1'
    testid = 'e9fed8c717dd'
    testqty = 'pmtHighVoltage'
    
    hvSet = int(rc.domCfgs[testhub].getDOMSetting(testid, testqty))
    rc.domCfgs[testhub].setDOMSetting(testid, testqty, str(hvSet+111))
    hvSetNew = int(rc.domCfgs[testhub].getDOMSetting(testid, testqty))
    print testid, ": changed", testqty, "from", hvSet, "to", hvSetNew

    blArr = rc.domCfgs[testhub].getDOMBaselines(testid)
    print testid, "baselines:", blArr
    for atwd in range(2):
        for ch in range(3):
            blArr[atwd][ch] = blArr[atwd][ch]+1
    rc.domCfgs[testhub].setDOMBaselines(testid, blArr)
    print testid, "baselines updated to:", blArr
    
    rc.write(newName="sps-test-output",
             newVersion=333,
             newDomCfgName="test-output")

