# -*- coding: utf-8 -*-
"""
Calibra TT Swabian para TCSPC con tracking.

@author: azelcer
"""
from __future__ import annotations
from dataclasses import dataclass as _dataclass
import numpy as _np
import threading as _th
from typing import Callable as _Callable

import TimeTagger as _TimeTagger

# import time as _time
import logging as _lgn
from PyQt5.QtCore import (
    Qt as _Qt,
    pyqtSignal as _psignal,
    pyqtSlot as _pslot,
)


import PyQt5.QtWidgets as _QtWidgets
import PyQt5.QtGui as _QtGui
import pyqtgraph as _pg

import tools.swabiantools as _st
from tools.config_handler import TCSPInstrumentInfo, APDInfo

import mock_shutters as shutter_driver

_lgr = _lgn.getLogger(__name__)
_lgn.basicConfig(level=_lgn.INFO)


# Globals
_APP_NAME = "TCSPC Swabian Calibration"
_SIGNAL_TYPES = [x.name for x in _st.SignalTypeEnum]
_DELAY_LIMIT = 2_000_000  # +- delay limits in ps
_N_SHUTTERS = 4  # be ready


# Threads de ayuda, podrían moverse a otro módulo
class CalibratePeriodThread(_th.Thread):
    """Realiza la calibración en background."""

    def __init__(
        self,
        tagger: _TimeTagger.TimeTagger,
        channel_number: int,
        signal_type: _st.SignalTypeEnum,
        callback_function: _Callable,
        *args,
        **kwargs,
    ):
        """Guarda los datos.

        La función callback tiene que tener la siguiente firma:
            fcn(period: float, data: np.ndarray)
        y recibe todo en None si hubo un error
        """
        super().__init__(*args, **kwargs)
        self.tagger = tagger
        self.channel = channel_number
        self.cb = callback_function
        self.signal_type = signal_type

    def run(self):
        """Lleva a cabo la medida."""
        _lgr.info("Iniciando thread de calibración")
        try:
            period, data = _st.calibrate_period(
                self.tagger,
                self.channel,
                return_data=True,
                debug=True,
            )
        except Exception:
            period, data = None, None
        self.cb(period, data)
        _lgr.info("Fin thread de calibración.")


class CalibratePulseThread(_th.Thread):
    """Realiza la calibración de los pulsos en background."""

    def __init__(
        self,
        tagger: _TimeTagger.TimeTagger,
        laser_channel: int,
        laser_type: _st.SignalTypeEnum,
        APD_channels: list[int],
        APD_types: list[_st.SignalTypeEnum],
        callback_function: _Callable,
        *args,
        **kwargs,
    ):
        """Guarda los datos.

        La función callback tiene que tener la siguiente firma:
            fcn(APC_channel: int, shutter: int, data: np.ndarray, finished: bool)
        y recibe finished en true si es el último
        """
        super().__init__(*args, **kwargs)
        self.tagger = tagger
        self.laser_channel = laser_channel
        self.laser_type = laser_type
        self.APD_channels = APD_channels
        self.APD_types = APD_types
        self.cb = callback_function

    def run(self):
        """Lleva a cabo la medida."""
        _lgr.info("Iniciando thread de calibración de pulsos")
        try:
            for apd_idx, channel in enumerate(self.APD_channels):
                for shutter in range(_N_SHUTTERS):
                    _lgr.info(
                        "Calibrando canal %s, shutter %s", channel, shutter
                    )
                    finished = (
                        channel == self.APD_channels[-1]
                        and shutter == _N_SHUTTERS - 1
                    )
                    # cerrar todos los shutters menos el que toca
                    shutter_driver.set_shutter(
                        shutter, True
                    )  # ver si es True o False
                    data = _st.pulse_delay_calibration(
                        tagger,
                        self.laser_channel,
                        channel,
                        self.laser_type,
                        self.APD_types[apd_idx],
                        debug=shutter * 100 + 175,
                    )
                    shutter_driver.set_shutter(
                        shutter, False
                    )  # ver si es True o False
                    self.cb(channel, shutter, data, finished)
        except Exception as e:
            print("Exceptuamos,", type(e), e, flush=True)
            self.cb(
                self.APD_channels[-1],
                0,
                _np.zeros(
                    (
                        2,
                        2,
                    )
                ),
                True,
            )


