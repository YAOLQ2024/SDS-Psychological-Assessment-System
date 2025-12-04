import sys
import serial
import struct
import time
import threading
import numpy as np
from collections import deque
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                             QLabel, QHBoxLayout, QCheckBox, QPushButton, QFrame)
from PyQt5.QtCore import QTimer, pyqtSignal, QObject, Qt
import pyqtgraph as pg

# ==========================================
# 1. 配置参数
# ==========================================
SERIAL_PORT = 'COM9'       # 请修改为您的实际串口号
BAUD_RATE = 230400         # 必须与 NRF52 代码一致
SAMPLE_RATE = 500          # 采样率
PLOT_WINDOW = 5            # 显示窗口宽度 (秒)
BUFFER_SIZE = SAMPLE_RATE * 60 # 内存缓存 60 秒数据

# ==========================================
# 2. CRC16 校验 (CRC-16/CCITT-FALSE)
# ==========================================
class CRC16_CCITT:
    def __init__(self):
        self.poly = 0x1021
        self.table = [0] * 256
        self._generate_table()

    def _generate_table(self):
        for i in range(256):
            crc = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ self.poly
                else:
                    crc <<= 1
            self.table[i] = crc & 0xFFFF

    def calculate(self, data):
        crc = 0xFFFF # 初始值 0xFFFF
        for byte in data:
            idx = ((crc >> 8) ^ byte) & 0xFF
            crc = ((crc << 8) ^ self.table[idx]) & 0xFFFF
        return crc

# ==========================================
# 3. 串口读取线程
# ==========================================
class SerialWorker(QObject):
    # 信号定义: 通道ID, 波形数值(可为None), 特征字典(可为None)
    data_received = pyqtSignal(int, object, object)

    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = False
        self.crc_calculator = CRC16_CCITT()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)

    def _run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.05)
            print(f"✅ 串口已连接: {self.port} @ {self.baud}")
        except Exception as e:
            print(f"❌ 串口打开失败: {e}")
            return

        buffer = b''

        while self.running:
            try:
                # 1. 读取数据
                if ser.in_waiting:
                    buffer += ser.read(ser.in_waiting)
                
                # 2. 循环解析 (至少需要 Header(2) + Type(1) = 3 字节)
                while len(buffer) >= 3:
                    
                    # --- A. 校验包头 0x06 0x09 ---
                    if buffer[0] != 0x06 or buffer[1] != 0x09:
                        # 如果头不对，丢弃第一个字节，继续找
                        buffer = buffer[1:]
                        continue
                    
                    # --- B. 获取包类型 ---
                    pkt_type = buffer[2]
                    target_len = 0
                    
                    if pkt_type == 0x01:    # 波形包
                        # Header(2) + Type(1) + ID(1) + Data(4) + CRC(2) = 10
                        target_len = 10     
                    elif pkt_type == 0x02:  # 特征包
                        # Header(2) + Type(1) + ID(1) + Theta(4) + Alpha(4) + Beta(4) + CRC(2) = 18
                        target_len = 18     
                    else:
                        # 未知类型，跳过头（可能是假头）
                        # print(f"未知类型: {hex(pkt_type)}")
                        buffer = buffer[2:] 
                        continue
                    
                    # --- C. 检查长度是否足够 ---
                    if len(buffer) < target_len:
                        break # 数据不够，退出循环等待更多数据
                    
                    # --- D. 提取完整一帧 ---
                    frame = buffer[:target_len]
                    
                    # --- E. CRC 校验 ---
                    # 参与校验的数据是除了最后2字节CRC之外的所有数据
                    data_to_check = frame[:-2]
                    calc_crc = self.crc_calculator.calculate(data_to_check)
                    
                    # 提取接收到的CRC (大端序)
                    recv_crc = (frame[-2] << 8) | frame[-1]
                    
                    if calc_crc == recv_crc:
                        # === 校验通过，开始解析 ===
                        self._parse_frame(frame, pkt_type)
                        
                        # 移除已处理的一帧
                        buffer = buffer[target_len:]
                    else:
                        # print(f"CRC Error: Calc {calc_crc:04X} != Rx {recv_crc:04X}")
                        # CRC 错，可能是假头，丢弃1字节重试
                        buffer = buffer[1:]

            except Exception as e:
                print(f"读取异常: {e}")
                time.sleep(0.1)

        ser.close()

    def _parse_frame(self, frame, pkt_type):
        try:
            # frame[0]: 0x06
            # frame[1]: 0x09
            # frame[2]: Type
            # frame[3]: Channel ID (NRF已+1)
            
            # 直接获取 Channel ID
            ch_id = frame[3]

            if pkt_type == 0x01:
                # === 波形包 (Type 0x01) ===
                # [4:8] Data (float, little-endian)
                val = struct.unpack('<f', frame[4:8])[0]
                
                # 发送波形数据，特征值为 None
                self.data_received.emit(ch_id, val, None)
                
            elif pkt_type == 0x02:
                # === 特征包 (Type 0x02) ===
                # [4:8]   Theta
                # [8:12]  Alpha
                # [12:16] Beta
                theta = struct.unpack('<f', frame[4:8])[0]
                alpha = struct.unpack('<f', frame[8:12])[0]
                beta  = struct.unpack('<f', frame[12:16])[0]
                
                features = {'theta': theta, 'alpha': alpha, 'beta': beta}
                
                # 发送特征数据，波形值为 None
                self.data_received.emit(ch_id, None, features)
                
        except Exception as e:
            print(f"解析内容错误: {e}")

