# -*- coding: utf-8 -*-
"""
Created on Fri Jun  1 14:18:19 2018

@author: Florencia D. Choque
Mini script with three Threads: scan, TCSPC and focus lock
"""

import numpy as np
import time
import os
import sys
from datetime import date, datetime

from threading import Thread

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from pyqtgraph.dockarea import Dock, DockArea
import qdarkstyle

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QDockWidget
from tkinter import Tk, filedialog

import drivers.ADwin as ADwin

from drivers.minilasevo import MiniLasEvo
import drivers.picoharp as picoharp
import drivers.ids_cam as ids_cam

import scan as scan
import new_focus as focus
import tcspc
import measurements.minflux as minflux
import measurements.psf as psf

import tools.tools as tools

π = np.pi

class Frontend(QtGui.QMainWindow):

    closeSignal = pyqtSignal()

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.setWindowTitle('PyFLUX')

        self.cwidget = QtGui.QWidget()
        self.setCentralWidget(self.cwidget)

        # Actions in menubar

        menubar = self.menuBar()
        fileMenu = menubar.addMenu('Measurement')

        self.psfWidget = psf.Frontend()
        self.minfluxWidget = minflux.Frontend()

        self.psfMeasAction = QtGui.QAction('PSF measurement', self)
        self.psfMeasAction.setStatusTip('Routine to measure one MINFLUX PSF')
        fileMenu.addAction(self.psfMeasAction)
        
        self.psfMeasAction.triggered.connect(self.psf_measurement)
    
        self.minfluxMeasAction = QtGui.QAction('MINFLUX measurement', self)
        self.minfluxMeasAction.setStatusTip('Routine to perform a tcspc-MINFLUX measurement')
        fileMenu.addAction(self.minfluxMeasAction)
        
        self.minfluxMeasAction.triggered.connect(self.minflux_measurement)

        # GUI layout
        grid = QtGui.QGridLayout()
        self.cwidget.setLayout(grid)

        ## scan dock
        self.scanWidget = scan.Frontend()

        scanDock = QDockWidget('Scan', self)
        scanDock.setWidget(self.scanWidget)
        scanDock.setFeatures(QDockWidget.DockWidgetVerticalTitleBar | 
                                 QDockWidget.DockWidgetFloatable |
                                 QDockWidget.DockWidgetClosable)
        scanDock.setAllowedAreas(Qt.LeftDockWidgetArea)

        self.addDockWidget(Qt.LeftDockWidgetArea, scanDock)

        ## focus lock dock
        self.focusWidget = focus.Frontend()

        focusDock = QDockWidget('Focus Lock', self)
        focusDock.setWidget(self.focusWidget)
        focusDock.setFeatures(QDockWidget.DockWidgetVerticalTitleBar | 
                                 QDockWidget.DockWidgetFloatable |
                                 QDockWidget.DockWidgetClosable)
        focusDock.setAllowedAreas(Qt.RightDockWidgetArea)

        self.addDockWidget(Qt.RightDockWidgetArea, focusDock)
        
        ## tcspc dock
        self.tcspcWidget = tcspc.Frontend()
        
        tcspcDock = QDockWidget('Time-correlated single-photon counting', self)
        tcspcDock.setWidget(self.tcspcWidget)
        tcspcDock.setFeatures(QDockWidget.DockWidgetVerticalTitleBar | 
                                 QDockWidget.DockWidgetFloatable |
                                 QDockWidget.DockWidgetClosable)
        tcspcDock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, tcspcDock)
        

        # sizes to fit my screen properly
        self.scanWidget.setMinimumSize(1000, 598)
        # self.xyWidget.setMinimumSize(800, 598)
        self.tcspcWidget.setMinimumSize(850, 370)
        self.focusWidget.setMinimumSize(850, 370)
        self.move(1, 1)

    def make_connection(self, backend):

        backend.zWorker.make_connection(self.focusWidget)
        backend.scanWorker.make_connection(self.scanWidget)
        backend.tcspcWorker.make_connection(self.tcspcWidget)
        
        backend.minfluxWorker.make_connection(self.minfluxWidget)
        backend.psfWorker.make_connection(self.psfWidget)
        
    def psf_measurement(self):

        self.psfWidget.show()
        
    def minflux_measurement(self):
        
        self.minfluxWidget.show()
        self.minfluxWidget.emit_filename()

    def closeEvent(self, *args, **kwargs):

        self.closeSignal.emit()
        time.sleep(1)
        
        focusThread.exit()
        tcspcWorkerThread.exit()
        scanThread.exit()
        minfluxThread.exit()
        super().closeEvent(*args, **kwargs)
        
        app.quit()         

