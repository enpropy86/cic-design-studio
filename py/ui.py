import os
import sys
import math
import json
import time
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton, QButtonGroup,
    QFrame, QSplitter, QScrollArea, QDialog, QTextEdit, QTextBrowser,
    QSizePolicy, QFileDialog, QMessageBox, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QMouseEvent

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

import matplotlib
matplotlib.use('QtAgg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False 

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

# User defined modules
try:
    from src_generator import CICCodeGenerator
    from fir_calc import calculate_fir_params, analyze_response_wide, calc_cic_growth, estimate_fpga_resource, get_useful_band_edge
except ImportError:
    pass

try:
    from tb_generator import generate_testbench
    HAS_TB_GEN = True
except ImportError:
    HAS_TB_GEN = False

try:
    from llm_helper import LLMHelper
    HAS_LLM = True
except ImportError:
    HAS_LLM = False

try:
    from agent_core import DesignAgent
    from agent_tools import TOOL_REGISTRY
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False


# ==============================================================================
# Light Theme & Style Configuration (Claude Code / Modern Web Style)
# ==============================================================================
THEME = {
    'bg':           '#f0eeeb',      # 暖石灰背景
    'surface':      '#faf9f7',      # 暖白卡片
    'input':        '#e8e6e1',      # 暖灰输入框
    'accent':       '#c8724c',      # 柔和赭橙
    'accent_hover': '#b5623e',      # 深赭橙 hover
    'text':         '#2d2a26',      # 暖深灰文字
    'subtext':      '#7a756d',      # 暖中灰副文字
    'border':       '#d6d2cc',      # 暖灰边框
    'success':      '#5a9e6f',      # 柔和绿
    'error':        '#c75a4a',      # 柔和红
    'code_bg':      '#2b2926',      # 暖深色代码背景
    'code_fg':      '#d4cfc8',      # 暖白代码文字
}

GLOBAL_STYLESHEET = f"""
QWidget {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    color: {THEME['text']};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {THEME['bg']};
}}
QFrame#Card {{
    background-color: {THEME['surface']};
    border: 1px solid {THEME['border']};
    border-radius: 8px;
}}
QFrame#Header {{
    background-color: {THEME['surface']};
    border-bottom: 1px solid {THEME['border']};
}}
QLineEdit, QComboBox, QTextEdit, QAbstractSpinBox {{
    background-color: {THEME['input']};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px;
    color: {THEME['text']};
    selection-background-color: {THEME['accent']};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {THEME['accent']};
    background-color: {THEME['surface']};
}}
QLineEdit[error="true"] {{
    border: 1px solid {THEME['error']};
}}
QPushButton {{
    background-color: {THEME['surface']};
    border: 1px solid {THEME['border']};
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
    color: {THEME['text']};
}}
QPushButton:hover {{
    background-color: {THEME['input']};
    border: 1px solid {THEME['accent']};
    color: {THEME['text']};
}}
QPushButton:pressed {{
    background-color: {THEME['input']};
    border: 1px solid {THEME['accent']};
    color: {THEME['text']};
}}
QPushButton#AccentButton, QPushButton#AIAssistantBtn {{
    background-color: {THEME['accent']};
    color: #ffffff;
    border: none;
}}
QPushButton#AccentButton:hover, QPushButton#AIAssistantBtn:hover {{
    background-color: {THEME['accent_hover']};
    color: #ffffff;
}}
QPushButton#AccentButton:pressed, QPushButton#AIAssistantBtn:pressed {{
    background-color: {THEME['accent_hover']};
    border: 1px solid {THEME['accent']};
    color: #ffffff;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QSplitter::handle {{
    background-color: {THEME['border']};
}}
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #d1d5db;
    min-height: 20px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: #9ca3af;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
}}
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {THEME['border']};
    border-radius: 3px;
    background-color: {THEME['surface']};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1px solid {THEME['accent']};
    background-color: #eef2ff;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {THEME['accent']};
    border: 1px solid {THEME['accent_hover']};
}}
QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{
    background-color: {THEME['accent_hover']};
    border: 1px solid {THEME['accent']};
}}
QComboBox QAbstractItemView {{
    background-color: {THEME['surface']};
    color: {THEME['text']};
    selection-background-color: {THEME['accent']};
    selection-color: white;
    border: 1px solid {THEME['border']};
    outline: none;
    padding: 2px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
"""


# ==============================================================================
# UI Helper Widgets
# ==============================================================================
class Card(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        
        # Title
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {THEME['text']};")
        self._layout.addWidget(title_lbl)
        
        # Separator
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {THEME['border']};")
        self._layout.addWidget(line)
        
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(10)
        self._layout.addLayout(self.content_layout)

    def add_widget(self, widget):
        self.content_layout.addWidget(widget)

    def add_layout(self, layout):
        self.content_layout.addLayout(layout)


class InputRow(QWidget):
    def __init__(self, label_text, default_val, unit="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel(label_text)
        self.label.setFixedWidth(140)
        self.label.setStyleSheet(f"color: {THEME['subtext']};")
        
        self.input_field = QLineEdit(str(default_val))
        self.input_field.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        lay.addWidget(self.label)
        lay.addWidget(self.input_field)
        if unit:
            self.unit_label = QLabel(unit)
            self.unit_label.setStyleSheet(f"color: {THEME['subtext']};")
            self.unit_label.setFixedWidth(40)
            lay.addWidget(self.unit_label)

    def text(self):
        return self.input_field.text()
        
    def set_text(self, text):
        self.input_field.setText(str(text))


# ==============================================================================
# Thread-safe Signal Handler
# ==============================================================================
class WorkerSignals(QObject):
    success = pyqtSignal(object, bool)   # result, is_agent
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    step_update = pyqtSignal(object)     # AgentStep


# ==============================================================================
# Collapsible Section Widget (for Agent thinking visualization)
# ==============================================================================
class CollapsibleSection(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._toggle_btn = QPushButton(f"▶ {title}")
        self._toggle_btn.setStyleSheet(f"text-align: left; border: none; color: {THEME['subtext']}; font-size: 12px; padding: 4px 0;")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        lay.addWidget(self._toggle_btn)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 4, 0, 4)
        self._content_layout.setSpacing(4)
        self._content.hide()
        lay.addWidget(self._content)
        self._title = title
        self._expanded = False

    def _toggle(self):
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{arrow} {self._title}")

    def add_widget(self, w):
        self._content_layout.addWidget(w)


# ==============================================================================
# Parameter Suggestion Dialog (B1)
# ==============================================================================
class ParamSuggestDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("参数推荐向导")
        self.setFixedWidth(420)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.result_text = None
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        lay.addWidget(QLabel("请填写您的设计需求:"))

        fs_in_lay = QHBoxLayout()
        fs_in_lay.addWidget(QLabel("输入采样率"))
        self.inp_fs_in = QLineEdit("48")
        self.inp_fs_in.setAlignment(Qt.AlignmentFlag.AlignRight)
        fs_in_lay.addWidget(self.inp_fs_in)
        self.cmb_fs_in_unit = QComboBox()
        self.cmb_fs_in_unit.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.cmb_fs_in_unit.setCurrentIndex(1)
        fs_in_lay.addWidget(self.cmb_fs_in_unit)
        lay.addLayout(fs_in_lay)

        fs_out_lay = QHBoxLayout()
        fs_out_lay.addWidget(QLabel("目标采样率"))
        self.inp_fs_out = QLineEdit("8")
        self.inp_fs_out.setAlignment(Qt.AlignmentFlag.AlignRight)
        fs_out_lay.addWidget(self.inp_fs_out)
        self.cmb_fs_out_unit = QComboBox()
        self.cmb_fs_out_unit.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.cmb_fs_out_unit.setCurrentIndex(1)
        fs_out_lay.addWidget(self.cmb_fs_out_unit)
        lay.addLayout(fs_out_lay)

        bw_lay = QHBoxLayout()
        bw_lay.addWidget(QLabel("信号带宽 (可选)"))
        self.inp_bw = QLineEdit("")
        self.inp_bw.setPlaceholderText("留空则自动")
        self.inp_bw.setAlignment(Qt.AlignmentFlag.AlignRight)
        bw_lay.addWidget(self.inp_bw)
        self.cmb_bw_unit = QComboBox()
        self.cmb_bw_unit.addItems(["Hz", "kHz", "MHz"])
        self.cmb_bw_unit.setCurrentIndex(1)
        bw_lay.addWidget(self.cmb_bw_unit)
        lay.addLayout(bw_lay)

        plat_lay = QHBoxLayout()
        plat_lay.addWidget(QLabel("目标平台"))
        self.cmb_platform = QComboBox()
        self.cmb_platform.addItems(["Xilinx", "Altera", "ASIC", "General"])
        plat_lay.addWidget(self.cmb_platform)
        lay.addLayout(plat_lay)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        ok_btn = QPushButton("生成推荐")
        ok_btn.setObjectName("AccentButton")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)
        btn_lay.addWidget(ok_btn)
        lay.addLayout(btn_lay)

    def _on_ok(self):
        fs_in = f"{self.inp_fs_in.text()} {self.cmb_fs_in_unit.currentText()}"
        fs_out = f"{self.inp_fs_out.text()} {self.cmb_fs_out_unit.currentText()}"
        bw = self.inp_bw.text().strip()
        platform = self.cmb_platform.currentText()
        prompt = f"我需要将采样率从 {fs_in} 转换到 {fs_out}"
        if bw:
            prompt += f"，信号带宽约 {bw} {self.cmb_bw_unit.currentText()}"
        prompt += f"，目标平台为 {platform}。请综合推荐完整的结构方案包含架构模式(纯CIC还是CIC+FIR)以及适用的FIR结构(并联/串联/DA可选)，并提供所有的滤波参数配置。"
        self.result_text = prompt
        self.accept()


# ==============================================================================
# Design Compare Dialog (B4)
# ==============================================================================
class CompareDialog(QDialog):
    def __init__(self, current_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle("方案对比")
        self.setFixedWidth(380)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.result_text = None
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        lay.addWidget(QLabel("当前方案 A 已从界面读取。请输入方案 B:"))

        self.inp_r = InputRow("R (倍率)", current_params.get('ratio', 32))
        self.inp_n = InputRow("N (级数)", current_params.get('stages', 4))
        self.inp_m = InputRow("M (延迟)", current_params.get('delay', 1))
        self.inp_taps = InputRow("FIR Taps", current_params.get('fir_taps', 21))
        for w in [self.inp_r, self.inp_n, self.inp_m, self.inp_taps]:
            lay.addWidget(w)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        ok_btn = QPushButton("开始对比")
        ok_btn.setObjectName("AccentButton")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)
        btn_lay.addWidget(ok_btn)
        lay.addLayout(btn_lay)

    def _on_ok(self):
        r = self.inp_r.text()
        n = self.inp_n.text()
        m = self.inp_m.text()
        taps = self.inp_taps.text()
        self.result_text = f"请对比当前设计（方案A）与方案B（R={r}, N={n}, M={m}, FIR Taps={taps}）的优劣，包括位宽增长、资源占用、频率响应等维度。"
        self.accept()


# ==============================================================================
# Session History Dialog (B5)
# ==============================================================================
class SessionHistoryDialog(QDialog):
    def __init__(self, sessions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("历史会话")
        self.setFixedSize(450, 350)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.selected_name = None
        lay = QVBoxLayout(self)

        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        self.list_w = QListWidget()
        for s in sessions:
            item = QListWidgetItem(f"{s['name']}  ({s['count']} 条消息)  {s['timestamp']}")
            item.setData(Qt.ItemDataRole.UserRole, s['name'])
            self.list_w.addItem(item)
        lay.addWidget(self.list_w)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        load_btn = QPushButton("加载")
        load_btn.setObjectName("AccentButton")
        load_btn.clicked.connect(self._on_load)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)
        btn_lay.addWidget(load_btn)
        lay.addLayout(btn_lay)

    def _on_load(self):
        item = self.list_w.currentItem()
        if item:
            self.selected_name = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


# ==============================================================================
# AI Assistant Dialog (Modern Web / Claude Code Style)
# ==============================================================================
class AIAssistantDialog(QDialog):
    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.app = parent_app
        self.setWindowTitle("AI 助手 (Agent)")
        self.resize(800, 850)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        
        self.signals = WorkerSignals()
        self.signals.success.connect(self._on_chat_success)
        self.signals.error.connect(self._on_chat_error)
        self.signals.progress.connect(self._update_typing_status)
        self.signals.step_update.connect(self._on_step_update)

        # AI Engine Init
        self.helper = LLMHelper() if HAS_LLM else None
        if HAS_AGENT and self.helper and self.helper.is_configured():
            self.agent = DesignAgent(
                llm=self.helper, tools=TOOL_REGISTRY,
                on_progress=self._on_agent_progress,
                on_step=self._on_agent_step
            )
        else:
            self.agent = None

        self._build_ui()
        
        if not self.helper or not self.helper.is_configured():
            self._add_system_message("⚠️ AI 引擎未就绪 (未找到配置)。")
        else:
            mode_text = "Agent (工具调用模式)" if self.agent else "基础对话模式"
            self._add_system_message(f"AI Assistant 就绪。当前模式: {mode_text}\n您可以询问设计建议、解释参数，或让 AI 为您配置系统。")

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Header ----
        header = QFrame()
        header.setFixedHeight(56)
        header.setObjectName("Header")
        ht_layout = QHBoxLayout(header)
        ht_layout.setContentsMargins(20, 0, 20, 0)
        
        title_lbl = QLabel("AI 设计助手")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {THEME['text']};")
        ht_layout.addWidget(title_lbl)
        
        badge_lbl = QLabel("AGENT" if self.agent else "BASIC")
        badge_lbl.setStyleSheet(f"background: {THEME['input']}; color: {THEME['subtext']}; padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;")
        ht_layout.addWidget(badge_lbl)
        ht_layout.addStretch()
        
        clear_btn = QPushButton("清空对话")
        clear_btn.clicked.connect(self._clear_chat)
        ht_layout.addWidget(clear_btn)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_session)
        ht_layout.addWidget(save_btn)

        history_btn = QPushButton("历史")
        history_btn.clicked.connect(self._load_session)
        ht_layout.addWidget(history_btn)
        
        main_layout.addWidget(header)

        # ---- Quick Actions ----
        quick_bar = QFrame()
        quick_bar.setStyleSheet(f"background: {THEME['bg']}; color: {THEME['text']};")
        q_layout = QHBoxLayout(quick_bar)
        q_layout.setContentsMargins(20, 10, 20, 10)
        
        actions = [
            ("解释参数", self._quick_explain),
            ("一键诊断", self._quick_diagnose),
            ("参数建议", self._quick_suggest),
            ("对比方案", self._quick_compare),
            ("验证脚本", self._quick_matlab),
        ]
        for t, c in actions:
            qb = QPushButton(t)
            qb.setStyleSheet(f"background: {THEME['surface']}; border: 1px solid {THEME['border']}; font-size: 13px; color: {THEME['text']}; border-radius:15px; padding: 6px 14px;")
            qb.clicked.connect(c)
            qb.setCursor(Qt.CursorShape.PointingHandCursor)
            q_layout.addWidget(qb)
        q_layout.addStretch()
        main_layout.addWidget(quick_bar)

        # ---- Chat History Area ----
        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setStyleSheet(f"background: {THEME['surface']}; border: none;")
        
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet(f"background: {THEME['surface']};")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(20, 20, 20, 20)
        self.chat_layout.setSpacing(16)
        self.chat_layout.addStretch() 
        
        self.chat_area.setWidget(self.chat_container)
        main_layout.addWidget(self.chat_area, 1)

        # ---- Input Area ----
        input_frame = QFrame()
        input_frame.setStyleSheet(f"background: {THEME['surface']}; border-top: 1px solid {THEME['border']}; padding: 10px;")
        inf_layout = QVBoxLayout(input_frame)
        inf_layout.setContentsMargins(10, 5, 10, 10)
        
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("描述您的需求... (Shift+Enter 换行)")
        self.input_edit.setFixedHeight(80)
        self.input_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {THEME['input']}; border: 1px solid transparent; border-radius: 8px; font-size: 14px; padding: 10px; color: {THEME['text']};
            }}
            QTextEdit:focus {{ border: 1px solid {THEME['accent']}; background-color: {THEME['surface']}; }}
            QTextEdit[placeholderText] {{ color: {THEME['subtext']}; }}
        """)
        self.input_edit.installEventFilter(self)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.send_btn = QPushButton("发送  ↑")
        self.send_btn.setObjectName("AccentButton")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self.send_btn)
        
        inf_layout.addWidget(self.input_edit)
        inf_layout.addLayout(btn_layout)
        
        main_layout.addWidget(input_frame)
        
        self._typing_widget = None

    def eventFilter(self, obj, event):
        if obj == self.input_edit and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and not event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_agent_progress(self, step, total, status):
        self.signals.progress.emit(f"🟢 **{status}** ({step}/{total})")

    def _scroll_to_bottom(self):
        def _do_scroll():
            sb = self.chat_area.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())
        QTimer.singleShot(50, _do_scroll)

    def _add_message_widget(self, widget):
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, widget)
        self._scroll_to_bottom()

    def _add_system_message(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {THEME['subtext']}; font-size: 13px; text-align: center;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._add_message_widget(lbl)

    def _add_user_message(self, text):
        frame = QFrame()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch()
        
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setStyleSheet(f"background: #f3f4f6; color: {THEME['text']}; padding: 12px 16px; border-radius: 12px; font-size: 14px; max-width: 500px;")
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        lay.addWidget(bubble)
        self._add_message_widget(frame)

    def _add_ai_message(self, html_content, raw_blocks=None, source_text=None):
        frame = QFrame()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        
        # Parse styles via Qt rich text engine limits, using CSS classes
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(f"""
            QTextBrowser {{ border: none; background: transparent; font-size: 14px; color: {THEME['text']}; }}
            code {{ background: {THEME['code_bg']}; color: {THEME['code_fg']}; padding: 2px 4px; border-radius: 4px; font-family: Consolas, monospace; }}
            pre {{ background: {THEME['code_bg']}; color: {THEME['code_fg']}; padding: 12px; border-radius: 6px; font-family: Consolas, monospace; }}
            a {{ color: {THEME['accent']}; text-decoration: none; }}
        """)
        browser.setHtml(html_content)
        browser.setMinimumHeight(30)
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        # Auto-resize QTextBrowser height
        def resize_browser(b=browser):
            doc = b.document()
            if doc is not None:
                doc_height = int(doc.size().height())
                b.setFixedHeight(doc_height + 15)

        doc = browser.document()
        if doc is not None:
            layout = doc.documentLayout()
            if layout is not None:
                layout.documentSizeChanged.connect(lambda _: resize_browser())
        # Call it once slightly delayed to ensure rendering
        QTimer.singleShot(10, resize_browser)
        
        lay.addWidget(browser)
        
        message_text = source_text or html_content
        raw_blocks = raw_blocks or []
        params_dict = self._find_apply_params(message_text, raw_blocks)
        has_param_block = any(self._looks_like_param_block(code) for _lang, code in raw_blocks)

        # Add quick action buttons for code blocks / inferred parameter sets
        if raw_blocks or params_dict is not None:
            btn_lay = QHBoxLayout()
            for lang, code in raw_blocks:
                copy_btn = QPushButton(f"复制代码 ({lang})")
                copy_btn.setStyleSheet("background: #f3f4f6; border: 1px solid #e5e7eb; font-size: 12px; padding: 4px 8px;")
                copy_btn.clicked.connect(lambda _, c=code, b=copy_btn: self._copy_code(c, b))
                btn_lay.addWidget(copy_btn)
            
            # Application hook (if LLM returned apply_params style dictionary)
            try:
                if params_dict is not None:
                    if 'alternatives' in params_dict and 'balanced' in params_dict['alternatives']:
                        alts = params_dict['alternatives']
                        b_btn = QPushButton("应用: 均衡建议")
                        b_btn.setObjectName("AccentButton")
                        b_btn.clicked.connect(lambda _, p=alts.get('balanced', params_dict): self._apply_params_to_ui(p))
                        btn_lay.addWidget(b_btn)

                        lr_btn = QPushButton("应用: 极致资源")
                        lr_btn.clicked.connect(lambda _, p=alts.get('low_resource', params_dict): self._apply_params_to_ui(p))
                        btn_lay.addWidget(lr_btn)

                        hp_btn = QPushButton("应用: 极致性能")
                        hp_btn.clicked.connect(lambda _, p=alts.get('high_performance', params_dict): self._apply_params_to_ui(p))
                        btn_lay.addWidget(hp_btn)
                    else:
                        apply_btn = QPushButton("应用此参数")
                        apply_btn.setObjectName("AccentButton")
                        apply_btn.clicked.connect(lambda _, p=params_dict: self._apply_params_to_ui(p))
                        btn_lay.addWidget(apply_btn)
                elif has_param_block:
                    apply_btn = QPushButton("应用此参数")
                    apply_btn.setObjectName("AccentButton")
                    apply_btn.clicked.connect(lambda _, t=message_text, b=raw_blocks: self._apply_message_params(t, b))
                    btn_lay.addWidget(apply_btn)
            except Exception as e:
                print(f"Failed to parse JSON for apply buttons: {e}")
                
            btn_lay.addStretch()
            lay.addLayout(btn_lay)
            
        self._add_message_widget(frame)

    def _copy_code(self, code, button=None):
        QApplication.clipboard().setText(code)
        if button is not None:
            button.setText("已复制")

    def _looks_like_param_block(self, code):
        code_l = code.lower()
        return (
            ('ratio' in code_l and ('stages' in code_l or 'stage' in code_l))
            or ('passband_ratio' in code_l and 'fir_taps' in code_l)
            or ('fir_taps' in code_l and 'data_width' in code_l)
        )

    def _apply_message_params(self, text, raw_blocks):
        params = self._find_apply_params(text, raw_blocks)
        if params is None:
            QMessageBox.warning(self, "无法应用", "没有从这条回复中识别出完整参数。")
            return
        self._apply_params_to_ui(params)

    def _balanced_json_objects(self, text):
        objects = []
        start = None
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:i + 1])
                    start = None
        return objects

    def _extract_number(self, text, patterns, cast=float):
        import re
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return cast(m.group(1))
                except (ValueError, TypeError):
                    pass
        return None

    def _extract_loose_json_params(self, text):
        import re
        params = {}
        string_keys = {
            'mode': ['mode', 'type'],
            'fir_type': ['fir_type'],
        }
        number_keys = {
            'ratio': ['ratio'],
            'stages': ['stages'],
            'delay': ['delay'],
            'fir_taps': ['fir_taps'],
            'passband_ratio': ['passband_ratio', 'fir_passband'],
            'fir_width': ['fir_width', 'fir_coeff_width', 'coefficient_width'],
            'data_width': ['data_width', 'data_w'],
        }

        for out_key, keys in string_keys.items():
            for key in keys:
                m = re.search(rf'["\']{key}["\']\s*:\s*["\']([^"\']+)', text, re.IGNORECASE)
                if m:
                    params[out_key] = m.group(1).strip()
                    break

        for out_key, keys in number_keys.items():
            for key in keys:
                m = re.search(rf'["\']{key}["\']\s*:\s*["\']?\s*(-?\d+(?:\.\d+)?)', text, re.IGNORECASE)
                if m:
                    value = float(m.group(1)) if '.' in m.group(1) else int(m.group(1))
                    params[out_key] = value
                    break

        fs_match = re.search(r'["\']fs_in["\']\s*:\s*["\']?\s*(\d+(?:\.\d+)?)(?:\s*(GHz|MHz|kHz|Hz))?', text, re.IGNORECASE)
        if fs_match:
            value = float(fs_match.group(1))
            unit = (fs_match.group(2) or 'Hz').lower()
            params['fs_in'] = int(value * {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}[unit])

        if 'ratio' not in params or 'stages' not in params:
            return None
        if 'mode' not in params:
            params['mode'] = 'Interpolator_FIR' if ('fir_taps' in params or 'passband_ratio' in params) else 'Interpolator'
        return params

    def _normalize_apply_params(self, params, source_text):
        if not isinstance(params, dict):
            return None
        if 'mode' not in params and 'type' in params:
            params = dict(params)
            params['mode'] = params['type']
        if 'ratio' not in params or 'stages' not in params or 'mode' not in params:
            return None

        out = dict(params)
        text_l = source_text.lower()
        is_image = (
            any(k in text_l for k in ('png', '4x', '4×'))
            or any(k in source_text for k in ('图像', '灰度', '像素', '放大'))
        )
        if is_image and out.get('mode') == 'Interpolator':
            out['mode'] = 'Interpolator_FIR'
        if is_image and ('fir_taps' in out or 'fir_type' in out) and out.get('mode') != 'Interpolator_FIR':
            out['mode'] = 'Interpolator_FIR'
        out.setdefault('delay', 1)
        out.setdefault('fir_type', 'parallel')
        out.setdefault('data_width', 8 if is_image else 16)
        if 'fir_coeff_width' in out and 'fir_width' not in out:
            out['fir_width'] = out['fir_coeff_width']
        if 'coefficient_width' in out and 'fir_width' not in out:
            out['fir_width'] = out['coefficient_width']
        if is_image:
            out.setdefault('fs_in', 10000000)
        return out

    def _find_apply_params(self, text, raw_blocks):
        for _lang, code in raw_blocks:
            if 'ratio' in code and 'stages' in code and '{' in code:
                try:
                    parsed = json.loads(code)
                    found = self._normalize_apply_params(parsed, text)
                    if found:
                        return found
                except Exception:
                    pass

        loose_text = "\n".join(code for _lang, code in raw_blocks)
        if loose_text:
            found = self._normalize_apply_params(self._extract_loose_json_params(loose_text), text)
            if found:
                return found

        for obj in self._balanced_json_objects(text):
            if 'ratio' in obj and 'stages' in obj:
                try:
                    parsed = json.loads(obj)
                    found = self._normalize_apply_params(parsed, text)
                    if found:
                        return found
                except Exception:
                    pass

        found = self._normalize_apply_params(self._extract_loose_json_params(text), text)
        if found:
            return found

        text_l = text.lower()
        is_image_answer = (
            any(k in text_l for k in ('png', '4x', '4×', 'fir'))
            or any(k in text for k in ('图像', '灰度', '像素', '抽头', '放大'))
        )
        if not is_image_answer:
            return None

        ratio = self._extract_number(text, [
            r'(?:ratio|插值比|升采样|上采样|放大)\D{0,20}(\d+)',
            r'(\d+)\s*[x×]\s*(?:升采样|上采样|放大|插值)'
        ], int) or 4
        stages = self._extract_number(text, [
            r'(?:stages|CIC\s*级数|级数|阶数)\D{0,20}(\d+)',
            r'(\d+)\s*阶\s*CIC'
        ], int) or 3
        delay = self._extract_number(text, [
            r'(?:delay|微分延迟)\D{0,20}(\d+)'
        ], int) or 1
        fir_taps = self._extract_number(text, [
            r'(?:fir_taps|FIR\s*抽头数|FIR\s*抽头|抽头数)\D{0,20}(\d+)'
        ], int) or 21
        passband = self._extract_number(text, [
            r'(?:passband_ratio|通带占比|通带比例|通带)\D{0,20}(0?\.\d+|1(?:\.0+)?)'
        ], float) or 0.3
        fir_width = self._extract_number(text, [
            r'(?:fir_width|fir_coeff_width|coefficient_width|FIR\s*系数位宽|系数位宽)\D{0,20}(\d+)\s*bit'
        ], int) or 16
        data_width = self._extract_number(text, [
            r'(?:data_width|data_w|数据位宽)\D{0,20}(\d+)\s*bit',
            r'(\d+)\s*bit\s*(?:无符号)?(?:灰度|像素|数据)'
        ], int) or 8

        fs_in = 10000000
        import re
        fs_match = re.search(r'(?:fs_in|输入时钟|时钟频率|像素时钟)\D{0,30}(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)', text, re.IGNORECASE)
        if fs_match:
            scale = {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}[fs_match.group(2).lower()]
            fs_in = int(float(fs_match.group(1)) * scale)

        fir_type = 'parallel'
        if 'serial' in text_l or '串行' in text:
            fir_type = 'serial'
        elif re.search(r'\bda\b', text_l) or '分布式' in text:
            fir_type = 'da'

        return {
            'mode': 'Interpolator_FIR',
            'ratio': ratio,
            'stages': stages,
            'delay': delay,
            'fir_taps': fir_taps,
            'passband_ratio': passband,
            'fir_width': fir_width,
            'fir_type': fir_type,
            'data_width': data_width,
            'fs_in': fs_in,
        }

    def _coerce_int_param(self, value):
        import re
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        m = re.search(r'-?\d+', str(value))
        if m:
            return int(m.group(0))
        return None

    def _coerce_float_param(self, value):
        import re
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        m = re.search(r'-?\d+(?:\.\d+)?', str(value))
        if m:
            return float(m.group(0))
        return None

    def _coerce_fs_hz(self, value):
        import re
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)?', text, re.IGNORECASE)
        if not m:
            return None
        scale = {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}
        unit = (m.group(2) or 'Hz').lower()
        return float(m.group(1)) * scale[unit]

    def _apply_params_to_ui(self, params):
        try:
            self.app.apply_params_to_ui(params)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"应用参数失败: {e}")

    def _render_markdown(self, text):
        if HAS_MARKDOWN:
            # We must use fenced_code and we can do custom styling
            html = markdown.markdown(text, extensions=['fenced_code', 'tables'])
            return html
        else:
            # Fallback
            safe_text = text.replace('<', '&lt;').replace('>', '&gt;')
            return f"<pre>{safe_text}</pre>"

    def _add_typing_indicator(self):
        if self._typing_widget: return
        # Create a thinking container instead of a single label
        self._typing_widget = QFrame()
        self._typing_widget.setStyleSheet(f"background: {THEME['surface']}; border: 1px solid {THEME['border']}; border-radius: 8px; padding: 8px;")
        tw_lay = QVBoxLayout(self._typing_widget)
        tw_lay.setContentsMargins(10, 8, 10, 8)
        tw_lay.setSpacing(6)

        self._thinking_label = QLabel("🟢 思考中...")
        self._thinking_label.setStyleSheet(f"color: {THEME['subtext']}; font-size: 13px; font-weight: bold; border: none;")
        tw_lay.addWidget(self._thinking_label)

        self._steps_container = QVBoxLayout()
        self._steps_container.setSpacing(4)
        tw_lay.addLayout(self._steps_container)

        self._add_message_widget(self._typing_widget)
        self._thinking_start = time.time()
        self._thinking_status_text = None
        self._thinking_timer = QTimer()
        self._thinking_timer.timeout.connect(self._update_thinking_time)
        self._thinking_timer.start(1000)

    def _update_thinking_time(self):
        if not self._typing_widget or not hasattr(self, '_thinking_label'):
            return
        elapsed = int(time.time() - self._thinking_start)
        dots = "." * ((elapsed % 3) + 1)
        if self._thinking_status_text:
            self._thinking_label.setText(f"🟢 {self._thinking_status_text} ({elapsed}s){dots}")
        else:
            self._thinking_label.setText(f"🟢 思考中 ({elapsed}s){dots}")

    @pyqtSlot(str)
    def _update_typing_status(self, text):
        self._thinking_status_text = text
        if self._typing_widget and hasattr(self, '_thinking_label'):
            elapsed = int(time.time() - self._thinking_start)
            self._thinking_label.setText(f"{text} ({elapsed}s)")

    @pyqtSlot(object)
    def _on_step_update(self, step):
        if not self._typing_widget or not hasattr(self, '_steps_container'):
            return
        step_w = QFrame()
        step_w.setStyleSheet(f"background: {THEME['bg']}; border-radius: 4px; padding: 6px; border: none;")
        s_lay = QVBoxLayout(step_w)
        s_lay.setContentsMargins(8, 4, 8, 4)
        s_lay.setSpacing(2)

        if step.action:
            tool_name = step.action.split('(')[0]
            action_lbl = QLabel(f"🔧 {tool_name}")
            action_lbl.setStyleSheet(f"color: {THEME['success']}; font-size: 12px; font-weight: bold; border: none;")
            s_lay.addWidget(action_lbl)

        if step.thought:
            thought_text = step.thought[:120] + "..." if len(step.thought) > 120 else step.thought
            thought_section = CollapsibleSection("Thought")
            t_lbl = QLabel(thought_text)
            t_lbl.setWordWrap(True)
            t_lbl.setStyleSheet(f"color: {THEME['subtext']}; font-size: 11px; font-style: italic; border: none;")
            thought_section.add_widget(t_lbl)
            s_lay.addWidget(thought_section)

        if step.observation:
            obs_text = step.observation[:150] + "..." if len(step.observation) > 150 else step.observation
            obs_section = CollapsibleSection("Observation")
            o_lbl = QLabel(obs_text)
            o_lbl.setWordWrap(True)
            o_lbl.setStyleSheet(f"color: {THEME['subtext']}; font-size: 11px; border: none;")
            obs_section.add_widget(o_lbl)
            s_lay.addWidget(obs_section)

        self._steps_container.addWidget(step_w)
        self._scroll_to_bottom()

    def _remove_typing_indicator(self):
        if hasattr(self, '_thinking_timer') and self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None
        if self._typing_widget:
            self.chat_layout.removeWidget(self._typing_widget)
            self._typing_widget.deleteLater()
            self._typing_widget = None
        self._thinking_status_text = None

    def _on_send(self):
        text = self.input_edit.toPlainText().strip()
        if not text: return
        self.input_edit.clear()
        self._add_user_message(text)
        self._add_typing_indicator()
        
        threading.Thread(target=self._do_chat_thread, args=(text,), daemon=True).start()

    def _do_chat_thread(self, text):
        try:
            ctx = self.app.get_params()
            if self.agent:
                res = self.agent.run(text, context_params=ctx)
                self.signals.success.emit(res, True)
            else:
                res = self.helper.chat(text, context_params=ctx)  # type: ignore[union-attr]
                self.signals.success.emit(res, False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.error.emit(str(e))

    @pyqtSlot(object, bool)
    def _on_chat_success(self, result, is_agent):
        self._remove_typing_indicator()

        if is_agent:
            # Render collapsible reasoning process
            if getattr(result, 'scratchpad', None):
                section = CollapsibleSection(f"推理过程 ({len(result.scratchpad)} 步)")
                for step in result.scratchpad:
                    step_frame = QFrame()
                    step_frame.setStyleSheet(f"background: {THEME['bg']}; border-radius: 4px; padding: 4px;")
                    sf_lay = QVBoxLayout(step_frame)
                    sf_lay.setContentsMargins(6, 4, 6, 4)
                    sf_lay.setSpacing(2)
                    if step.action:
                        tool_name = step.action.split('(')[0]
                        al = QLabel(f"🔧 {tool_name}")
                        al.setStyleSheet(f"color: {THEME['success']}; font-size: 12px; font-weight: bold;")
                        sf_lay.addWidget(al)
                    if step.thought:
                        tl = QLabel(step.thought[:150] + ("..." if len(step.thought) > 150 else ""))
                        tl.setWordWrap(True)
                        tl.setStyleSheet(f"color: {THEME['subtext']}; font-size: 11px; font-style: italic;")
                        sf_lay.addWidget(tl)
                    section.add_widget(step_frame)
                self._add_message_widget(section)

            # Extract code blocks
            ans = result.answer
            blocks = []
            if '```' in ans:
                import re
                blocks = [(m.group(1) or 'text', m.group(2).strip()) for m in re.finditer(r'```(.*?\n)?(.*?)```', ans, re.S)]
            if not blocks:
                import re
                for m in re.finditer(r'\{[\s\S]*?\}', ans):
                    code = m.group(0).strip()
                    if 'ratio' in code and 'stages' in code and 'mode' in code:
                        try:
                            parsed = json.loads(code)
                            if isinstance(parsed, dict):
                                blocks.append(('json', code))
                                break
                        except Exception:
                            pass

            html = self._render_markdown(ans)
            self._add_ai_message(html, raw_blocks=blocks, source_text=ans)

        else:
            self._add_ai_message(self._render_markdown(result), source_text=result)

    @pyqtSlot(str)
    def _on_chat_error(self, err):
        self._remove_typing_indicator()
        self._add_ai_message(f"<span style='color:{THEME['error']}'>❌ 执行错误: {err}</span>")

    def _clear_chat(self):
        for i in reversed(range(self.chat_layout.count() - 1)):
            item = self.chat_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if self.helper: self.helper.clear_history()
        self._add_system_message("对话已清空")

    # ---- Quick Actions (Agent tools) ----
    def _quick_explain(self):
        self._on_send_direct("请详细解释我当前界面的参数配置。")

    def _quick_diagnose(self):
        self._on_send_direct("请对当前设计进行一键诊断：先检查参数合法性，再分析位宽增长、频率响应和资源占用，最后给出综合评价。")

    def _quick_suggest(self):
        dlg = ParamSuggestDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_text:
            self._on_send_direct(dlg.result_text)

    def _quick_compare(self):
        params = self.app.get_params() or {}
        dlg = CompareDialog(params, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_text:
            self._on_send_direct(dlg.result_text)

    def _quick_matlab(self):
        self._on_send_direct("请生成用于当前参数配置的 MATLAB 验证脚本。")

    # ---- Session History (B5) ----
    def _save_session(self):
        if not self.helper:
            return
        try:
            path = self.helper.save_history()
            QMessageBox.information(self, "保存成功", f"会话已保存到:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load_session(self):
        if not self.helper:
            return
        try:
            sessions = self.helper.list_sessions()
            if not sessions:
                QMessageBox.information(self, "无历史", "没有找到已保存的会话记录。")
                return
            dlg = SessionHistoryDialog(sessions, self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_name:
                self.helper.load_history(dlg.selected_name)
                self._clear_chat()
                self._add_system_message(f"已加载会话: {dlg.selected_name}")
                for msg in self.helper.chat_history:
                    if msg['role'] == 'user':
                        self._add_user_message(msg['content'])
                    elif msg['role'] == 'assistant':
                        self._add_ai_message(self._render_markdown(msg['content']))
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))

    # ---- Agent Step Callback (B6) ----
    def _on_agent_step(self, step):
        self.signals.step_update.emit(step)
        
    def _on_send_direct(self, text):
        self._add_user_message(text)
        self._add_typing_indicator()
        threading.Thread(target=self._do_chat_thread, args=(text,), daemon=True).start()


# ==============================================================================
# Main Application (PyQt6 rewrite)
# ==============================================================================
class ModernApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("数字升降采样器自动设计工具 - Modernized")
        self.resize(1100, 750)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        self.build_ui()
        self.update_resource_estimate()
        self._show_empty_chart()

    def build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Header
        header = QFrame()
        header.setFixedHeight(64)
        header.setObjectName("Header")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(24, 0, 24, 0)

        title = QLabel("CIC / FIR 设计工具")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {THEME['text']};")
        subtitle = QLabel("Digital Resampler Designer (PyQt Edition)")
        subtitle.setStyleSheet(f"font-size: 13px; color: {THEME['subtext']}; margin-top:4px;")

        h_layout.addWidget(title)
        h_layout.addWidget(subtitle)
        h_layout.addStretch()

        clip_btn = QPushButton("应用剪贴板参数")
        clip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clip_btn.clicked.connect(self.apply_clipboard_params)
        h_layout.addWidget(clip_btn)

        ai_btn = QPushButton("✨ AI 助手")
        ai_btn.setObjectName("AIAssistantBtn")
        ai_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ai_btn.clicked.connect(self._open_ai_assistant)
        h_layout.addWidget(ai_btn)

        main_layout.addWidget(header)

        # 2. Main Body Splitter
        body = QWidget()
        body.setStyleSheet(f"background-color: {THEME['bg']};")
        b_layout = QVBoxLayout(body)
        b_layout.setContentsMargins(24, 24, 24, 24)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Panel (Settings)
        left_area = QScrollArea()
        left_area.setWidgetResizable(True)
        left_area.setMinimumWidth(380)
        left_area.setMaximumWidth(450)

        self.left_container = QWidget()
        self.left_layout = QVBoxLayout(self.left_container)
        self.left_layout.setContentsMargins(0, 0, 16, 0)
        self.left_layout.setSpacing(20)

        self.build_left_panel()
        self.left_layout.addStretch()
        
        left_area.setWidget(self.left_container)
        self.splitter.addWidget(left_area)
        
        # Right Panel (Charts & Info)
        right_panel = QWidget()
        self.right_layout = QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(16, 0, 0, 0)
        
        self.build_right_panel()
        
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(1, 1) # Right panel expands more
        
        b_layout.addWidget(self.splitter)
        main_layout.addWidget(body)

    def build_left_panel(self):
        # Card 1: Architecture
        self.mode_card = Card("系统架构")
        self.mode_group = QButtonGroup(self)
        self.modes = [
            ("CIC 升采样 (Interpolator)", "Interpolator"),
            ("CIC 降采样 (Decimator)", "Decimator"),
            ("FIR 预补偿 + CIC 升采样 (Interpolator + FIR)", "Interpolator_FIR"),
            ("CIC 降采样 + FIR 补偿 (Decimator + FIR)", "Decimator_FIR"),
        ]
        self.mode_buttons = []
        for i, (text, val) in enumerate(self.modes):
            rb = QRadioButton(text)
            self.mode_group.addButton(rb, i)
            self.mode_card.add_widget(rb)
            self.mode_buttons.append((rb, val))
            # Delayed connect mapping
            rb.toggled.connect(self._on_param_change)
        
        self.left_layout.addWidget(self.mode_card)
        
        # Card 2: Input Params
        self.sys_card = Card("输入参数配置")
        sys_lay = QHBoxLayout()
        lbl_fs = QLabel("输入采样率")
        lbl_fs.setStyleSheet(f"color: {THEME['text']};")
        sys_lay.addWidget(lbl_fs)
        self.inp_fs = QLineEdit("10")
        self.inp_fs.setAlignment(Qt.AlignmentFlag.AlignRight)
        sys_lay.addWidget(self.inp_fs)
        self.cmb_unit = QComboBox()
        self.cmb_unit.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.cmb_unit.setCurrentIndex(2) # MHz
        sys_lay.addWidget(self.cmb_unit)
        self.sys_card.add_layout(sys_lay)

        self.inp_width = InputRow("数据位宽 (DATA_IN_W)", 16, "Bits")
        self.sys_card.add_widget(self.inp_width)
        self.inp_width.input_field.textChanged.connect(self._on_param_change_delayed)

        self.left_layout.addWidget(self.sys_card)

        # Card 3: CIC
        self.cic_card = Card("CIC 滤波配置")
        self.inp_ratio = InputRow("抽取/插值倍率 (R)", 32, "R")
        self.inp_stages = InputRow("级数 (N)", 4, "N")
        self.inp_delay = InputRow("微分延迟 (M)", 1, "M")
        for inp in [self.inp_ratio, self.inp_stages, self.inp_delay]:
            self.cic_card.add_widget(inp)
            inp.input_field.textChanged.connect(self._on_param_change_delayed)
        self.left_layout.addWidget(self.cic_card)

        # Card 4: FIR
        self.fir_card = Card("FIR 补偿滤波器")
        
        type_lay = QHBoxLayout()
        lbl_type = QLabel("FIR 结构")
        lbl_type.setStyleSheet(f"color: {THEME['text']};")
        type_lay.addWidget(lbl_type)
        self.cmb_fir_type = QComboBox()
        self.cmb_fir_type.addItems(["并行 (Parallel，全吞吐量)", "串行 (Serial，单乘法器)", "分布式算术 (DA，无乘法器)"])
        self.cmb_fir_type.currentTextChanged.connect(self._on_param_change)
        type_lay.addWidget(self.cmb_fir_type)
        self.fir_card.add_layout(type_lay)
        
        self.inp_taps = InputRow("抽头数 (Taps)", 21)
        self.inp_fir_w = InputRow("系数位宽", 16, "Bits")
        self.inp_pass = InputRow("兼容参数", 1.0, "auto")
        self.inp_pass.input_field.setReadOnly(True)
        for inp in [self.inp_taps, self.inp_fir_w, self.inp_pass]:
            self.fir_card.add_widget(inp)
            inp.input_field.textChanged.connect(self._on_param_change_delayed)
            
        win_lay = QHBoxLayout()
        lbl_win = QLabel("窗函数")
        lbl_win.setStyleSheet(f"color: {THEME['text']};")
        win_lay.addWidget(lbl_win)
        self.cmb_window = QComboBox()
        self.cmb_window.addItems(["hamming", "hann", "blackman", "bartlett", "boxcar"])
        self.cmb_window.currentTextChanged.connect(self._on_param_change)
        win_lay.addWidget(self.cmb_window)
        self.fir_card.add_layout(win_lay)
        
        self.chk_antisym = QCheckBox("反对称系数 (Type III/IV)")
        self.chk_antisym.stateChanged.connect(self._on_param_change)
        self.fir_card.add_widget(self.chk_antisym)
        self.left_layout.addWidget(self.fir_card)
        
        # Card 5: Output
        self.out_card = Card("输出配置")
        self.inp_name = InputRow("模块名称", "my_design")
        self.out_card.add_widget(self.inp_name)
        
        path_lay = QHBoxLayout()
        self.lbl_path = QLabel("...")
        self.lbl_path.setStyleSheet(f"color: {THEME['subtext']}; font-size: 11px;")
        path_lay.addWidget(self.lbl_path)
        btn_path = QPushButton("选择文件夹")
        btn_path.clicked.connect(self._browse_path)
        path_lay.addWidget(btn_path)
        self.out_card.add_layout(path_lay)
        self.full_path = os.getcwd()
        self._update_path_display()
        
        self.chk_tb = QCheckBox("生成仿真平台 (Testbench)")
        self.out_card.add_widget(self.chk_tb)

        # Card 6: 输出位宽与模板固定信息
        self.trunc_card = Card("输出与复位信息")

        # 全精度位宽（只读展示）
        self.trunc_group = QButtonGroup(self)
        self.rb_full = QRadioButton("全精度输出")
        self.rb_full.setChecked(True)
        self.rb_custom = QRadioButton("自定义位宽")
        self.trunc_group.addButton(self.rb_full, 0)
        self.trunc_group.addButton(self.rb_custom, 1)

        full_lay = QHBoxLayout()
        full_lay.addWidget(self.rb_full)
        self.lbl_full_width = QLabel("-- Bits")
        self.lbl_full_width.setStyleSheet(f"color: {THEME['accent']}; font-weight: bold;")
        full_lay.addWidget(self.lbl_full_width)
        full_lay.addStretch()
        self.trunc_card.add_layout(full_lay)

        self.trunc_card.add_widget(self.rb_custom)

        self.custom_trunc_container = QWidget()
        ct_lay = QVBoxLayout(self.custom_trunc_container)
        ct_lay.setContentsMargins(20, 0, 0, 0)
        ct_lay.setSpacing(8)
        self.inp_out_width = InputRow("输出位宽", 16, "Bits")
        ct_lay.addWidget(self.inp_out_width)
        self.trunc_card.add_widget(self.custom_trunc_container)
        self.custom_trunc_container.hide()

        self.rb_full.toggled.connect(self._on_trunc_mode_change)
        self.rb_custom.toggled.connect(self._on_trunc_mode_change)

        # 截断方式（只读，rtl/ 模板固定为直接截断 MSB）
        trunc_info_lay = QHBoxLayout()
        lbl_tm = QLabel("截断方式")
        lbl_tm.setFixedWidth(140)
        lbl_tm.setStyleSheet(f"color: {THEME['subtext']};")
        self.cmb_trunc = QComboBox()
        self.cmb_trunc.addItems(["直接截断 (MSB)", "四舍五入 (Rounding)", "收敛舍入 (Convergent)"])
        self.cmb_trunc.setEnabled(False)
        self.cmb_trunc.setToolTip("选择非全精度输出时可选择截断方式")
        trunc_info_lay.addWidget(lbl_tm)
        trunc_info_lay.addWidget(self.cmb_trunc)
        self.trunc_card.add_layout(trunc_info_lay)

        # 复位风格（三种可选）
        reset_info_lay = QHBoxLayout()
        lbl_rst = QLabel("复位风格")
        lbl_rst.setFixedWidth(140)
        lbl_rst.setStyleSheet(f"color: {THEME['subtext']};")
        self.cmb_reset = QComboBox()
        self.cmb_reset.addItems(["Xilinx (同步高有效)", "Altera (同步低有效)", "ASIC (异步低有效)"])
        self.cmb_reset.setToolTip("Xilinx: sync active-high rst\nAltera: sync active-low rst_n\nASIC: async active-low rst_n with sync release")
        reset_info_lay.addWidget(lbl_rst)
        reset_info_lay.addWidget(self.cmb_reset)
        self.trunc_card.add_layout(reset_info_lay)

        self.left_layout.addWidget(self.trunc_card)

        # Actions
        act_lay = QVBoxLayout()
        act_lay.setSpacing(10)
        btn_gen = QPushButton("🚀 生成 RTL 代码")
        btn_gen.setObjectName("AccentButton")
        btn_gen.setStyleSheet(f"background-color: {THEME['accent']}; color: #ffffff; border: none; border-radius: 6px; padding: 8px 14px; font-weight: 600;")
        btn_gen.clicked.connect(self.on_generate)

        btn_tb = QPushButton("🧪 生成测试平台")
        btn_tb.clicked.connect(self.on_generate_tb)

        btn_prev = QPushButton("📊 预览频率响应")
        btn_prev.clicked.connect(self.on_preview)

        act_lay.addWidget(btn_gen)
        act_lay.addWidget(btn_tb)
        act_lay.addWidget(btn_prev)
        self.left_layout.addLayout(act_lay)
        
        self._delay_timer = QTimer()
        self._delay_timer.setSingleShot(True)
        self._delay_timer.timeout.connect(self._on_param_change)

    def build_right_panel(self):
        # Toolbar
        tools = QFrame()
        t_lay = QHBoxLayout(tools)
        t_lay.setContentsMargins(0, 0, 0, 10)
        
        btn_zoom = QPushButton("🔍 缩放通带")
        btn_zoom.clicked.connect(self.zoom_passband)
        btn_reset = QPushButton("🔄 重置视图")
        btn_reset.clicked.connect(self.reset_zoom)
        btn_save = QPushButton("💾 保存图表")
        btn_save.clicked.connect(self.export_chart)
        
        self.chk_norm = QCheckBox("归一化 X 轴")
        self.chk_norm.setChecked(True)
        self.chk_norm.stateChanged.connect(self.on_preview)
        
        t_lay.addWidget(btn_zoom)
        t_lay.addWidget(btn_reset)
        t_lay.addWidget(btn_save)
        t_lay.addStretch()
        t_lay.addWidget(self.chk_norm)
        self.right_layout.addWidget(tools)
        
        # Chart Setup
        self.fig = Figure(dpi=100, facecolor=THEME['surface'])
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        
        # Wrapping canvas in a card to style the border
        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cl = QVBoxLayout(chart_card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.canvas)
        self.right_layout.addWidget(chart_card, 1) # Expanding priority
        
        # Resource Card
        self.res_card = Card("资源预估")
        self.lbl_res_cic = QLabel("CIC: --")
        self.lbl_res_fir = QLabel("FIR: --")
        self.lbl_res_tot = QLabel("总计: --")
        self.lbl_res_tot.setStyleSheet(f"font-weight: bold; color: {THEME['accent']}; font-size: 14px;")
        self.res_card.add_widget(self.lbl_res_cic)
        self.res_card.add_widget(self.lbl_res_fir)
        self.res_card.add_widget(self.lbl_res_tot)
        self.right_layout.addWidget(self.res_card)

        # 缩放状态初始化
        self._current_xlim = 0.5
        self._is_zoomed = False
        self._zoom_xlim_ratio = None
        self._zoom_ylim = None

    def _browse_path(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if d:
            self.full_path = d
            self._update_path_display()
            
    def _update_path_display(self):
        p = self.full_path
        if len(p) > 35: p = "..." + p[-32:]
        self.lbl_path.setText(p)

    def get_fs_hz(self):
        try:
            val = float(self.inp_fs.text())
            u = self.cmb_unit.currentText()
            m = {"Hz":1, "kHz":1e3, "MHz":1e6, "GHz":1e9}
            return val * m[u]
        except: return 1.0

    def get_mode(self):
        idx = self.mode_group.checkedId()
        if idx >= 0: return self.mode_buttons[idx][1]
        return "Decimator"

    def get_params(self):
        try:
            m = self.get_mode()
            p = {
                'type': m,
                'fs_in': self.get_fs_hz(),
                'data_w': int(self.inp_width.text()),
                'ratio': int(self.inp_ratio.text()),
                'stages': int(self.inp_stages.text()),
                'delay': int(self.inp_delay.text()),
                'filename': self.inp_name.text(),
                'path': self.full_path,
                'generate_tb': self.chk_tb.isChecked(),
                'trunc_mode': '全精度' if self.rb_full.isChecked() else self.cmb_trunc.currentText(),
                'reset_style': ['xilinx', 'altera', 'asic'][self.cmb_reset.currentIndex()]
            }
            if self.rb_custom.isChecked():
                try:
                    p['output_width'] = int(self.inp_out_width.text())
                except ValueError:
                    pass
            if "FIR" in p['type']:
                p['fir_taps'] = int(self.inp_taps.text())
                p['fir_width'] = int(self.inp_fir_w.text())
                p['fir_passband'] = float(self.inp_pass.text())
                p['window'] = self.cmb_window.currentText()
                p['antisym'] = self.chk_antisym.isChecked()
                p['fir_type'] = "parallel"
                if hasattr(self, 'cmb_fir_type'):
                    if '串行' in self.cmb_fir_type.currentText():
                        p['fir_type'] = "serial"
                    elif '分布式' in self.cmb_fir_type.currentText():
                        p['fir_type'] = "da"
            return p
        except Exception: 
            return None

    def _on_trunc_mode_change(self):
        if self.rb_custom.isChecked():
            self.custom_trunc_container.show()
            self.cmb_trunc.setEnabled(True)
            fp = self._calc_full_precision_width()
            if fp > 0:
                self.inp_out_width.set_text(fp)
        else:
            self.custom_trunc_container.hide()
            self.cmb_trunc.setEnabled(False)

    def _calc_full_precision_width(self):
        try:
            w = int(self.inp_width.text())
            r = int(self.inp_ratio.text())
            n = int(self.inp_stages.text())
            m = int(self.inp_delay.text())
            cic_growth = calc_cic_growth(n, m, r)
            fp = w + cic_growth
            if "FIR" in self.get_mode():
                coe_w = int(self.inp_fir_w.text())
                taps = int(self.inp_taps.text())
                fp = w + coe_w + math.ceil(math.log2(taps)) + cic_growth
            return fp
        except (ValueError, ZeroDivisionError):
            return 0

    def _on_param_change_delayed(self):
        self._delay_timer.start(500) # Throttle updates

    def _on_param_change(self):
        m = self.get_mode()
        if "FIR" in m:
            self.fir_card.show()
        else:
            self.fir_card.hide()
        self.update_resource_estimate()
        fp = self._calc_full_precision_width()
        if fp > 0:
            self.lbl_full_width.setText(f"{fp} Bits")
        else:
            self.lbl_full_width.setText("-- Bits")

    def update_resource_estimate(self):
        if not hasattr(self, 'lbl_res_cic'):
            return
        try:
            w = int(self.inp_width.text())
            r = int(self.inp_ratio.text())
            n = int(self.inp_stages.text())
            m = int(self.inp_delay.text())

            if "FIR" in self.get_mode():
                taps = int(self.inp_taps.text())
            else:
                taps = 0

            est = estimate_fpga_resource(n, m, r, w, taps)

            self.lbl_res_cic.setText(
                f"CIC: {est['cic']['luts']} LUTs, {est['cic']['ffs']} FFs")
            if taps > 0:
                self.lbl_res_fir.setText(
                    f"FIR: {est['fir']['luts']} LUTs, {est['fir']['ffs']} FFs, {est['fir']['dsps']} DSPs")
            else:
                self.lbl_res_fir.setText("FIR: N/A")
            self.lbl_res_tot.setText(
                f"总计: ~{est['total']['luts']} LUTs, ~{est['total']['ffs']} FFs")
        except Exception:
            self.lbl_res_tot.setText("总计: -- (参数有误)")

    def _show_empty_chart(self):
        if not hasattr(self, 'canvas'):
            return
        self.ax.clear()
        self.setup_chart_style()
        self.ax.set_xlabel("归一化输出频率 (1 = Fout/2)", fontsize=10)
        self.ax.set_ylabel("幅度 (dB)", fontsize=10)
        self.ax.set_ylim(-120, 10)
        self.ax.text(0.5, 0.5, "请点击「预览频率响应」查看图表",
                     transform=self.ax.transAxes, ha='center', va='center',
                     fontsize=13, color=THEME['subtext'], alpha=0.6)
        self.canvas.draw()

    def setup_chart_style(self):
        self.ax.spines['bottom'].set_color(THEME['border'])
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.ax.spines['left'].set_color(THEME['border'])
        self.ax.tick_params(axis='x', colors=THEME['subtext'], labelsize=9)
        self.ax.tick_params(axis='y', colors=THEME['subtext'], labelsize=9)
        self.ax.grid(True, linestyle=':', alpha=0.5, color=THEME['border'])
        self.ax.xaxis.label.set_color(THEME['subtext'])
        self.ax.yaxis.label.set_color(THEME['subtext'])

    def on_preview(self):
        if not hasattr(self, 'canvas'):
            return
        p = self.get_params()
        if not p: return
        try:
            use_fir = "FIR" in p['type']
            freqs, cic, fir, tot = analyze_response_wide(
                p['stages'], p['ratio'], p['delay'], 
                p.get('fir_taps',15) if use_fir else 15,
                p.get('fir_passband',0.5) if use_fir else 0.5,
                p.get('fir_width',16) if use_fir else 16,
                p.get('window','hamming'), p.get('antisym',False),
                mode=p['type']
            )
            self.ax.clear()
            self.setup_chart_style()
            
            u_str = self.cmb_unit.currentText()
            unit_scale = {"Hz":1, "kHz":1e3, "MHz":1e6, "GHz":1e9}[u_str]
            if "Interpolator" in p['type']:
                output_fs = p['fs_in'] * p['ratio']
            else:
                output_fs = p['fs_in'] / p['ratio']
            
            if self.chk_norm.isChecked():
                x = freqs
                self.ax.set_xlabel("归一化输出频率 (1 = Fout/2)", fontsize=10)
            else:
                x = freqs * (output_fs / 2.0) / unit_scale
                self.ax.set_xlabel(f"输出频率 ({u_str})", fontsize=10)
            self.ax.set_ylabel("幅度 (dB)", fontsize=10)
            
            self._current_xlim = x[-1] if len(x) > 0 else 0.5
            
            self.ax.plot(x, cic, label="CIC", color=THEME['accent'])
            if use_fir:
                self.ax.plot(x, fir, label="FIR", linestyle='--', color='#9ca3af')
                self.ax.plot(x, tot, label="总响应", color=THEME['success'], lw=2)

            if self._is_zoomed and self._zoom_xlim_ratio:
                self.ax.set_xlim(0, self._zoom_xlim_ratio * self._current_xlim)
                self.ax.set_ylim(self._zoom_ylim)
            else:
                self.ax.set_ylim(-120, 10)
            self.ax.legend(frameon=True, edgecolor=THEME['border'])
            self.canvas.draw()
        except Exception as e:
            QMessageBox.warning(self, "预览失败", f"参数错误引发异常:\n{e}")

    def zoom_passband(self):
        if not hasattr(self, '_current_xlim') or self._current_xlim == 0:
            return
        try:
            R = int(self.inp_ratio.text())
            passband_end = self._current_xlim * get_useful_band_edge(self.get_mode(), R)
            xlim_end = passband_end * 1.1
            self.ax.set_xlim(0, xlim_end)
            self.ax.set_ylim(-10, 5)
            self._is_zoomed = True
            self._zoom_xlim_ratio = xlim_end / self._current_xlim
            self._zoom_ylim = (-10, 5)
            self.canvas.draw()
        except (ValueError, ZeroDivisionError):
            pass

    def reset_zoom(self):
        if hasattr(self, '_current_xlim'):
            self.ax.set_xlim(0, self._current_xlim)
            self.ax.set_ylim(-120, 10)
            self._is_zoomed = False
            self._zoom_xlim_ratio = None
            self._zoom_ylim = None
            self.canvas.draw()

    def _coerce_int_param(self, value):
        import re
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        m = re.search(r'-?\d+', str(value))
        if m:
            return int(m.group(0))
        return None

    def _coerce_float_param(self, value):
        import re
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        m = re.search(r'-?\d+(?:\.\d+)?', str(value))
        if m:
            return float(m.group(0))
        return None

    def _coerce_fs_hz(self, value):
        import re
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)?', text, re.IGNORECASE)
        if not m:
            return None
        scale = {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}
        unit = (m.group(2) or 'Hz').lower()
        return float(m.group(1)) * scale[unit]

    def _balanced_json_objects(self, text):
        objects = []
        start = None
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:i + 1])
                    start = None
        return objects

    def _extract_loose_json_params(self, text):
        import re
        params = {}
        string_keys = {
            'mode': ['mode', 'type'],
            'fir_type': ['fir_type'],
        }
        number_keys = {
            'ratio': ['ratio'],
            'stages': ['stages'],
            'delay': ['delay'],
            'fir_taps': ['fir_taps'],
            'passband_ratio': ['passband_ratio', 'fir_passband'],
            'fir_width': ['fir_width', 'fir_coeff_width', 'coefficient_width'],
            'data_width': ['data_width', 'data_w'],
        }

        for out_key, keys in string_keys.items():
            for key in keys:
                m = re.search(rf'["\']{key}["\']\s*:\s*["\']([^"\']+)', text, re.IGNORECASE)
                if m:
                    params[out_key] = m.group(1).strip()
                    break

        for out_key, keys in number_keys.items():
            for key in keys:
                m = re.search(rf'["\']{key}["\']\s*:\s*["\']?\s*(-?\d+(?:\.\d+)?)', text, re.IGNORECASE)
                if m:
                    params[out_key] = float(m.group(1)) if '.' in m.group(1) else int(m.group(1))
                    break

        fs_match = re.search(r'["\']fs_in["\']\s*:\s*["\']?\s*(\d+(?:\.\d+)?)(?:\s*(GHz|MHz|kHz|Hz))?', text, re.IGNORECASE)
        if fs_match:
            value = float(fs_match.group(1))
            unit = (fs_match.group(2) or 'Hz').lower()
            params['fs_in'] = int(value * {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}[unit])

        return params or None

    def _normalize_apply_params(self, params):
        if not isinstance(params, dict):
            return None
        out = dict(params)
        if 'mode' not in out and 'type' in out:
            out['mode'] = out['type']
        if 'fir_passband' in out and 'passband_ratio' not in out:
            out['passband_ratio'] = out['fir_passband']
        if 'fir_coeff_width' in out and 'fir_width' not in out:
            out['fir_width'] = out['fir_coeff_width']
        if 'coefficient_width' in out and 'fir_width' not in out:
            out['fir_width'] = out['coefficient_width']
        has_fir = any(k in out for k in ('fir_taps', 'passband_ratio', 'fir_width', 'fir_type'))
        if out.get('mode') == 'Interpolator' and has_fir:
            out['mode'] = 'Interpolator_FIR'
        if 'mode' not in out:
            out['mode'] = 'Interpolator_FIR' if has_fir else 'Interpolator'
        if 'ratio' not in out or 'stages' not in out:
            return None
        out.setdefault('delay', 1)
        out.setdefault('data_width', 8 if has_fir else 16)
        out.setdefault('fir_type', 'parallel')
        return out

    def parse_params_text(self, text):
        import re
        text = (text or '').strip()
        if not text:
            return None

        candidates = [text]
        candidates.extend(m.group(2).strip() for m in re.finditer(r'```(.*?\n)?(.*?)```', text, re.S))
        candidates.extend(self._balanced_json_objects(text))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            found = self._normalize_apply_params(parsed)
            if found:
                return found

        loose = self._extract_loose_json_params("\n".join(candidates))
        return self._normalize_apply_params(loose)

    def apply_params_to_ui(self, params):
        blocked_inputs = [
            self.inp_ratio, self.inp_stages, self.inp_delay,
            self.inp_taps, self.inp_pass, self.inp_fir_w, self.inp_width
        ]
        try:
            for inp in blocked_inputs:
                inp.input_field.blockSignals(True)
            self.inp_fs.blockSignals(True)
            self.cmb_unit.blockSignals(True)

            mode = params.get('mode', params.get('type'))
            if mode:
                for rb, val in self.mode_buttons:
                    if val == mode:
                        rb.setChecked(True)
                        break

            fir_type = params.get('fir_type')
            if fir_type is not None:
                ft = str(fir_type).lower()
                if 'serial' in ft:
                    self.cmb_fir_type.setCurrentIndex(1)
                elif 'da' in ft:
                    self.cmb_fir_type.setCurrentIndex(2)
                else:
                    self.cmb_fir_type.setCurrentIndex(0)

            if 'ratio' in params: self.inp_ratio.set_text(self._coerce_int_param(params['ratio']) or params['ratio'])
            if 'stages' in params: self.inp_stages.set_text(self._coerce_int_param(params['stages']) or params['stages'])
            if 'delay' in params: self.inp_delay.set_text(self._coerce_int_param(params['delay']) or params['delay'])
            if 'fir_taps' in params: self.inp_taps.set_text(self._coerce_int_param(params['fir_taps']) or params['fir_taps'])
            if 'passband_ratio' in params: self.inp_pass.set_text(self._coerce_float_param(params['passband_ratio']) or params['passband_ratio'])

            fw = params.get('fir_width', params.get('fir_coeff_width', params.get('coefficient_width')))
            if fw is not None:
                coerced_fw = self._coerce_int_param(fw)
                if coerced_fw is not None:
                    self.inp_fir_w.set_text(coerced_fw)

            dw = params.get('data_width', params.get('data_w'))
            if dw is not None:
                coerced_dw = self._coerce_int_param(dw)
                if coerced_dw is not None:
                    self.inp_width.set_text(coerced_dw)

            fs_hz = params.get('fs_in')
            if fs_hz is not None:
                fs_val = self._coerce_fs_hz(fs_hz)
                if fs_val is not None:
                    if fs_val >= 1e9:
                        unit, scale = "GHz", 1e9
                    elif fs_val >= 1e6:
                        unit, scale = "MHz", 1e6
                    elif fs_val >= 1e3:
                        unit, scale = "kHz", 1e3
                    else:
                        unit, scale = "Hz", 1.0
                    self.inp_fs.setText(f"{fs_val / scale:.6g}")
                    idx = self.cmb_unit.findText(unit)
                    if idx >= 0:
                        self.cmb_unit.setCurrentIndex(idx)
        finally:
            for inp in blocked_inputs:
                inp.input_field.blockSignals(False)
            self.inp_fs.blockSignals(False)
            self.cmb_unit.blockSignals(False)

        self._on_param_change()
        self.update_resource_estimate()
        self.on_preview()

    def apply_clipboard_params(self):
        text = QApplication.clipboard().text()
        params = self.parse_params_text(text)
        if not params:
            QMessageBox.warning(self, "无法应用", "剪贴板里没有识别到可应用的参数 JSON。")
            return False
        self.apply_params_to_ui(params)
        QMessageBox.information(self, "已应用", "剪贴板参数已应用到主界面。")
        return True

    def maybe_apply_clipboard_params(self, previous_text):
        text = QApplication.clipboard().text()
        if not text or text == previous_text:
            return
        params = self.parse_params_text(text)
        if not params:
            return
        ret = QMessageBox.question(
            self,
            "检测到参数配置",
            "剪贴板中有可应用的参数 JSON，是否应用到主界面？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.apply_params_to_ui(params)

    def export_chart(self):
        fp, _ = QFileDialog.getSaveFileName(self, "保存图表", "response.png", "Images (*.png *.pdf *.svg)")
        if fp:
            self.fig.savefig(fp, dpi=150, facecolor=THEME['surface'], bbox_inches='tight')

    def on_generate(self):
        p = self.get_params()
        if not p:
            return
        # Show SaveAs dialog first to determine filename and module name
        default_name = os.path.join(p['path'], p['filename'] + ".v")
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存 RTL 代码", default_name, "Verilog Files (*.v);;All Files (*)")
        if not filepath:
            return
        # Extract module name from user-chosen filename
        base = os.path.splitext(os.path.basename(filepath))[0]
        p['filename'] = base
        self.inp_name.set_text(base)
        try:
            gen = CICCodeGenerator(p)
            code = gen.generate()
            if code.startswith("// [ERROR]"):
                QMessageBox.critical(self, "生成错误", code)
                return
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            ret = QMessageBox.question(self, "生成成功",
                f"代码已保存到:\n{filepath}\n\n是否打开所在文件夹？")
            if ret == QMessageBox.StandardButton.Yes:
                os.startfile(os.path.dirname(filepath))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def on_generate_tb(self):
        if not HAS_TB_GEN:
            QMessageBox.warning(self, "不可用", "测试平台生成模块未找到 (tb_generator.py)")
            return
        p = self.get_params()
        if not p:
            return
        # Show SaveAs dialog first
        default_name = os.path.join(p['path'], p['filename'] + "_test.py")
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存测试脚本", default_name, "Python Files (*.py);;All Files (*)")
        if not filepath:
            return
        # Extract base name and sync back
        base = os.path.splitext(os.path.basename(filepath))[0]
        if base.endswith("_test"):
            base = base[:-5]
        p['filename'] = base
        self.inp_name.set_text(base)
        try:
            result = generate_testbench(p, filepath)
            summary = result.get('summary', '')
            msg = f"测试脚本已保存到:\n{filepath}\n"
            if summary:
                msg += f"\n{summary}"
            QMessageBox.information(self, "测试平台生成成功", msg)
        except Exception as e:
            QMessageBox.critical(self, "生成失败", str(e))

    def _open_ai_assistant(self):
        previous_clipboard = QApplication.clipboard().text()
        dlg = AIAssistantDialog(self)
        dlg.exec()
        self.maybe_apply_clipboard_params(previous_clipboard)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernApp()
    window.show()
    sys.exit(app.exec())