# ==========================================
# 4. 主界面 (GUI)
# ==========================================
class EEGMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"EEG Monitor - {SERIAL_PORT}")
        self.resize(1200, 800)

        # 数据缓存
        self.data_buffers = {1: deque(maxlen=BUFFER_SIZE), 
                             2: deque(maxlen=BUFFER_SIZE), 
                             3: deque(maxlen=BUFFER_SIZE)}
        self.sample_counters = {1: 0, 2: 0, 3: 0}
        
        # 特征值缓存 (默认显示0)
        self.latest_features = {1: {'theta':0, 'alpha':0, 'beta':0}, 
                                2: {'theta':0, 'alpha':0, 'beta':0}, 
                                3: {'theta':0, 'alpha':0, 'beta':0}}

        self._init_ui()

        # 启动串口线程
        self.worker = SerialWorker(SERIAL_PORT, BAUD_RATE)
        self.worker.data_received.connect(self.on_data_received)
        self.worker.start()

        # 绘图刷新定时器 (30ms -> ~33 FPS)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plots)
        self.timer.start(30) 

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # --- 顶部控制栏 ---
        control_panel = QHBoxLayout()
        control_panel.setContentsMargins(10, 10, 10, 10)
        
        self.chk_autoscroll = QCheckBox("自动滚屏 (Auto Scroll)")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.setStyleSheet("font-size: 14px; font-weight: bold; color: #00FF00;")
        control_panel.addWidget(self.chk_autoscroll)

        btn_clear = QPushButton("清除波形")
        btn_clear.setStyleSheet("background-color: #555; color: white;")
        btn_clear.clicked.connect(self.clear_data)
        control_panel.addWidget(btn_clear)
        
        control_panel.addStretch()
        layout.addLayout(control_panel)

        # --- 绘图区域 (3个通道) ---
        self.plots = {}
        self.curves = {}
        self.labels = {}
        colors = ['#00FF00', '#00FFFF', '#FFFF00'] # 绿, 青, 黄

        for ch_id in range(1, 4):
            row = QFrame()
            row.setFrameShape(QFrame.StyledPanel)
            row.setStyleSheet("background-color: #111; border: 1px solid #333; margin-bottom: 5px;")
            h_layout = QHBoxLayout(row)
            h_layout.setContentsMargins(5, 5, 5, 5)

            # 左侧：数值显示
            info_label = QLabel(f"<b>CH {ch_id}</b><br>等待数据...")
            info_label.setFixedWidth(140)
            info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            info_label.setStyleSheet(f"color: {colors[ch_id-1]}; font-size: 14px; padding: 5px;")
            self.labels[ch_id] = info_label
            h_layout.addWidget(info_label)

            # 右侧：波形显示
            plot_widget = pg.PlotWidget()
            plot_widget.setLabel('left', 'Amp', units='uV')
            plot_widget.showGrid(x=True, y=True, alpha=0.3)
            plot_widget.setBackground('#000000')
            
            curve = plot_widget.plot(pen=pg.mkPen(color=colors[ch_id-1], width=1.5))
            
            self.plots[ch_id] = plot_widget
            self.curves[ch_id] = curve
            
            h_layout.addWidget(plot_widget)
            layout.addWidget(row)

    def clear_data(self):
        for ch_id in self.data_buffers:
            self.data_buffers[ch_id].clear()
            self.sample_counters[ch_id] = 0

    def on_data_received(self, ch_id, raw_val, features):
        """
        处理接收到的数据
        - 如果 raw_val 不为 None，说明是波形包
        - 如果 features 不为 None，说明是特征包
        """
        # 简单过滤非法ID
        if ch_id not in self.data_buffers:
            return

        # 1. 处理波形
        if raw_val is not None:
            self.data_buffers[ch_id].append(raw_val)
            self.sample_counters[ch_id] += 1
        
        # 2. 处理特征值
        if features is not None:
            self.latest_features[ch_id] = features

    def update_plots(self):
        auto_scroll = self.chk_autoscroll.isChecked()

        for ch_id in range(1, 4):
            # --- 更新波形 ---
            buffer = self.data_buffers[ch_id]
            if len(buffer) > 2:
                y_data = np.array(buffer)
                end_count = self.sample_counters[ch_id]
                start_count = end_count - len(buffer)
                x_data = (np.arange(len(buffer)) + start_count) / SAMPLE_RATE

                self.curves[ch_id].setData(x_data, y_data)

                if auto_scroll:
                    current_time = end_count / SAMPLE_RATE
                    self.plots[ch_id].setXRange(current_time - PLOT_WINDOW, current_time, padding=0)

            # --- 更新左侧数值 (从缓存中取最新值) ---
            feats = self.latest_features[ch_id]
            txt = (f"<span style='font-size:18px; font-weight:bold;'>CH {ch_id}</span><br>"
                   f"&theta;: {feats['theta']:.2f}<br>"
                   f"&alpha;: {feats['alpha']:.2f}<br>"
                   f"&beta; : {feats['beta']:.2f}")
            self.labels[ch_id].setText(txt)

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    pg.setConfigOption('antialias', True)
    window = EEGMainWindow()
    window.show()
    sys.exit(app.exec_())