class Backend(QtCore.QObject):

    askROIcenterSignal = pyqtSignal()
    moveToSignal = pyqtSignal(np.ndarray)
    tcspcStartSignal = pyqtSignal(str, int, int)
    xyzStartSignal = pyqtSignal()
    xyzEndSignal = pyqtSignal(str)
    xyMoveAndLockSignal = pyqtSignal(np.ndarray)
    

    def __init__(self, adw, ph, camera, diodelaser, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.zWorker = focus.Backend(camera, adw)
        self.scanWorker = scan.Backend(adw, diodelaser)
        self.tcspcWorker = tcspc.Backend(ph)
        
        self.minfluxWorker = minflux.Backend(adw)
        self.psfWorker = psf.Backend()
        
    def setup_minflux_connections(self):
        
        self.scanWorker.ROIcenterSignal.connect(self.minfluxWorker.get_ROI_center)
        
        self.minfluxWorker.tcspcPrepareSignal.connect(self.tcspcWorker.prepare_minflux)
        #self.minfluxWorker.tcspcStartSignal.connect(self.xyWorker.start_tracking_pattern)
        self.minfluxWorker.tcspcStartSignal.connect(self.tcspcWorker.measure_minflux)
        
        #self.minfluxWorker.xyzStartSignal.connect(self.xyWorker.get_lock_signal)
        self.minfluxWorker.xyzStartSignal.connect(self.zWorker.get_lock_signal)
        
        # TO DO: check if this is compatible with both psf and minflux measurement
        
        #self.minfluxWorker.moveToSignal.connect(self.xyWorker.get_move_signal)
        
        self.minfluxWorker.shutterSignal.connect(self.scanWorker.shutter_handler)
        #self.minfluxWorker.shutterSignal.connect(self.xyWorker.shutter_handler)
        self.minfluxWorker.shutterSignal.connect(self.zWorker.shutter_handler)
        
        self.tcspcWorker.tcspcDoneSignal.connect(self.minfluxWorker.get_tcspc_done_signal)
       
        self.minfluxWorker.saveConfigSignal.connect(self.scanWorker.saveConfigfile)
        #self.minfluxWorker.xyzEndSignal.connect(self.xyWorker.get_end_measurement_signal)
        self.minfluxWorker.xyzEndSignal.connect(self.zWorker.get_end_measurement_signal)
        #self.minfluxWorker.xyStopSignal.connect(self.xyWorker.get_stop_signal)

    def setup_psf_connections(self):
        
        self.psfWorker.scanSignal.connect(self.scanWorker.get_scan_signal)
        #self.psfWorker.xySignal.connect(self.xyWorker.single_xy_correction)
        self.psfWorker.zSignal.connect(self.zWorker.single_z_correction)
        #self.psfWorker.xyStopSignal.connect(self.xyWorker.get_stop_signal)
        self.psfWorker.zStopSignal.connect(self.zWorker.get_stop_signal)
        self.psfWorker.moveToInitialSignal.connect(self.scanWorker.get_moveTo_initial_signal)
       
        self.psfWorker.shutterSignal.connect(self.scanWorker.shutter_handler)
        #self.psfWorker.shutterSignal.connect(self.xyWorker.shutter_handler)
        self.psfWorker.shutterSignal.connect(self.zWorker.shutter_handler)
                
        #self.psfWorker.endSignal.connect(self.xyWorker.get_end_measurement_signal)
        self.psfWorker.endSignal.connect(self.zWorker.get_end_measurement_signal)
        self.psfWorker.saveConfigSignal.connect(self.scanWorker.saveConfigfile)
        
        self.scanWorker.frameIsDone.connect(self.psfWorker.get_scan_is_done)
        #self.xyWorker.xyIsDone.connect(self.psfWorker.get_xy_is_done)
        self.zWorker.zIsDone.connect(self.psfWorker.get_z_is_done)

    def make_connection(self, frontend):
        
        frontend.focusWidget.make_connection(self.zWorker)
        frontend.scanWidget.make_connection(self.scanWorker)
        frontend.tcspcWidget.make_connection(self.tcspcWorker)
        
        frontend.minfluxWidget.make_connection(self.minfluxWorker)
        frontend.psfWidget.make_connection(self.psfWorker)
    
        self.setup_minflux_connections()
        self.setup_psf_connections()
        
        frontend.scanWidget.paramSignal.connect(self.psfWorker.get_scan_parameters)
        # TO DO: write this in a cleaner way, i. e. not in this section, not using frontend
        
        self.scanWorker.focuslockpositionSignal.connect(self.zWorker.get_focuslockposition)
        self.zWorker.focuslockpositionSignal.connect(self.scanWorker.get_focuslockposition)

        frontend.closeSignal.connect(self.stop)

    def stop(self):

        self.scanWorker.stop()
        self.tcspcWorker.stop()
        self.zWorker.stop()

if __name__ == '__main__':

    if not QtGui.QApplication.instance():
        app = QtGui.QApplication([])
    else:
        app = QtGui.QApplication.instance()

    app.setStyle(QtGui.QStyleFactory.create('fusion'))
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

    gui = Frontend()

    port = tools.get_MiniLasEvoPort()
#    port = 'COM5'
    print('[scan] MiniLasEvo diode laser port:', port)
    diodelaser = MiniLasEvo(port)

    #if camera wasnt closed properly just keep using it without opening new one
    try:
        cam = ids_cam.IDS_U3()
    except:
        pass

    ph = picoharp.PicoHarp300()
    
    DEVICENUMBER = 0x1
    adw = ADwin.ADwin(DEVICENUMBER, 1)
    scan.setupDevice(adw)

    worker = Backend(adw, ph, cam, diodelaser)

    gui.make_connection(worker)
    worker.make_connection(gui)
    
    # initial parameters
    
    gui.scanWidget.emit_param()
    worker.scanWorker.emit_param()
    
    gui.minfluxWidget.emit_param()
#    gui.minfluxWidget.emit_param_to_backend()
#    worker.minfluxWorker.emit_param_to_frontend()
    
    gui.psfWidget.emit_param()
    
    ## focus thread

    focusThread = QtCore.QThread()
    worker.zWorker.moveToThread(focusThread)
    worker.zWorker.focusTimer.moveToThread(focusThread)
    worker.zWorker.focusTimer.timeout.connect(worker.zWorker.update)
    print("Focus Timer:", worker.zWorker.focusTimer)

    focusThread.start()

    # focus GUI thread

    # focusGUIThread = QtCore.QThread()
    # gui.focusWidget.moveToThread(focusGUIThread)

    # focusGUIThread.start()

    ## tcspc thread
    
    tcspcWorkerThread = QtCore.QThread()
    worker.tcspcWorker.moveToThread(tcspcWorkerThread)
    worker.tcspcWorker.tcspcTimer.moveToThread(tcspcWorkerThread)
    worker.tcspcWorker.tcspcTimer.timeout.connect(worker.tcspcWorker.update)
    
    tcspcWorkerThread.start()
    
    ## scan thread
    
    scanThread = QtCore.QThread()
    
    worker.scanWorker.moveToThread(scanThread)
    worker.scanWorker.viewtimer.moveToThread(scanThread)
    worker.scanWorker.viewtimer.timeout.connect(worker.scanWorker.update_view)

    scanThread.start()
    
    ## minflux worker thread
    
    minfluxThread = QtCore.QThread()
    worker.minfluxWorker.moveToThread(minfluxThread)
    
    minfluxThread.start()
    
    ## psf worker thread
    
#    psfThread = QtCore.QThread()
#    worker.psfWorker.moveToThread(psfThread)
#    worker.psfWorker.measTimer.moveToThread(psfThread)
#    worker.psfWorker.measTimer.timeout.connect(worker.psfWorker.measurement_loop)
#
#    psfThread.start()
    
    gui.showMaximized()
    #app.exec_()