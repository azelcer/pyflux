# -*- coding: utf-8 -*-
"""
Created on Tue Jan 15 11:59:13 2019

@author: Luciano A. Masullo
"""

import numpy as np
import time
import ctypes as ct
from datetime import date

import matplotlib.pyplot as plt
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from pyqtgraph.dockarea import Dock, DockArea
import pyqtgraph.ptime as ptime
from scipy import optimize as opt
from PIL import Image

import tools.viewbox_tools as viewbox_tools
import tools.colormaps as cmaps
import tools.PSF as PSF
import tools.tools as tools
import scan

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
import qdarkstyle

from lantz.drivers.andor import ccd 
import drivers.ADwin as ADwin


class Frontend(QtGui.QFrame):
    
    liveviewSignal = pyqtSignal(bool)
    roiInfoSignal = pyqtSignal(int, np.ndarray)
    closeSignal = pyqtSignal()
    saveDataSignal = pyqtSignal(bool)
    
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        
        self.setup_gui()
        
        # initial ROI parameters        
        
        self.NofPixels = 200
        self.roi = None
        self.ROInumber = 0
        self.roilist = []

    def craete_roi(self):
        
        ROIpen = pg.mkPen(color='r')

        ROIpos = (0.5 * self.NofPixels - 64, 0.5 * self.NofPixels - 64)
        self.roi = viewbox_tools.ROI2(self.NofPixels/2, self.vb, ROIpos,
                                     handlePos=(1, 0),
                                     handleCenter=(0, 1),
                                     scaleSnap=True,
                                     translateSnap=True,
                                     pen=ROIpen, number=self.ROInumber)
        
        self.ROInumber += 1
        
        self.roilist.append(self.roi)
        
        self.ROIButton.setChecked(False)

#        else:
#
#            self.vb.removeItem(self.roi)
#            self.roi.hide()
        
    def emit_roi_info(self):
        
#        print('Set ROIs function')
        
        roinumber = len(self.roilist)
        
        if roinumber == 0:
            
            print('Please select a valid ROI for beads tracking')
            
        else:
            
            coordinates = np.zeros((4))
            
            for i in range(len(self.roilist)):
                
    #            print(self.roilist[i].pos())
    #            print(self.roilist[i].size())
                xmin, ymin = self.roilist[i].pos()
                xmax, ymax = self.roilist[i].pos() + self.roilist[i].size()
        
                coordinates = np.array([xmin, xmax, ymin, ymax])  
#            roicoordinates[i] = coordinates
                
#            self.roiInfoSignal.emit(roinumber, roicoordinates)
            self.roiInfoSignal.emit(roinumber, coordinates)

    def delete_roi(self):
        
        for i in range(len(self.roilist)):
            
            self.vb.removeItem(self.roilist[i])
            self.roilist[i].hide()
            
        self.roilist = []
        self.delete_roiButton.setChecked(False)
        self.ROInumber = 0
        
    def toggle_liveview(self):
        
        if self.liveviewButton.isChecked():
            
            self.liveviewSignal.emit(True)
        
        else:
            
            self.liveviewSignal.emit(False)
            self.liveviewButton.setChecked(False)
            self.emit_roi_info()
            self.img.setImage(np.zeros((512,512)), autoLevels=False)
            print('live view stopped')
        
    @pyqtSlot(np.ndarray)
    def get_image(self, img):
        
        self.img.setImage(img, autoLevels=False)
        
    @pyqtSlot(np.ndarray, np.ndarray, np.ndarray)
    def get_data(self, time, xData, yData):
        
        self.xCurve.setData(time, xData)
        self.yCurve.setData(time, yData)
        
        self.xyDataItem.setData(xData, yData)
        
        if len(xData) > 2:
        
            cov = np.cov(xData, yData)
            
            a, b, theta = tools.cov_ellipse(cov, nsig=1)
            
            xmean = np.mean(xData)
            ymean = np.mean(yData)
            
