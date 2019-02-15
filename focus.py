﻿# -*- coding: utf-8 -*-
"""
Created on Wed Oct  1 13:41:48 2018

@authors: Luciano Masullo
"""

import numpy as np
import time
import scipy.ndimage as ndi
import matplotlib.pyplot as plt
from scipy import optimize as opt

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from pyqtgraph.dockarea import Dock, DockArea
import pyqtgraph.ptime as ptime

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot

import sys
sys.path.append('C:\Program Files\Thorlabs\Scientific Imaging\ThorCam')
# install from https://instrumental-lib.readthedocs.io/en/stable/install.html
from instrumental.drivers.cameras import uc480
import tools.viewbox_tools as viewbox_tools
import tools.tools as tools
import tools.colormaps as cmaps
import tools.pi as pi
import scan
import drivers.ADwin as ADwin



def actuatorParameters(adwin, z_f, n_pixels_z=50, pixeltime=1000):

    z_f = tools.convert(z_f, 'XtoU')

    adwin.Set_Par(23, n_pixels_z)
    
    adwin.Set_FPar(25, z_f)

    adwin.Set_FPar(26, tools.timeToADwin(pixeltime))

def zMoveTo(adwin, z_f):

    actuatorParameters(adwin, z_f)
    adwin.Start_Process(3)


class Frontend(QtGui.QFrame):
    
    changedROI = pyqtSignal(np.ndarray)  # oass new roi size
    closeSignal = pyqtSignal()
    lockFocusSignal = pyqtSignal(bool)
    changedPIparam = pyqtSignal(np.ndarray)
    
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        
        self.roi = None
        self.cropped = False

        self.setUpGUI()

    def ROImethod(self):
        
        if self.cropped is True:  # code to go back to the (1280 x 1024) ROI
            
            x0 = 0
            y0 = 0
            x1 = 1280 
            y1 = 1024 
            
            value = np.array([x0, y0, x1, y1])
            self.changedROI.emit(value)
            self.cropped = False
        
        ROIpen = pg.mkPen(color='y')

        if self.roi is None:

            ROIpos = (0, 0)
            self.roi = viewbox_tools.ROI(300, self.vb, ROIpos,
                                         handlePos=(1, 0),
                                         handleCenter=(0, 1),
                                         scaleSnap=True,
                                         translateSnap=True,
                                         pen=ROIpen)

        else:

            self.vb.removeItem(self.roi)
            self.roi.hide()

            ROIpos = (0, 0)
            self.roi = viewbox_tools.ROI(300, self.vb, ROIpos,
                                         handlePos=(1, 0),
                                         handleCenter=(0, 1),
                                         scaleSnap=True,
                                         translateSnap=True,
                                         pen=ROIpen)
            
    def selectROI(self):
        
        self.cropped = True
        self.getStats = True
    
        ROIpos = np.array(self.roi.pos())
               
        roisize = np.array(self.roi.size())
        
    
        y0 = int(ROIpos[0])
        x0 = int(ROIpos[1])
        y1 = int(ROIpos[0] + roisize[0])
        x1 = int(ROIpos[1] + roisize[1])
        
        value = np.array([x0, y0, x1, y1])
        
        self.changedROI.emit(value)
    
        self.vb.removeItem(self.roi)
        self.roi.hide()
        self.roi = None
        
    def toggleFocus(self):
        
        params = np.array([self.kpEdit.text(), self.kiEdit.text()], 
                           dtype=np.float)
        self.changedPIparam.emit(params)
        
        if self.lockButton.isChecked():
            
            self.lockFocusSignal.emit(True)