@_dataclass
class PulseInfo:
    """Data and graphs about a pulse"""

    class ShutterInfo:
        data: _np.ndarray
        plot: _pg.PlotDataItem
        vline: _pg.InfiniteLine
        label: _QtWidgets.QLabel

    APD: int
    graph: _pg.PlotItem
    label: _QtWidgets.QLabel
    shutter_info: dict[int, ShutterInfo]  # Use default factory


# GUI setup helpers
def _add_graph(parent: _pg.GraphicsLayout, row: int, col: int) -> _pg.PlotItem:
    rv = parent.addPlot(row=row, col=col)
    rv.setLabels(bottom=("Time", "ps"), left=("Intensity", "counts"))
    rv.showGrid(x=True, y=True)
    return rv


def _create_signal_combobox() -> _QtWidgets.QComboBox:
    """Create and fill."""
    cb = _QtWidgets.QComboBox()
    [cb.addItem(st.name, st) for st in _st.SignalTypeEnum]
    return cb


def _create_delay_lineedit(data: str = "") -> _QtWidgets.QLineEdit:
    """Create and fill."""
    le = _QtWidgets.QLineEdit(str(data))
    le.setValidator(_QtGui.QIntValidator(-_DELAY_LIMIT, _DELAY_LIMIT))
    return le