#            print(xmean, ymean)
#            print(type(xmean))
            
            t = np.linspace(0, 2 * np.pi, 1000)
            
            x = np.sqrt(a) * np.cos(t + theta) + np.mean(xData)
            y = np.sqrt(b) * np.sin(t + theta) + np.mean(yData)
            
            self.xyDataEllipse.setData(x, y)
            self.xyDataMean.setData([xmean], [ymean])
        
    @pyqtSlot(bool, bool, bool)
    def get_backend_states(self, tracking, feedback, savedata):
        
        print('get_backend_states')
        
        if tracking is True:
            
            self.trackingBeadsBox.setChecked(True)
        
        if tracking is False:
            
            self.trackingBeadsBox.setChecked(False)
            
        if feedback is True:
            
            self.feedbackLoopBox.setChecked(True)
            
        if feedback is False:
            
            self.feedbackLoopBox.setChecked(False)
            
        if savedata is True:
            
            self.saveDataBox.setChecked(True)
            
        if savedata is False:
            
            self.saveDataBox.setChecked(False)

    def emit_save_data_state(self):
        
        if self.saveDataBox.isChecked():
            
            self.saveDataSignal.emit(True)
            self.emit_roi_info()
            
        else:
            
            self.saveDataSignal.emit(False)
        
    def make_connection(self, backend):
            
        backend.changedImage.connect(self.get_image)
        backend.changedData.connect(self.get_data)
        backend.updateGUIcheckboxSignal.connect(self.get_backend_states)
        
    def setup_gui(self):
        
        # GUI layout
        
        grid = QtGui.QGridLayout()
        self.setLayout(grid)
        
        # parameters widget
        
        self.paramWidget = QtGui.QFrame()
        self.paramWidget.setFrameStyle(QtGui.QFrame.Panel |
                                       QtGui.QFrame.Raised)
        
        self.paramWidget.setFixedHeight(200)
        self.paramWidget.setFixedWidth(250)
        
        grid.addWidget(self.paramWidget, 0, 1)
        
        # image widget layout
        
        imageWidget = pg.GraphicsLayoutWidget()
        imageWidget.setMinimumHeight(350)
        imageWidget.setMinimumWidth(350)
        
        self.vb = imageWidget.addViewBox(row=0, col=0)
        self.vb.setAspectLocked(True)
        self.vb.setMouseMode(pg.ViewBox.RectMode)
        self.img = pg.ImageItem()
        self.img.translate(-0.5, -0.5)
        self.vb.addItem(self.img)
        self.vb.setAspectLocked(True)
        imageWidget.setAspectLocked(True)
        grid.addWidget(imageWidget, 0, 0)
        
        # set up histogram for the liveview image

        self.hist = pg.HistogramLUTItem(image=self.img)
        lut = viewbox_tools.generatePgColormap(cmaps.parula)
        self.hist.gradient.setColorMap(lut)
#        self.hist.vb.setLimits(yMin=800, yMax=3000)

        ## TO DO: fix histogram range


        for tick in self.hist.gradient.ticks:
            tick.hide()
        imageWidget.addItem(self.hist, row=0, col=1)
        
        # xy drift graph (graph without a fixed range)
        
        self.xyGraph = pg.GraphicsWindow()
#        self.xyGraph.resize(200, 300)
        self.xyGraph.setAntialiasing(True)
        
        self.xyGraph.statistics = pg.LabelItem(justify='right')
        self.xyGraph.addItem(self.xyGraph.statistics)
        self.xyGraph.statistics.setText('---')
        
        self.xyGraph.xPlot = self.xyGraph.addPlot(row=1, col=0)
        self.xyGraph.xPlot.setLabels(bottom=('Time', 's'),
                            left=('Y position', 'nm'))   # TO DO: clean-up the x-y mess (they're interchanged)
        self.xyGraph.xPlot.showGrid(x=True, y=True)
        self.xCurve = self.xyGraph.xPlot.plot(pen='b')
        
        self.xyGraph.yPlot = self.xyGraph.addPlot(row=0, col=0)
        self.xyGraph.yPlot.setLabels(bottom=('Time', 's'),
                                     left=('X position', 'nm'))
        self.xyGraph.yPlot.showGrid(x=True, y=True)
        self.yCurve = self.xyGraph.yPlot.plot(pen='r')
        
        # xy drift graph (2D point plot)
        
        self.xyPoint = pg.GraphicsWindow()
        self.xyPoint.resize(400, 400)
        self.xyPoint.setAntialiasing(False)
        