#            self.setpointLine = self.focusGraph.zPlot.addLine(y=self.setPoint, pen='r')
            
        else:
            
            self.lockFocusSignal.emit(False)
            
        
    @pyqtSlot(np.ndarray)
    def get_image(self, img):
        
        #  The croppingis done because otherwise the displayed image will be
        #  300 x 1024. It doesn't affect the performance of the system
        
        if self.cropped is False: 
            
            self.img.setImage(img, autoLevels=False)
        
        else:

            croppedimg = img[0:300, 0:300]
            self.img.setImage(croppedimg)
            
    @pyqtSlot(np.ndarray, np.ndarray)
    def get_data(self, time, position):
        self.focusCurve.setData(time, position)
            
    def make_connection(self, backend):
            
        backend.changedImage.connect(self.get_image)
        backend.changedData.connect(self.get_data)
        
    def setUpGUI(self):
        
         # Focus lock widget
         
        self.setFrameStyle(QtGui.QFrame.Panel | QtGui.QFrame.Raised)
        self.setMinimumSize(2, 200)
        
        self.kpEdit = QtGui.QLineEdit('-0.3')
        self.kpEdit.setFixedWidth(60)

        self.kpLabel = QtGui.QLabel('kp')
        self.kiEdit = QtGui.QLineEdit('0.00001')
        self.kiEdit.setFixedWidth(60)
        self.kiLabel = QtGui.QLabel('ki')
        self.lockButton = QtGui.QPushButton('Lock focus')
        self.lockButton.setCheckable(True)
        self.lockButton.setSizePolicy(QtGui.QSizePolicy.Preferred,
                                      QtGui.QSizePolicy.Expanding)
        moveLabel = QtGui.QLabel('Move [nm]')
        moveLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.moveEdit = QtGui.QLineEdit('0')
        self.moveEdit.setFixedWidth(60)
        self.ROIbutton = QtGui.QPushButton('ROI')
        self.selectROIbutton = QtGui.QPushButton('select ROI')
        self.calibrationButton = QtGui.QPushButton('Calibrate')
        
#        self.kiEdit.textChanged.connect(self.fworker.unlockFocus)
#        self.kpEdit.textChanged.connect(self.fworker.unlockFocus)
        self.lockButton.clicked.connect(self.toggleFocus)
        self.ROIbutton.clicked.connect(self.ROImethod)
        self.selectROIbutton.clicked.connect(self.selectROI)
#        self.calibrationButton.clicked.connect(self.fworker.calibrate)

        self.focusPropertiesDisplay = QtGui.QLabel(' st_dev = 0  max_dev = 0')

        # focus camera display
        
        self.camDisplay = pg.GraphicsLayoutWidget()
        self.vb = self.camDisplay.addViewBox(row=0, col=0)

        self.vb.setMouseMode(pg.ViewBox.RectMode)
        self.img = pg.ImageItem()
        self.img.translate(-0.5, -0.5)
        self.vb.addItem(self.img)
        self.vb.setAspectLocked(True)

        self.hist = pg.HistogramLUTItem(image=self.img)   # set up histogram for the liveview image
        lut = viewbox_tools.generatePgColormap(cmaps.inferno)
        self.hist.gradient.setColorMap(lut)
        self.hist.vb.setLimits(yMin=0, yMax=10000)

        for tick in self.hist.gradient.ticks:
            tick.hide()
            
        self.camDisplay.addItem(self.hist, row=0, col=1)
        
        # focus lock graph
        
        self.focusGraph = pg.GraphicsWindow()
        self.focusGraph.setAntialiasing(True)
        
        self.focusGraph.statistics = pg.LabelItem(justify='right')
        self.focusGraph.addItem(self.focusGraph.statistics, row=0, col=0)
        self.focusGraph.statistics.setText('---')
        
        self.focusGraph.zPlot = self.focusGraph.addPlot(row=0, col=0)
        self.focusGraph.zPlot.setLabels(bottom=('Time', 's'),
                                        left=('CM x position', 'px'))
        self.focusGraph.zPlot.showGrid(x=True, y=True)
        self.focusCurve = self.focusGraph.zPlot.plot(pen='y')

        # GUI layout
        
        grid = QtGui.QGridLayout()
        self.setLayout(grid)
        
        # parameters widget
        
        self.paramWidget = QtGui.QFrame()
        self.paramWidget.setFrameStyle(QtGui.QFrame.Panel |
                                       QtGui.QFrame.Raised)
        
        self.paramWidget.setFixedHeight(150)
        self.paramWidget.setFixedWidth(200)
        
        subgrid = QtGui.QGridLayout()
        self.paramWidget.setLayout(subgrid)
        
        subgrid.addWidget(self.calibrationButton, 0, 0, 1, 4)
        subgrid.addWidget(self.kpLabel, 1, 2)
        subgrid.addWidget(self.kpEdit, 1, 3)
        subgrid.addWidget(self.kiLabel, 2, 2)
        subgrid.addWidget(self.kiEdit, 2, 3)
        subgrid.addWidget(self.lockButton, 3, 0, 1, 4)
        subgrid.addWidget(self.ROIbutton, 1, 0)
        subgrid.addWidget(self.selectROIbutton, 2, 0)
        

        
        grid.addWidget(self.paramWidget, 0, 0)
        grid.addWidget(self.focusGraph, 0, 1)
        grid.addWidget(self.camDisplay, 0, 2)

        
    def closeEvent(self, *args, **kwargs):
        
        self.closeSignal.emit()
        
        super().closeEvent(*args, **kwargs)
        
        

