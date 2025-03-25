# -*- coding: utf-8 -*-
"""
TCSPC con tracking.

@author: azelcer
"""

import numpy as np
from datetime import date
import os
from tkinter import Tk, filedialog
import logging as _lgn

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtWidgets import QGroupBox
from PyQt5 import QtWidgets
import tools.swabiantools as _st
from swabian.backend import TCSPC_Backend

import configparser
from dataclasses import dataclass as _dataclass

import qdarkstyle


_lgr = _lgn.getLogger(__name__)
_lgn.basicConfig(level=_lgn.INFO)


_MAX_EVENTS = 131072
_N_BINS = 50
_MAX_SAMPLES = int(60*200)  # si es cada 5 ms son 200 por segundo


@_dataclass
class PSFMetadata:
    """Metadata of PSFs."""

    scan_range: float  # en µm, 'Scan range (µm)'
    n_pixels:  int  # 'Number of pixels'
    px_size: float  # 'Pixel size (µm)'
    scan_type: str  # 'Scan type'


# está en tools
def loadConfig(filename) -> configparser.SectionProxy:
    """Load a config file and return just the parameters."""
    config = configparser.ConfigParser()
    config.read(filename)
    return config['Scanning parameters']


class TCSPCFrontend(QtWidgets.QFrame):
    """Frontend para TCSPC con tracking."""

    # Signals
    measureSignal = pyqtSignal(np.ndarray, np.ndarray, np.ndarray)

    # Data
    # _localizations_x = np.full((_MAX_SAMPLES,), 0)
    # _localizations_y = np.full((_MAX_SAMPLES,), 0)
    # _shifts = [(0, 0),]
    # _intensities = np.zeros((4, _MAX_SAMPLES,), dtype=np.float64)
    _PSF = None
    _config: PSFMetadata = None
    _pos_vline: pg.InfiniteLine = None

    def __init__(self, *args, **kwargs):
        """Conecta señales."""
        super().__init__(*args, **kwargs)
        # initial directory
        self.initialDir = r"C:\Data"
        self._backend = TCSPC_Backend()
        # FIXME: for developing only
        self.period = self._backend.iinfo.period

        self._init_data()
        self.setup_gui()
        # self._backend.sgnl_new_data.connect(self.get_data)
        self._backend.sgnl_measure_init.connect(self.process_measurement_start)
        self._backend.sgnl_measure_end.connect(self.process_measurement_stop)
        self._timer = QTimer()
        self._timer.timeout.connect(self.update_data)

    def _init_data(self):
        self._hist_data = list(np.histogram([], range=(0, self.period), bins=_N_BINS))
        # self._intensities = np.zeros((4, _MAX_SAMPLES,), dtype=np.float64)
        # self._intensities[:] = np.nan
        # self._last_pos = 0
        # self._localizations_x = np.full((_MAX_SAMPLES,), 0)
        # self._localizations_y = np.full((_MAX_SAMPLES,), 0)
        # self._shifts = [(0, 0),]
        self._intensities, self._positions = self._backend.get_data_buffers()
        self._last_I_index = self._last_pos_indes = 0

    def start_measurement(self):
        """Inicia la medida."""
        try:
            filename = self.filenameEdit.text()
        except Exception:
            filename = "lefilename"
        self._backend.start_measure(filename, self._PSF, self._config)

    @pyqtSlot(str)
    def process_measurement_start(self, filename: str):
        """Procesa inicio de medida."""
        _lgr.info("Iniciando medida con archivo %s", filename)
        self._current_filename = filename
        self.filenameEdit.setText(filename)
        self.clear_plots()
        self._init_data()
        self.measureButton.setEnabled(False)
        self._timer.start(200)  # ms

    def stop_measurement(self):
        """Detiene la medida.

        Sin error checking por hora
        """
        self._backend.stop_measure()

    def process_measurement_stop(self):
        """Procesa fin de medida.

        Sin error checking por hora
        """
        self.measureButton.setEnabled(True)
        self._timer.stop()
        _st.swabian2numpy(self._current_filename, self._backend.period,
                          self._backend.iinfo.APD_info[0].channel,
                          self._backend.iinfo.laser_channel,
                          self._backend.iinfo.tick_channel
                          )

    def load_folder(self):
        """Muestra una ventana de selección de carpeta."""
        try:
            root = Tk()
            root.withdraw()
            folder = filedialog.askdirectory(parent=root, initialdir=self.initialDir)
            root.destroy()
            if folder:
                self.folderEdit.setText(folder)
        except OSError:
            pass

    def load_PSF(self):
        """Elegir archivo NPZ (no tiff)."""
        try:
            root = Tk()
            root.withdraw()
            psffile = filedialog.askopenfile(
                parent=root, title="Elegir PSF", initialdir=self.initialDir,
                filetypes=(("numpy", "*.npy"),), mode="rb")
            root.destroy()
            if psffile:
                try:
                    self._PSF = np.load(psffile, allow_pickle=False)
                    _lgr.info("Cargadas donas con forma %s", self._PSF.shape)
                    psffile.close()
                except Exception as e:
                    print("error abriendo PSF", e, type(e))
        except OSError:
            pass

    def load_config(self):
        """Elegir archivo de configuración."""
        try:
            root = Tk()
            root.withdraw()
            cfgfile = filedialog.askopenfilename(
                parent=root, title="Elegir configuración",
                initialdir=self.initialDir, filetypes=(("txt", "*.txt"),),
            )
            root.destroy()
            if cfgfile:
                try:
                    config = loadConfig(cfgfile)
                except Exception as e:
                    print("error configuración", e, type(e))
        except OSError as e:
            _lgr.error("Error '%s' abriendo archivo de configuracion: %s",
                       type(e), e)
            return
        metadata = PSFMetadata(
            float(config['Scan range (µm)']),
            int(config['Number of pixels']),
            float(config['Pixel size (µm)']),
            config['Scan type']
        )
        if metadata.scan_type != 'xy':
            _lgr.error("Scan invalido")
        _lgr.info("%s", metadata)
        self._config = metadata

    def update_data(self):
        """Receive update graphs."""
        pos_idx, I_idx, delta_t = self._backend.get_last_data()
        try:
            counts, bins = np.histogram(delta_t, range=(0, self.period), bins=_N_BINS)
            self._hist_data[0] += counts

            for plot, data in zip(self.intplots, self._intensities):
                plot.setData(data)  # , connect="finite")
            self.intplots[-1].setData(self._intensities.sum(axis=0))
            self.trace_vline.setValue(I_idx)
            self.histPlot.setData(bins[0:-1], counts)
            self.posPlot.setData(self._positions[0], self._positions[1])

        except Exception as e:
            _lgr.error("Excepción %s recibiendo la información: %s", type(e), e)

    def clear_plots(self):
        """Clear all plots."""
        self.histPlot.clear()
        for p in self.intplots:
            p.clear()

        self.posPlot.clear()

    def setup_gui(self):
        """Initialize the GUI."""
        # widget with tcspc parameters
        self.paramWidget = QGroupBox("TCSPC parameter")
        self.paramWidget.setFixedHeight(250)
        self.paramWidget.setFixedWidth(250)

        phParamTitle = QtWidgets.QLabel("<h2>TCSPC settings</h2>")
        phParamTitle.setTextFormat(QtCore.Qt.RichText)

        # widget to display data
        self.dataWidget = pg.GraphicsLayoutWidget()

        # file/folder widget
        self.fileWidget = QGroupBox("Save options")
        self.fileWidget.setFixedHeight(180)
        self.fileWidget.setFixedWidth(250)
        # Buttons
        self.measureButton = QtWidgets.QPushButton("Measure TTTR")
        self.stopButton = QtWidgets.QPushButton("Stop")

        self.clearButton = QtWidgets.QPushButton("Clear data")

        self.filenameEdit = QtWidgets.QLineEdit("filename")

        # microTime histogram and timetrace
        self.histWidg = self.dataWidget.addPlot(
            row=0, col=0, title="microTime histogram", stepMode=True, fillLevel=0,
        )
        self.histWidg.setLabels(bottom=("ps"), left=("counts"))
        self.histPlot = self.histWidg.plot()

        self.tracePlot = self.dataWidget.addPlot(row=1, col=0, title="Time trace")
        self.tracePlot.setLabels(bottom=("s"), left=("counts"))
        self.intplots: list[pg.PlotDataItem] = [
            self.tracePlot.plot(pen=_) for _ in range(4 + 1)
        ]
        self.trace_vline = pg.InfiniteLine(0)
        self.tracePlot.addItem(self.trace_vline)

        self.posPlotItem = self.dataWidget.addPlot(row=0, col=1, rowspan=2, title="Position")
        self.posPlotItem.showGrid(x=True, y=True)
        self.posPlotItem.setLabels(
            bottom=("X position", "nm"), left=("Y position", "nm")
        )
        self.posPlot: pg.PlotDataItem = self.posPlotItem.plot(
            [], [], pen=None, symbolBrush=(255, 0, 0), symbolSize=5, symbolPen=None
            )
        # folder
        # TO DO: move this to backend
        today = str(date.today()).replace("-", "")
        root = "C:\\Data\\"
        folder = root + today
        try:
            os.mkdir(folder)
        except OSError:
            _lgr.info("Directory %s already exists", folder)
        else:
            _lgr.info("Error creating directory %s", folder)

        self.folderLabel = QtWidgets.QLabel("Folder:")
        self.folderEdit = QtWidgets.QLineEdit(folder)
        self.browseFolderButton = QtWidgets.QPushButton("Browse")
        self.browseFolderButton.setCheckable(True)
        self.browsePSFButton = QtWidgets.QPushButton("PSF")
        self.browsePSFButton.setCheckable(True)
        self.browseConfigButton = QtWidgets.QPushButton("Config")
        self.browseConfigButton.setCheckable(True)

        # GUI connections
        self.measureButton.clicked.connect(self.start_measurement)
        self.stopButton.clicked.connect(self.stop_measurement)
        self.browseFolderButton.clicked.connect(self.load_folder)
        self.browsePSFButton.clicked.connect(self.load_PSF)
        self.browseConfigButton.clicked.connect(self.load_config)
        self.clearButton.clicked.connect(self.clear_plots)

        # self.acqtimeEdit.textChanged.connect(self.emit_param)

        # general GUI layout
        grid = QtWidgets.QGridLayout()
        self.setLayout(grid)
        grid.addWidget(self.paramWidget, 0, 0)
        grid.addWidget(self.fileWidget, 1, 0)
        grid.addWidget(self.dataWidget, 0, 1, 2, 2)

        # param Widget layout
        subgrid = QtWidgets.QGridLayout()
        self.paramWidget.setLayout(subgrid)

        subgrid.addWidget(self.measureButton, 17, 0)
        subgrid.addWidget(self.stopButton, 17, 1)
        subgrid.addWidget(self.clearButton, 18, 1)

        file_subgrid = QtWidgets.QGridLayout()
        self.fileWidget.setLayout(file_subgrid)

        file_subgrid.addWidget(self.filenameEdit, 0, 0, 1, 2)
        file_subgrid.addWidget(self.folderLabel, 1, 0, 1, 2)
        file_subgrid.addWidget(self.folderEdit, 2, 0, 1, 2)
        file_subgrid.addWidget(self.browseFolderButton, 3, 0)
        file_subgrid.addWidget(self.browsePSFButton, 4, 0)
        file_subgrid.addWidget(self.browseConfigButton, 4, 1)

    def closeEvent(self, *args, **kwargs):
        """Handle close event."""
        print("************** cerrando swabian")
        self._backend.close()
        super().closeEvent(*args, **kwargs)


if __name__ == "__main__":

    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication([])
    else:
        app = QtWidgets.QApplication.instance()

    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

    gui = TCSPCFrontend()

    gui.setWindowTitle("Time-correlated single-photon counting with tracking")
    gui.show()
    gui.raise_()
    gui.activateWindow()
    app.exec_()
    # app.quit()