class TCSPCCalibrateFrontend(_QtWidgets.QFrame):
    """Frontend para TCSPC con tracking."""

    _laser_channel_idx: int = None
    _delays: list = []
    _shutters_delays: list = []
    _running_thread: _th.Thread | None = None

    # Calibration data
    _period: float | None = None
    _period_data: _np.ndarray | None
    _pulses_info: dict[int, PulseInfo] = {}
    _line_pulse_map: dict[_pg.InfiniteLine, tuple] = {}

    # self-signals
    period_finished_signal = _psignal()
    pulse_finished_signal = _psignal(int, int, _np.ndarray, bool)

    _intrument_info: TCSPInstrumentInfo | None = None

    def __init__(
        self,
        tagger: _TimeTagger.TimeTagger,
        tt_info: dict,
        instrument_info: TCSPInstrumentInfo | None,
        *args,
        **kwargs,
    ):
        """Inicializa datos y prepara el GUI."""
        super().__init__(*args, **kwargs)
        self._tagger = tagger
        self._channels = tuple(tt_info["channels"])
        self._delays = _st.get_channels_delay(tagger, self._channels)
        self.setup_gui()
        self.setWindowTitle(_APP_NAME)
        self._period_vline = None

        if instrument_info:
            _lgr.info("Using previous instrument info: %s", instrument_info)
            err_str = ""
            if instrument_info.laser_channel not in self._channels:
                err_str += (
                    " - La configuración selecciona un canal de laser"
                    f"inexistente {instrument_info.laser_channel}\n"
                )
            else:
                laser_idx = self._channels.index(instrument_info.laser_channel)
                self._laser_rbuttons[laser_idx].setChecked(True)
                self._period = instrument_info.period
                self._delay_lineedits[laser_idx].setText(str(self._period))
                if instrument_info.laser_signal not in _SIGNAL_TYPES:
                    err_str += (
                        " - La configuración selecciona un tipo de señal de "
                        f"laser inexistente {instrument_info.laser_signal}\n"
                    )
                else:
                    self._signal_type_combos[laser_idx].setCurrentIndex(
                        _SIGNAL_TYPES.index(instrument_info.laser_signal)
                    )
            for APD in instrument_info.APD_info:
                if APD.channel not in self._channels:
                    err_str += (
                        " - La configuración selecciona un canal de "
                        f"APD inexistente {APD.channel}\n"
                    )
                    continue
                if APD.channel == instrument_info.laser_channel:
                    err_str += (
                        " - La configuración selecciona el mismo canal"
                        f"para un APD y el laser {APD.channel}\n"
                    )
                    continue
                if APD.signal_type not in _SIGNAL_TYPES:
                    err_str += (
                        " - La configuración selecciona un tipo de señal "
                        f"inválida para el canal de APD {APD.channel} ({APD.signal_type})\n"
                    )
                    continue
                APD_idx = self._channels.index(APD.channel)
                # setear delay para el APD
                self._APD_chkboxes[APD_idx].setChecked(True)
                self._signal_type_combos[APD_idx].setCurrentIndex(
                    _SIGNAL_TYPES.index(APD.signal_type)
                )
                self._delay_lineedits[APD_idx].setText(str(APD.delay))
            if err_str:
                # TODO: usar messagebox
                print(err_str)

        self.period_finished_signal.connect(self.period_finished)
        self.pulse_finished_signal.connect(self.pulse_finished)

    def setup_gui(self):
        """Prepara el GUI.

        Tiene dos columnas: a la izquierda la seleccion de canales y botones,
        a la derecha los graficos (Y los tiempos?)

        Para cada canal se puede elegir si es el laser (1 sólo), si es APD,
        si es NIM o TTL y el delay.
        """

        def create_label_and_field(parent, label: str, default_value: str):
            """Create label and line fields, and add to parent."""
            label = _QtWidgets.QLabel(str(label))
            rv = _QtWidgets.QLineEdit(str(default_value))
            parent.addWidget(label)
            parent.addWidget(rv)
            return rv

        self.setGeometry(100, 100, 1000, 600)
        self.setWindowTitle("TCSPC")
        self.setWindowIcon(_QtGui.QIcon("images/main_icon.png"))

        # Left column
        self._params_frame = _QtWidgets.QFrame(self)
        self._params_frame.setFrameShape(_QtWidgets.QFrame.StyledPanel)
        param_layout = _QtWidgets.QVBoxLayout()
        self._params_frame.setLayout(param_layout)
        # Channel management
        chan_grid = _QtWidgets.QGridLayout()
        param_layout.addLayout(chan_grid)
        for idx, title in enumerate(
            ("Ch.", "Las.", "APD", "Sgn", "Delay/Period")
        ):
            chan_grid.addWidget(_QtWidgets.QLabel(title), 0, idx)
        self.laser_group = _QtWidgets.QButtonGroup(chan_grid)
        self._laser_rbuttons: list[_QtWidgets.QRadioButton] = [
            _QtWidgets.QRadioButton() for _ in range(len(self._channels))
        ]
        self._APD_chkboxes: list[_QtWidgets.QCheckBox] = [
            _QtWidgets.QCheckBox() for _ in range(len(self._channels))
        ]
        self._signal_type_combos: list[_QtWidgets.QComboBox] = [
            _create_signal_combobox() for _ in range(len(self._channels))
        ]
        self._delay_lineedits: list[_QtWidgets.QLineEdit] = [
            _create_delay_lineedit(str(d)) for d in self._delays
        ]
        for idx, (channel, rbutton, chkbox, combo, lineedit) in enumerate(
            zip(
                self._channels,
                self._laser_rbuttons,
                self._APD_chkboxes,
                self._signal_type_combos,
                self._delay_lineedits,
            )
        ):
            chan_grid.addWidget(_QtWidgets.QLabel(str(channel)), idx + 1, 0)
            self.laser_group.addButton(rbutton, id=idx)
            chan_grid.addWidget(rbutton, idx + 1, 1)
            chan_grid.addWidget(chkbox, idx + 1, 2)
            chan_grid.addWidget(combo, idx + 1, 3)
            chan_grid.addWidget(lineedit, idx + 1, 4)
        self.laser_group.idToggled.connect(self._laser_rb_changed)

        if self._laser_rbuttons:
            self._laser_rbuttons[0].setChecked(True)

        # TCSPC parameters labels and edits
        # acqtime_label = _QtWidgets.QLabel("Acquisition time [s]")
        # self.acq_time_tb = _QtWidgets.QLineEdit("1.0")
        # param_layout.addWidget(acqtime_label)
        # param_layout.addWidget(self.acq_time_tb)
        param_layout.addStretch(1)
        self._calibrate_button = _QtWidgets.QPushButton("Calibrate Period")
        param_layout.addWidget(self._calibrate_button)
        self._calibrate_button.clicked.connect(self._calibrate_period)
        self._pulses_button = _QtWidgets.QPushButton("Calibrate Pulses")
        param_layout.addWidget(self._pulses_button)
        self._pulses_button.clicked.connect(self._calibrate_pulses)
        self._delay_button = _QtWidgets.QPushButton("Use pulse delays")
        param_layout.addWidget(self._delay_button)
        self._delay_button.clicked.connect(self.use_pulse_delays)
        self._save_config = _QtWidgets.QPushButton("Save configuration")
        param_layout.addWidget(self._save_config)
        self._save_config.clicked.connect(self.save_config)

        # Right column: widget to display data and delays
        self._right_column_frame = _QtWidgets.QFrame(self)
        self._right_column_frame.setFrameShape(_QtWidgets.QFrame.StyledPanel)
        rframe_layout = _QtWidgets.QVBoxLayout()
        self._right_column_frame.setLayout(rframe_layout)
        self._data_widget = _pg.GraphicsLayoutWidget()
        self._data_widget.setAntialiasing(True)
        rframe_layout.addWidget(self._data_widget)
        # stacked graphs: top one for the period and the others for APDs
        self._data_widget.period = _add_graph(self._data_widget, 0, 0)
        self.period_plot: _pg.PlotDataItem = self._data_widget.period.plot(
            pen="r",
            width=140,
        )
        rframe_layout.addWidget(self._data_widget)

        # Delays textboxes
        self._pulse_delay_grid = _QtWidgets.QGridLayout()
        rframe_layout.addLayout(self._pulse_delay_grid)
        self._pulse_delay_grid.addWidget(_QtWidgets.QLabel("APD Ch.#"), 0, 0)
        for idx in range(_N_SHUTTERS):
            self._pulse_delay_grid.addWidget(
                _QtWidgets.QLabel(f"Shutter {idx+1}"), 0, idx + 1
            )
        # self._pulse_delay_texts: list[_QtWidgets.QLineEdit] = []

        hbox = _QtWidgets.QHBoxLayout(self)
        splitter = _QtWidgets.QSplitter(_Qt.Horizontal)
        splitter.addWidget(self._params_frame)
        splitter.addWidget(self._right_column_frame)
        hbox.addWidget(splitter)
        self.setLayout(hbox)

    def _get_edited_delays(self) -> list[int]:
        """Returns all the delays from the edit boxes"""
        return [int(le.text()) for le in self._delay_lineedits]

    @_pslot(bool)
    def use_pulse_delays(self):
        """Sets textboxes according to measurements.

        May give weird resukts if APD boxes selection change
        """
        self._analize_pulses(True)

    def _get_APD_idx(self) -> list[int]:
        """Devuelve el indice de los canales seleccionados como APD."""
        return [
            idx
            for idx in range(len(self._channels))
            if self._APD_chkboxes[idx].isChecked()
        ]

    def _set_channels_delays(self):
        """Sets delays according to textboxes, only for selected channels."""
        # Quedó medio horrible
        all_delays = self._get_edited_delays()
        laser_channel = self._get_laser_channel()
        settings = []
        for idx, channel in enumerate(self._channels):
            chkbox = self._APD_chkboxes[idx]
            # no need to check for enabled
            if (
                chkbox.isChecked() and chkbox.isEnabled()
            ) or channel == laser_channel:
                settings.append((channel, -all_delays[idx]))  # Check sign
        _st.set_channels_delay(tagger, settings)

    def _reset_pulse_data(self):
        """Erase data and graphs associated with pulses"""
        for chan, pi in self._pulses_info.items():
            for sh, shi in pi.shutter_info.items():
                pi.graph.removeItem(shi.vline)
                pi.graph.removeItem(shi.plot)
                self._pulse_delay_grid.removeWidget(shi.label)
                # pi.label.setParent(None)
                shi.label.deleteLater()
                shi.vline.deleteLater()
                shi.plot.deleteLater()
            self._data_widget.removeItem(pi.graph)
            pi.graph.deleteLater()
            self._pulse_delay_grid.removeWidget(pi.label)
            # pi.label.setParent(None)
            pi.label.deleteLater()
        self._pulses_info.clear()
        self._line_pulse_map.clear()

    @_pslot(int, bool)
    def _laser_rb_changed(self, buttonid: int, status: bool):
        """Manage laser channel selection change.

        Disable or enable APD selection box, select signal type for convenience

        TODO: ver si dejar que cambie todos o sólo el del laser

        Parameters
        ----------
        buttonid : int
            id of the button. Zero based index of the channel in the list.
        status : bool
            new RB status.
        """
        if status:
            self._APD_chkboxes[buttonid].setChecked(False)
        self._APD_chkboxes[buttonid].setEnabled(not status)
        for idx, combo in enumerate(self._signal_type_combos):
            combo.setCurrentIndex(
                _SIGNAL_TYPES.index(
                    _st.SignalTypeEnum.NIM.name
                    if idx == buttonid
                    else _st.SignalTypeEnum.TTL.name
                )
            )

    def _get_laser_channel(self) -> int:
        """Devuelve el nro de canal seleccionado para el laser."""
        lsr_idx = self.laser_group.checkedId()
        return self._channels[lsr_idx]

    def _get_laser_type(self) -> _st.SignalTypeEnum:
        """Devuelve el tipo de señal seleccionada para el laser."""
        lsr_idx = self.laser_group.checkedId()
        return self._signal_type_combos[lsr_idx].currentData()

    def _get_APD_channels(self) -> list[int]:
        """Devuelve la lista de canales seleccionados para APD."""
        APD_channels = [
            self._channels[idx]
            for idx, chkbox in enumerate(self._APD_chkboxes)
            if chkbox.isChecked() and chkbox.isEnabled()
        ]
        return APD_channels

    def _get_APD_types(self) -> list[int]:
        """Devuelve la lista tipos para los canales seleccionados para APD."""
        APD_signal_types = [
            self._signal_type_combos[idx].currentData()
            for idx, chkbox in enumerate(self._APD_chkboxes)
            if chkbox.isChecked() and chkbox.isEnabled()
        ]
        return APD_signal_types

    @_pslot(bool)
    def _calibrate_period(self, pushed: bool):
        """Handle "Period calibration" button press."""
        channel_number = self._get_laser_channel()
        laser_type = self._get_laser_type()
        self._running_thread = CalibratePeriodThread(
            self._tagger, channel_number, laser_type, self.period_finished_cb
        )
        self._running_thread.start()
        self._set_buttons_state(False)

    def _set_buttons_state(self, state: bool):
        """Enable or disable all buttons.

        Convenience function to disable all the buttons during measurements and
        reenable them after finishing.
        """
        self._params_frame.setEnabled(state)

    def period_finished_cb(self, period: float, data: _np.ndarray):
        """Callback for period measurement thread.

        Sets internal data and emits signal.
        """
        self._period = int(period) if period else None
        self._period_data = data
        self.period_finished_signal.emit()

    @_pslot()
    def period_finished(self):
        """Handle end of period measurement."""
        self._set_buttons_state(True)
        self._running_thread.join()
        self._running_thread = None
        if self._period is None:
            _QtWidgets.QMessageBox.warning(
                self,
                _APP_NAME,
                f"""There was an error calibrating the period.
Please check that the laser is turned on,
that the proper channel # has been selected({self._get_laser_channel()}),
and that the cables are properly connected.""",
            )
            return
        laser_channel = self._get_laser_channel()
        self.period_plot.setData(self._period_data[0], self._period_data[1])
        laser_idx = self.laser_group.checkedId()
        self._delay_lineedits[laser_idx].setText(str(int(self._period)))
        # TODO:  guardar period en configuración
        if self._period_vline:
            self._data_widget.period.removeItem(self._period_vline)
            self._period_vline = None
        self._period_vline = _pg.InfiniteLine(pos=self._period, movable=True)
        self._data_widget.period.addItem(self._period_vline)
        self._period_vline.sigPositionChanged.connect(self._period_changed)
        _lgr.info(
            "New calibrated period for channel %s: %s ps",
            laser_channel,
            self._period,
        )

    @_pslot(bool)
    def _calibrate_pulses(self, pushed: bool):
        """Process "Calibrate Pulses" button push."""
        self._reset_pulse_data()
        APD_channels = self._get_APD_channels()
        if not APD_channels:
            _lgr.info("No channels to calibrate")
            return
        _lgr.debug("Calibrando APDs en canales %s", APD_channels)
        self._set_channels_delays()
        laser_channel = self._get_laser_channel()
        self._running_thread = CalibratePulseThread(
            self._tagger,
            laser_channel,
            self._get_laser_type(),
            APD_channels,
            self._get_APD_types(),
            self.pulse_finished_cb,
        )
        self._running_thread.start()
        self._set_buttons_state(False)

    def pulse_finished_cb(
        self, APC_channel: int, shutter: int, data: _np.ndarray, finished: bool
    ):
        """Callback for pulse measurement thread.

        Sets internal data and emits signal.
        """
        self.pulse_finished_signal.emit(APC_channel, shutter, data, finished)

    @_pslot(int, int, _np.ndarray, bool)
    def pulse_finished(
        self, APD_channel: int, shutter: int, data: _np.ndarray, finished: bool
    ):
        """Procesar cada calibración (chequeando si es la última)."""
        _lgr.debug("recibimos data de APD %s", APD_channel)
        if finished:  # acá por si hay una excepción
            self._set_buttons_state(True)
            self._running_thread.join()
            self._running_thread = None
        # TODO: Aca eliminar cosas si no hay data (porque el APD no tiene nada conectado)
        apd_data = self._pulses_info.get(APD_channel)
        if not apd_data:
            apd_data = PulseInfo(
                APD_channel,
                _add_graph(self._data_widget, len(self._pulses_info) + 1, 0),
                _QtWidgets.QLabel(str(APD_channel)),
                {},
            )
            self._pulses_info[APD_channel] = apd_data
            self._pulse_delay_grid.addWidget(
                apd_data.label, len(self._pulses_info), 0
            )
        # poner data, analizar y poner vline y llenar textbox
        shutter_info = apd_data.shutter_info[shutter] = PulseInfo.ShutterInfo()
        shutter_info.data = data
        pulse_delay = data[0][_np.argmax(data[1])]
        new_plot = apd_data.graph.plot(  # pg.BarGraphItem(x=data[0], height=data[1], width=2, brush="#008a19")
            data[0], data[1], pen=shutter, width=140
        )
        shutter_info.plot = new_plot
        vline = _pg.InfiniteLine(
            pos=pulse_delay,
            movable=True,
            pen=shutter,
        )
        shutter_info.vline = vline
        apd_data.graph.addItem(vline)
        self._line_pulse_map[vline] = (
            APD_channel,
            shutter,
        )  # Ver si no usar los info
        shutter_info.label = _QtWidgets.QLabel(str(pulse_delay))
        self._pulse_delay_grid.addWidget(
            shutter_info.label, len(self._pulses_info), shutter + 1
        )
        vline.sigPositionChanged.connect(self._pulse_changed)
        if finished:
            self._analize_pulses()

    @_pslot(object)
    def _period_changed(self, line: _pg.InfiniteLine):
        """Handle user movement of a period line."""
        self._period = int(line.value())
        laser_idx = self.laser_group.checkedId()
        self._delay_lineedits[laser_idx].setText(str(int(self._period)))

    @_pslot(object)
    def _pulse_changed(self, line: _pg.InfiniteLine):
        """Handle user movement of a pulse start line."""
        APD_chan, shutter = self._line_pulse_map[line]
        pi = self._pulses_info[APD_chan]
        pi.shutter_info[shutter].label.setText(f"{int(line.value())}")

    def _analize_pulses(self, update: bool = False):
        """Analiza los pulsos.

        Calcula el shift a introducir en cada APD, el tiempo de inicio de la
        señal correspondiente a cada shutter, y el orden en el que llegan
        las señales de los shutters.
        """
        pulses_delays = _np.array(
            [
                [
                    int(shi.vline.value())
                    for sh, shi in chdata.shutter_info.items()
                ]
                for chan, chdata in self._pulses_info.items()
            ]
        )
        if pulses_delays.size == 0:
            _lgr.warning("No pulses measured")
            return
        sorted_shutters = _np.argsort(
            pulses_delays,
        )
        _lgr.info("Orden shutters: %s", sorted_shutters)
        if not _np.all(_np.ptp(sorted_shutters, axis=0) == 0):
            _lgr.warning("Shutter delay ordering is not the same for all APDs")
        chan_min, shut_min = _np.unravel_index(
            _np.argmin(pulses_delays), pulses_delays.shape
        )
        min_delay = pulses_delays[chan_min, shut_min]
        _lgr.info("The minimum delay is %s, on chanel idx %s, shutter %s",
                  min_delay, chan_min, shut_min)
        print("Average intershutter delays")
        deltas = _np.diff(pulses_delays)
        print(_np.average(deltas, axis=0))
        print(_np.std(deltas, axis=0))
        proposed_delays = pulses_delays[
            _np.arange(pulses_delays.shape[0]), sorted_shutters[:, 0]
        ]
        print("propongo meter delays de ", proposed_delays)
        print(
            "con lo que los tiempos de shutters quedarían de ",
            _np.average(pulses_delays - proposed_delays[:, None], axis=0),
        )
        if update:
            used_delays = _st.get_channels_delay(self._tagger, self._channels)
            for APD_channel, delay in zip(self._pulses_info, proposed_delays):
                APD_idx = self._channels.index(APD_channel)
                self._delay_lineedits[APD_idx].setText(
                    str(int(delay - used_delays[APD_idx]))
                )
            # Actualizar delays shutters
            self._shutters_delays = _np.mean(
                pulses_delays - proposed_delays[:, None], axis=0, dtype=int,
            ).tolist()

    @_pslot(bool)
    def save_config(self):
        """Save configuration.

        TODO: si miden y cambian los checkboxes hacemos cualquier cosa
        """
        if not self._period:
            _lgr.error("No period to save")
            return
        if self._shutters_delays is None:
            _lgr.error("No shutter delays to save")
            return
        all_delays = self._get_edited_delays()
        delays = [all_delays[i] for i in self._get_APD_idx()]
        APD_info = [
            APDInfo(chan, delay, st.name)
            for chan, delay, st in zip(
                self._get_APD_channels(), delays, self._get_APD_types()
            )
        ]
        info = TCSPInstrumentInfo(
            self._tagger.getSerial(),
            self._get_laser_channel(),
            self._get_laser_type().name,
            self._period,
            self._shutters_delays,
            APD_info,
        )
        print(info)
        info.save()


if __name__ == "__main__":
    tt_data = _st.get_tt_info()
    if not tt_data:
        print("   ******* Enchufá el equipo *******")
        raise ValueError("POR FAVOR ENCHUFA EL EQUIPO")
    IInfo = None
    try:
        IInfo = TCSPInstrumentInfo.load()
        serial = IInfo.serial
    except FileNotFoundError:
        _lgr.info("No configuration file found")
        serial = list(tt_data.keys())[0]
    if not (serial in list(tt_data.keys())):
        _lgr.warning(
            "The configuration file is for a time tagger with a "
            "different serial number: will use the first one instead."
        )
        serial = list(tt_data.keys())[0]
    _lgr.info(
        "%s TimeTaggers found. Using the one with with S#%s",
        len(tt_data),
        serial,
    )
    tt_info = tt_data[serial]
    with _TimeTagger.createTimeTagger() as tagger:
        app = _QtWidgets.QApplication([])
        ex = TCSPCCalibrateFrontend(tagger, tt_info, IInfo)
        ex.show()
        ex.raise_()
        ex.activateWindow()
        app.exec_()