class Backend(QtCore.QObject):
    
    changedImage = pyqtSignal(np.ndarray)
    changedData = pyqtSignal(np.ndarray, np.ndarray)
    changedSetPoint = pyqtSignal(np.ndarray)

    def __init__(self, camera, actuator, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.camera = camera
        self.actuator = actuator
        self.locked = False
        self.cropped = False
        self.standAlone = False
    
        self.npoints = 400
        
        # checks image size
        
        rawimage = self.camera.latest_frame()
        image = np.sum(rawimage, axis=2)
        
        self.sensorSize = np.array(image.shape)
        self.focusSignal = 0
        
        # set focus update rate
        
        self.scansPerS = 20
        self.camera.start_live_video(framerate='20 Hz')

        self.focusTime = 1000 / self.scansPerS
        self.focusTimer = QtCore.QTimer()
        self.focusTimer.timeout.connect(self.update)
        self.focusTimer.start(self.focusTime)
        
        self.currentZ = tools.convert(self.actuator.Get_FPar(52), 'UtoX')
        self.currentX = tools.convert(self.actuator.Get_FPar(50), 'UtoX')
        self.currentY = tools.convert(self.actuator.Get_FPar(51), 'UtoX')
        
        self.reset()
        
    def setupPI(self):
        
        self.setPoint = self.focusSignal
        self.PI = pi.PI(self.setPoint, 0.001, self.kp, self.ki)

        self.initialZ = self.currentZ
        
    def updatePI(self):
        
        # TO DO: fix this function

        self.distance = self.currentZ - self.initialZ
        
        cm = self.focusSignal
        out = self.PI.update(cm)

#        self.lockN += 1
#        self.lockMean += (cm - self.lockMean)/(self.lockN + 1)
#        self.graph.setLine.setValue(self.lockMean)

        # Safety unlocking
        
        if abs(self.distance) > 1  or abs(out) > 3 or self.currentZ < 0:  # in µm
        
            self.lockFocus(False)
            
        else:
            
            self.currentZ = self.currentZ + out
            print('moved to', self.currentZ, 'µm')
            
        zMoveTo(self.actuator, self.currentZ)
            

    def updateStats(self):
        
        # TO DO: fix this function

        signal = self.focusSignal

        if self.n == 1:
            self.mean = signal
            self.mean2 = self.mean**2
        else:
            self.mean += (signal - self.mean)/self.n
            self.mean2 += (signal**2 - self.mean2)/self.n

        # Stats
        self.std = np.sqrt(self.mean2 - self.mean**2)
        self.max_dev = np.max([self.max_dev,
                              self.focusSignal - self.setPoint])
        statData = 'std = {}    max_dev = {}'.format(np.round(self.std, 3),
                                                     np.round(self.max_dev, 3))
        self.gui.focusGraph.statistics.setText(statData)

        self.n += 1
        
    def update(self, delay=0.000):

        time.sleep(delay)
        
        raw_image = self.camera.latest_frame()
        
#        r = raw_image[:, :, 0]
#        g = raw_image[:, :, 1]
#        b = raw_image[:, :, 2]
        
        image = np.sum(raw_image, axis=2)
        
        self.changedImage.emit(image)
            
        # get mass center
            
        self.massCenter = np.array(ndi.measurements.center_of_mass(image))
        self.focusSignal = self.massCenter[0]
    
        # update of the data displayed in the graph

        if self.ptr < self.npoints:
            self.data[self.ptr] = self.focusSignal
            self.time[self.ptr] = ptime.time() - self.startTime
            
            self.changedData.emit(self.time[1:self.ptr + 1],
                                  self.data[1:self.ptr + 1])

        else:
            self.data[:-1] = self.data[1:]
            self.data[-1] = self.focusSignal
            self.time[:-1] = self.time[1:]
            self.time[-1] = ptime.time() - self.startTime

            self.changedData.emit(self.time, self.data)

        self.ptr += 1
        
        # update PI
        
        if self.locked:
            self.updatePI()
#            self.updateStats()
            

        
    def lockFocus(self, lockbool):
        
        if lockbool:
        
            self.reset()
            self.setupPI()
            self.update()
            self.locked = True
        
        else:
        
            if self.locked is True:
                self.locked = False

            
    def calibrate(self):
        
        self.focusTimer.stop()
        time.sleep(0.100)
        
        nsteps = 40
        xmin = 9.5  # in µm
        xmax = 10.5   # in µm
        xrange = xmax - xmin  
        
        calibData = np.zeros(40)
        xData = np.arange(xmin, xmax, xrange/nsteps)
        
        zMoveTo(self.actuator, xmin)
        
        time.sleep(0.100)
        
        for i in range(nsteps):
            
            zMoveTo(self.actuator, xmin + (i * 1/nsteps) * xrange)
            self.update()
            calibData[i] = self.focusSignal
            
        plt.plot(xData, calibData, 'o')
            
        time.sleep(0.200)
        
        self.focusTimer.start(self.focusTime)
    
            
    def reset(self):
        
        self.data = np.zeros(self.npoints)
        self.time = np.zeros(self.npoints)
        self.ptr = 0
        self.startTime = ptime.time()

        self.max_dev = 0
        self.mean = self.focusSignal
        self.std = 0
        self.n = 1
        
    @pyqtSlot(bool)
    def get_lock(self, lockbool):
        self.lockFocus(lockbool)
            
    @pyqtSlot(np.ndarray)
    def get_newROI(self, val):

        self.cropped = True
        self.camera._set_AOI(*val)
        print('focus lock ROI changed to', self.camera._get_AOI())
        
    @pyqtSlot(np.ndarray)
    def get_PIparam(self, param):
        self.kp, self.ki = param
        
    def make_connection(self, frontend):
            
        frontend.changedROI.connect(self.get_newROI)
        frontend.closeSignal.connect(self.stop)
        frontend.lockFocusSignal.connect(self.lockFocus)
        frontend.changedPIparam.connect(self.get_PIparam)
        frontend.calibrationButton.clicked.connect(self.calibrate)
        
    def stop(self):
        
        self.focusTimer.stop()
        self.camera.close()
        
        if self.standAlone is True:
            zMoveTo(self.actuator, 0)
            
        print('Focus lock stopped')
            
    

if __name__ == '__main__':
    
    app = QtGui.QApplication([])
    
    print('Focus lock module running in stand-alone mode')

    # initialize devices
    
    cam = uc480.UC480_Camera()
    
    DEVICENUMBER = 0x1
    adw = ADwin.ADwin(DEVICENUMBER, 1)
    scan.setupDevice(adw)
    
    # initialize fpar_52 (z) ADwin position parameters
        
    pos_zero = tools.convert(0, 'XtoU')
    adw.Set_FPar(52, pos_zero)  
    zMoveTo(adw, 10)

    gui = Frontend()   
    worker = Backend(cam, adw)
    
    worker.make_connection(gui)
    gui.make_connection(worker)

    gui.setWindowTitle('Focus lock')
    gui.resize(1500, 500)

    gui.show()
    app.exec_()
        