#        self.xyPoint.xyPointPlot = self.xyGraph.addPlot(col=1)
#        self.xyPoint.xyPointPlot.showGrid(x=True, y=True)
        
        self.xyplotItem = self.xyPoint.addPlot()
        self.xyplotItem.showGrid(x=True, y=True)
        self.xyplotItem.setLabels(bottom=('X position', 'nm'),
                                  left=('Y position', 'nm'))
        
        self.xyDataItem = self.xyplotItem.plot([], pen=None, symbolBrush=(255,0,0), 
                                               symbolSize=5, symbolPen=None)
        
        self.xyDataMean = self.xyplotItem.plot([], pen=None, symbolBrush=(117, 184, 200), 
                                               symbolSize=5, symbolPen=None)
        
        self.xyDataEllipse = self.xyplotItem.plot(pen=(117, 184, 200))

        
        # LiveView Button

        self.liveviewButton = QtGui.QPushButton('camera LIVEVIEW')
        self.liveviewButton.setCheckable(True)
        self.liveviewButton.clicked.connect(self.toggle_liveview)
        
        # create ROI button
    
        self.ROIButton = QtGui.QPushButton('add ROI')
        self.ROIButton.setCheckable(True)
        self.ROIButton.clicked.connect(self.craete_roi)
        
        # delete ROI button
        
        self.delete_roiButton = QtGui.QPushButton('delete ROIs')
        self.delete_roiButton.clicked.connect(self.delete_roi)
        
        # position tracking checkbox
        
        self.exportDataButton = QtGui.QPushButton('export current data')

        # position tracking checkbox
        
        self.trackingBeadsBox = QtGui.QCheckBox('Track beads')
        self.trackingBeadsBox.stateChanged.connect(self.emit_roi_info)
        
        # turn ON/OFF feedback loop
        
        self.feedbackLoopBox = QtGui.QCheckBox('Feedback loop')

        # save data signal
        
        self.saveDataBox = QtGui.QCheckBox("Save data")
        self.saveDataBox.stateChanged.connect(self.emit_save_data_state)
        
        
        # button to clear the data
        
        self.clearDataButton = QtGui.QPushButton('Clear data')
        
        # buttons and param layout
        
        subgrid = QtGui.QGridLayout()
        self.paramWidget.setLayout(subgrid)

        subgrid.addWidget(self.liveviewButton, 0, 0)
        subgrid.addWidget(self.ROIButton, 1, 0)
        subgrid.addWidget(self.delete_roiButton, 2, 0)
        subgrid.addWidget(self.exportDataButton, 3, 0)
        subgrid.addWidget(self.clearDataButton, 4, 0)
        subgrid.addWidget(self.trackingBeadsBox, 1, 1)
        subgrid.addWidget(self.feedbackLoopBox, 2, 1)
        subgrid.addWidget(self.saveDataBox, 3, 1)

#        subgrid.addWidget(self.tcspcFeedbackBox, 7, 0)  # TO DO: put this in the tcpsc widget (plus signals, etc) and not here

        
        grid.addWidget(self.xyGraph, 1, 0)
        grid.addWidget(self.xyPoint, 1, 1)
        
        
    def closeEvent(self, *args, **kwargs):
        
        self.closeSignal.emit()
        
        super().closeEvent(*args, **kwargs)
        
class Backend(QtCore.QObject):
    
    changedImage = pyqtSignal(np.ndarray)
    changedData = pyqtSignal(np.ndarray, np.ndarray, np.ndarray)
    updateGUIcheckboxSignal = pyqtSignal(bool, bool, bool)

    XYdriftCorrectionIsDone = pyqtSignal(float, float, float)  # signal to emit new piezo position after drift correction
    
    XYtcspcIsDone = pyqtSignal()
    XYtcspcCorrection = pyqtSignal()

    def __init__(self, andor, adw, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.andor = andor
        self.adw = adw
        self.initialize_camera()
        self.setup_camera()
        
        # folder
        
        today = str(date.today()).replace('-', '')  # TO DO: change to get folder from microscope
        root = r'C:\\Data\\'
        folder = root + today
        
        filename = r'\xydata'
        self.filename = folder + filename
        
        self.viewtimer = QtCore.QTimer()
        self.viewtimer.timeout.connect(self.update)
        
        self.tracking_value = False
        self.save_data_state = False
        self.feedback_active = False

        self.npoints = 1200
        self.buffersize = 30000
        
        self.currentx = 0
        self.currenty = 0
        
        self.reset()
        self.reset_data_arrays()
        
        self.counter = 0
        
    def setup_camera(self):
        
        self.pxSize = 80  # in nm
        self.shape = (512, 512) # TO DO: change to 256 x 256
        self.expTime = 0.300   # in sec
        
        self.andor.set_exposure_time(self.expTime)
        self.andor.set_image(shape=self.shape)
        
        print('FOV size = {}'.format(self.shape))

        # Temperature

        self.andor.cooler_on = True
        self.andor.temperature_setpoint = -20   # in °C
        
        # Frame transfer mode
        
        self.andor.frame_transfer_mode = True
        print('Frame transfer mode =', self.andor.frame_transfer_mode)

        # Horizontal readout speed

        ad = 1   # 16-bit DAC
        typ = 0   # EM mode
        index = 0   # 1 MHz
        self.andor.lib.SetHSSpeed(ct.c_int(ad), ct.c_int(typ), ct.c_int(index))
        
        hrate = self.andor.true_horiz_shift_speed(index=0, typ=0, ad=1)
        print('Horizontal readout rate = {} MHz'.format(hrate.magnitude))
        
        # pre-amp GAIN

        self.andor.preamp = 2  # index 2 for preamp gain = 4.7 
        
        gain = self.andor.true_preamp(2)
        print('PreAmp gain = {}'.format(np.round(gain, 1)))

        # EM GAIN
        
        self.andor.EM_gain_mode = 'DAC255'
        self.andor.EM_gain = 1  # EM gain set to 100

        print('EM gain = {}'.format(self.andor.EM_gain))
    
        # Vertical shift speed
        
        self.andor.vert_shift_speed = 4
        
        vspeed = self.andor.true_vert_shift_speed(4)
        print('Vertical shift speed = {} µs'.format(np.round(vspeed.magnitude,
                                                             1)))
        
    def initialize_camera(self):
        
        cam = 0
        self.andor.current_camera = self.andor.camera_handle(cam)
        self.andor.lib.Initialize()
        print('idn:', self.andor.idn)
    
    @pyqtSlot(bool)
    def liveview(self, value):

        if value:
            self.liveview_start()

        else:
            self.liveview_stop()

        
    def liveview_start(self):
        
        self.initial = True
        
        print('Temperature = {} °C'.format(self.andor.temperature))
        print(self.andor.temperature_status)

        # Initial image
        
        self.andor.acquisition_mode = 'Run till abort'
        print('Acquisition mode:', self.andor.acquisition_mode)
        self.andor.shutter(0, 1, 0, 0, 0)
        self.andor.start_acquisition()
        
        time.sleep(self.expTime * 2)
          
        self.image = self.andor.most_recent_image16(self.shape)

        self.changedImage.emit(self.image)

        self.viewtimer.start(400) # DON'T USE time.sleep() inside the update()
                                  # 400 ms ~ acq time + gaussian fit time
    
    def liveview_stop(self):
        
        self.viewtimer.stop()
        self.andor.abort_acquisition()
#        self.andor.shutter(0, 2, 0, 0, 0)  # TO DO: implement toggle shutter
                    
    def update(self):
        """ General update method """
        
        self.update_view()

        if self.tracking_value:
                
            self.tracking()
            self.update_graph_data()
            
    def update_view(self):
        """ Image update while in Liveview mode """

        self.image = self.andor.most_recent_image16(self.shape)
        self.changedImage.emit(self.image)
            
    def update_graph_data(self):
        """ Update the data displayed in the graphs """

        self.xPosition = self.x
        self.yPosition = self.y

        if self.ptr < self.npoints:
            self.xData[self.ptr] = self.xPosition
            self.yData[self.ptr] = self.yPosition
            self.time[self.ptr] = self.currentTime
            
            self.changedData.emit(self.time[0:self.ptr + 1],
                                  self.xData[0:self.ptr + 1],
                                  self.yData[0:self.ptr + 1])

        else:
            self.xData[:-1] = self.xData[1:]
            self.xData[-1] = self.xPosition
            self.yData[:-1] = self.yData[1:]
            self.yData[-1] = self.yPosition
            self.time[:-1] = self.time[1:]
            self.time[-1] = self.currentTime
            
            self.changedData.emit(self.time, self.xData, self.yData)

        self.ptr += 1
    
    @pyqtSlot(bool)
    def toggle_tracking(self, val):
        ''' Toggles ON/OFF tracking of fiducial fluorescent beads. 
        Drift correction feedback loop is not automatically started.'''
        
        self.startTime = time.time()
        
        if val is True:
            
            self.tracking_value = True
            self.counter = 0
            
            self.reset()
            self.reset_data_arrays()
        
        if val is False:
        
            self.tracking_value = False
            
    @pyqtSlot(bool)
    def toggle_feedback(self, val):
        ''' Toggles ON/OFF feedback for either continous (TCSPC) 
        or discrete (confocal imaging) correction'''
        
        if val is True:
            
            self.feedback_active = True

            # set up and start actuator process
            
            self.set_actuator_param()
            self.adw.Start_Process(4)
            
            print('Feedback loop ON')
            
        if val is False:
            
            self.feedback_active = False
            print('Feedback loop OFF')
            
    def gaussian_fit(self):
        
        # set main reference frame
        
        xmin, xmax, ymin, ymax = self.ROIcoordinates
        xmin_nm, xmax_nm, ymin_nm, ymax_nm = self.ROIcoordinates * self.pxSize
        
        # select the data of the image corresponding to the ROI

        array = self.image[xmin:xmax, ymin:ymax]
        
#        result = Image.fromarray(self.image.astype('uint16'))
#        result.save(r'C:\Data\{}.tiff'.format('512x512'))
#        
#        result = Image.fromarray(array.astype('uint16')) # TO DO: clean up this save
#        result.save(r'C:\Data\{}.tiff'.format('20x20'))
        
        # set new reference frame
        
        xrange_nm = xmax_nm - xmin_nm
        yrange_nm = ymax_nm - ymin_nm
             
        x_nm = np.arange(0, xrange_nm, self.pxSize)
        y_nm = np.arange(0, yrange_nm, self.pxSize)
        
        (Mx_nm, My_nm) = np.meshgrid(x_nm, y_nm)
        
        # find max 
        
        argmax = np.unravel_index(np.argmax(array, axis=None), array.shape)
        
        x_center_id = argmax[0]
        y_center_id = argmax[1]
        
        # define area around maximum
    
        xrange = 10 # in px
        yrange = 10 # in px
        
        xmin_id = int(x_center_id-xrange)
        xmax_id = int(x_center_id+xrange)
        
        ymin_id = int(y_center_id-yrange)
        ymax_id = int(y_center_id+yrange)
        
        array_sub = array[xmin_id:xmax_id, ymin_id:ymax_id]
                
        xsubsize = 2 * xrange
        ysubsize = 2 * yrange
        
#        plt.imshow(array_sub, cmap=cmaps.parula, interpolation='None')
        
        x_sub_nm = np.arange(0, xsubsize) * self.pxSize
        y_sub_nm = np.arange(0, ysubsize) * self.pxSize

        [Mx_sub, My_sub] = np.meshgrid(x_sub_nm, y_sub_nm)
        
        # make initial guess for parameters
        
        bkg = np.min(array)
        A = np.max(array) - bkg
        σ = 130 # nm
        x0 = x_sub_nm[int(xsubsize/2)]
        y0 = y_sub_nm[int(ysubsize/2)]
        
        initial_guess_G = [A, x0, y0, σ, σ, bkg]
         
        poptG, pcovG = opt.curve_fit(PSF.gaussian2D, (Mx_sub, My_sub), 
                                     array_sub.ravel(), p0=initial_guess_G)
        
        # retrieve results

        poptG = np.around(poptG, 2)
    
        A, x0, y0, σ_x, σ_y, bkg = poptG
    
        self.currentx = x0 + Mx_nm[xmin_id, ymin_id]
        self.currenty = y0 + My_nm[xmin_id, ymin_id]
        
            
    def tracking(self):
        
        """ 
        Function to track fiducial markers (fluorescent beads) from the selected ROI.
        The position of the beads is calculated through a guassian fit. 
        If feedback_active = True it also corrects for drifts in xy
        If save_data_state = True it saves the xy data
        
        """
        
        try:
            self.gaussian_fit()
            
        except(RuntimeError, ValueError):
            
            print('Gaussian fit did not work')
               
        if self.initial is True:
            
            self.initialx = self.currentx
            self.initialy = self.currenty
            
            self.initial = False
            
        self.x = self.currentx - self.initialx
        self.y = self.currenty - self.initialy
        
        self.currentTime = time.time() - self.startTime
        
        if self.save_data_state:
            
            self.time_array[self.j] = self.currentTime
            self.x_array[self.j] = self.x
            self.y_array[self.j] = self.y
            
            self.j += 1
            
            if self.j >= (self.buffersize - 5):    # TO DO: -5 bad fix
                
                self.export_data()
                self.reset_data_arrays()
                
                print('Data array, longer than buffer size, data_array reset')
                
        if self.feedback_active:
            
#            print('feedback starting...')
            
            dx = 0
            dy = 0
            threshold = 7
            far_threshold = 15
            correct_factor = 0.6
            security_thr = 0.2 # in µm
            
            if np.abs(self.x) > threshold:
                
                if dx < far_threshold:
                    
                    dx = correct_factor * dx
                
                dx = - (self.x)/1000 # conversion to µm

#                print('dx', dx)
                
            if np.abs(self.y) > threshold:
                
                if dy < far_threshold:
                    
                    dy = correct_factor * dy
                
                dy = - (self.y)/1000 # conversion to µm
                
#                print('dy', dy)
        
            if dx > security_thr or dy > security_thr:
                
                print('Correction movement larger than 200 nm, active correction turned OFF')
                
            else:
                
                # compensate for the mismatch between camera/piezo system of reference
                
                theta = np.radians(-3.7)   # 86.3 (or 3.7) is the angle between camera and piezo (measured)
                c, s = np.cos(theta), np.sin(theta)
                R = np.array(((c,-s), (s, c)))
                
                dy, dx = np.dot(R, np.asarray([dx, dy]))
                
                # add correction to piezo position
    
                self.piezoXposition = self.piezoXposition + dx  
                self.piezoYposition = self.piezoYposition + dy  
                
                self.actuator_xy(self.piezoXposition, self.piezoYposition)
                         
        self.counter += 1  # counter to check how many times this function is executed

        
    def set_actuator_param(self, pixeltime=1000):

        self.adw.Set_FPar(46, tools.timeToADwin(pixeltime))
        
        # set-up actuator initial param
    
        x_f = tools.convert(self.piezoXposition, 'XtoU')
        y_f = tools.convert(self.piezoYposition, 'XtoU')
        
        self.adw.Set_FPar(40, x_f)
        self.adw.Set_FPar(41, y_f)
            
        self.adw.Set_Par(40, 1)
        
    def actuator_xy(self, x_f, y_f):
        
        x_f = tools.convert(x_f, 'XtoU')
        y_f = tools.convert(y_f, 'XtoU')
        
        self.adw.Set_FPar(40, x_f)
        self.adw.Set_FPar(41, y_f)
        
        self.adw.Set_Par(40, 1)
            
    @pyqtSlot(bool)
    def discrete_xy_correction(self, val): # TO DO: change name to single_xy_correction
        
        print('Feedback {}'.format(val))
        
        self.feedback_active = val
        
#        self.andor.shutter(0, 1, 0, 0, 0)
        
        self.andor.start_acquisition()
        
        time.sleep(self.expTime * 3)
        
        self.image = self.andor.most_recent_image16(self.shape)

        self.changedImage.emit(self.image)
        
        self.andor.abort_acquisition()
        
        self.tracking()
        
        self.update_graph_data()
        
        self.XYdriftCorrectionIsDone.emit(self.piezoXposition, 
                                          self.piezoYposition, 
                                          self.piezoZposition)
        
        print('drift correction ended...')
            
    def reset(self):
        
        self.initial = True
        self.xData = np.zeros(self.npoints)
        self.yData = np.zeros(self.npoints)
        self.time = np.zeros(self.npoints)
        self.ptr = 0
        self.startTime = time.time()
        self.j = 0  # iterator on the data array
        
        self.changedData.emit(self.time, self.xData, self.yData)
        
    def reset_data_arrays(self):
        
        self.time_array = np.zeros(self.buffersize, dtype=np.float16)
        self.x_array = np.zeros(self.buffersize, dtype=np.float16)
        self.y_array = np.zeros(self.buffersize, dtype=np.float16)
        
        
    def export_data(self):
        
        """
        Exports the x, y and t data into a .txt file
        """

        fname = self.filename
        filename = tools.getUniqueName(fname)
        filename = filename + '_xydata.txt'
        
        size = self.j
        savedData = np.zeros((3, size))
        
        savedData[0, :] = self.time_array[0:self.j]
        savedData[1, :] = self.x_array[0:self.j]
        savedData[2, :] = self.y_array[0:self.j]
        
        np.savetxt(filename, savedData.T,  header='t (s), x (nm), y(nm)') # transpose for easier loading
        
        print('xy data exported to', filename)
        
    @pyqtSlot(bool)
    def get_save_data_state(self, val):
        
        self.save_data_state = val
        print('save_data_state = {}'.format(val))
    
    @pyqtSlot(dict)
    def get_scan_parameters(self, params):

        self.initialPos = params['initialPos']
        
        self.piezoXposition, self.piezoYposition, self.piezoZposition = self.initialPos
        
        print('positions from scanner', self.piezoXposition, self.piezoYposition, self.piezoZposition)
        
    @pyqtSlot(int, np.ndarray)
    def get_roi_info(self, N, coordinates_array):
        
#        self.numberOfROIs = N
        self.ROIcoordinates = coordinates_array.astype(int)
        print('got ROI coordinates')
        
    @pyqtSlot(bool, str)   
    def get_tcspc_signal(self, val, fname):
        
        """ 
        Get signal to start/stop xy position tracking and lock during 
        tcspc acquisition. It also gets the name of the tcspc file to produce
        the corresponding xy_data file
        
        bool val
        True: starts the tracking and feedback loop
        False: stops saving the data and exports the data during tcspc measurement
        tracking and feedback are not stopped automatically 
        
        """
        
        self.filename = fname
        
        if val is True:
            
            self.reset()
            self.reset_data_arrays()
            
            self.toggle_tracking(True)
            self.toggle_feedback(True)
            self.save_data_state = True
            
        else:
            
            self.export_data()
            self.save_data_state = False
            
        self.updateGUIcheckboxSignal.emit(self.tracking_value, 
                                          self.feedback_active, 
                                          self.save_data_state)
        
    @pyqtSlot(bool, str)   
    def get_scan_signal(self, val, fname):
        
        """ 
        Get signal to stop continous xy tracking/feedback if active and to
        go to discrete xy tracking/feedback mode if required
        """
    @pyqtSlot(float, np.ndarray)    
    def get_minflux_signal(self, acqtime, r):
        
        x_f, y_f = r
        z_f = tools.convert(adw.Get_FPar(52), 'UtoX')
        
        self.aux_moveTo(x_f, y_f, z_f)
        
        self.toggle_tracking(True)
        self.toggle_feedback(True)
        self.save_data_state = True
        
        self.updateGUIcheckboxSignal.emit(self.tracking_value, 
                                          self.feedback_active, 
                                          self.save_data_state)
        
    def set_aux_moveTo_param(self, x_f, y_f, z_f, n_pixels_x=128, n_pixels_y=128,
                         n_pixels_z=128, pixeltime=2000):

        x_f = tools.convert(x_f, 'XtoU')
        y_f = tools.convert(y_f, 'XtoU')
        z_f = tools.convert(z_f, 'XtoU')

        self.adw.Set_Par(21, n_pixels_x)
        self.adw.Set_Par(22, n_pixels_y)
        self.adw.Set_Par(23, n_pixels_z)

        self.adw.Set_FPar(23, x_f)
        self.adw.Set_FPar(24, y_f)
        self.adw.Set_FPar(25, z_f)

        self.adw.Set_FPar(26, tools.timeToADwin(pixeltime))

    def aux_moveTo(self, x_f, y_f, z_f): # TO DO: delete this two functions, only useful for the initial and final movement in stand-alone mode

        self.set_aux_moveTo_param(x_f, y_f, z_f)
        self.adw.Start_Process(2)
        
    def make_connection(self, frontend):
            
        frontend.liveviewSignal.connect(self.liveview)
        frontend.roiInfoSignal.connect(self.get_roi_info)
        frontend.closeSignal.connect(self.stop)
        frontend.saveDataSignal.connect(self.get_save_data_state)
        frontend.exportDataButton.clicked.connect(self.export_data)
        frontend.clearDataButton.clicked.connect(self.reset)
        frontend.clearDataButton.clicked.connect(self.reset_data_arrays)
        frontend.trackingBeadsBox.stateChanged.connect(lambda: self.toggle_tracking(frontend.trackingBeadsBox.isChecked()))
        frontend.feedbackLoopBox.stateChanged.connect(lambda: self.toggle_feedback(frontend.feedbackLoopBox.isChecked()))
        
        # lambda function and gui_###_state are used to toggle both backend
        # states and checkbox status so that they always correspond 
        # (checked <-> active, not checked <-> inactive)
        
    def stop(self):
        
        self.viewtimer.stop()
        
        try:
            
            self.andor.abort_acquisition()
            
        except:  # TO DO: write this code properly
            
            pass
                
        self.andor.shutter(0, 2, 0, 0, 0)
            
        self.andor.finalize()
        
        # Go back to 0 position

        x_0 = 0
        y_0 = 0
        z_0 = 0

        self.aux_moveTo(x_0, y_0, z_0)
        

if __name__ == '__main__':

    app = QtGui.QApplication([])
#    app.setStyle(QtGui.QStyleFactory.create('fusion'))
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    
    andor = ccd.CCD()
    
    DEVICENUMBER = 0x1
    adw = ADwin.ADwin(DEVICENUMBER, 1)
    scan.setupDevice(adw)
    
    gui = Frontend()
    worker = Backend(andor, adw)
    
    gui.make_connection(worker)
    worker.make_connection(gui)
    
    # initialize fpar_70, fpar_71, fpar_72 ADwin position parameters
        
    pos_zero = tools.convert(0, 'XtoU')
        
    worker.adw.Set_FPar(70, pos_zero)
    worker.adw.Set_FPar(71, pos_zero)
    worker.adw.Set_FPar(72, pos_zero)
    
    worker.aux_moveTo(10, 10, 10) # in µm
    
    time.sleep(0.200)
    
    worker.piezoXposition = 10.0 # in µm
    worker.piezoYposition = 10.0 # in µm
    worker.piezoZposition = 10.0 # in µm

    gui.setWindowTitle('xy drift correction')
    gui.show()
    app.exec_()
        