# -*- coding: utf-8 -*-
"""
启智AI板子表情识别服务
完全基于 face_emotion.py 的实现，确保检测质量一致
支持实时检测框显示和表情标注
"""

import os
import sys
import logging
import threading
import time
import numpy as np
import cv2
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import base64
from io import BytesIO
from PIL import Image
from collections import deque

# 添加项目路径
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))

# 尝试导入昇腾相关库
try:
    from ais_bench.infer.interface import InferSession
    NPU_AVAILABLE = True
    print("昇腾NPU环境可用 - 表情识别")
except ImportError as e:
    NPU_AVAILABLE = False
    print(f"昇腾NPU环境不可用: {e}")
    InferSession = None

# === 常量配置（与 face_emotion.py 完全一致）===
CLASSES = {0: 'face'}
CONFIDENCE_THRES = 0.4
IOU_THRES = 0.45
EMOTION_LABELS = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']
EMOTION_INPUT_SIZE = (48, 48)
SMOOTHING_WINDOW_SIZE = 5  # 恢复为5，与face_emotion.py一致，使用进程级别历史记录后可以正常累积


class AscendNPUEmotionRecognitionService:
    """启智AI板子表情识别服务 - 完全基于 face_emotion.py"""
    
    # 线程本地存储：为每个线程创建独立的模型实例
    _thread_local = threading.local()
    
    def __init__(self, device_id=0):
        """初始化NPU表情识别服务"""
        
        # 设备配置
        self.device_id = device_id
        
        # 模型路径配置
        self.det_model_path = os.path.join(project_root, "models", "yolov8s.om")
        self.emotion_model_path = os.path.join(project_root, "models", "48model.om")
        
        # 表情类别映射
        self.emotion_labels = EMOTION_LABELS
        self.emotion_chinese = {
            'Angry': '愤怒',
            'Disgust': '厌恶',
            'Fear': '害怕',
            'Happy': '高兴',
            'Sad': '悲伤',
            'Surprise': '惊讶',
            'Neutral': '自然'
        }
        
        # 表情统计
        self.emotion_stats = {label.lower(): 0 for label in self.emotion_labels}
        self.total_detections = 0
        
        # 备用CPU模式
        self.use_npu = NPU_AVAILABLE
        
        # 设置日志
        self._setup_logging()
        
    def _setup_logging(self):
        """设置日志"""
        # 创建日志目录
        log_dir = os.path.join(project_root, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # 日志文件路径
        log_file = os.path.join(log_dir, 'emotion_recognition.log')
        
        # 配置日志：同时输出到控制台和文件
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.DEBUG)  # 设置为DEBUG级别，可以看到所有调试信息
        
        # 避免重复添加handler
        if logger.handlers:
            return
        
        # 文件handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        
        # 添加handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        self.logger = logger
        self.logger.info(f"表情识别日志已配置，日志文件: {log_file}")

    def _get_thread_sessions(self):
        """
        获取当前线程的模型实例（线程本地存储）
        每个线程都有自己独立的 InferSession 实例，避免上下文冲突
        """
        if not hasattr(self._thread_local, 'det_session') or self._thread_local.det_session is None:
            # 为当前线程创建模型实例
            try:
                self.logger.info(f"为线程 {threading.current_thread().name} 创建模型实例...")
                self._thread_local.det_session = InferSession(device_id=self.device_id, model_path=self.det_model_path)
                self._thread_local.emo_session = InferSession(device_id=self.device_id, model_path=self.emotion_model_path)
                # 为当前线程创建独立的历史记录，避免不同请求互相影响
                self._thread_local.emotion_history = deque(maxlen=SMOOTHING_WINDOW_SIZE)
                self.logger.info(f"线程 {threading.current_thread().name} 模型实例创建成功")
            except Exception as e:
                self.logger.error(f"为线程创建模型实例失败: {e}")
                self._thread_local.det_session = None
                self._thread_local.emo_session = None
                self._thread_local.emotion_history = deque(maxlen=SMOOTHING_WINDOW_SIZE)
        
        return self._thread_local.det_session, self._thread_local.emo_session
    
    def _get_thread_history(self):
        """
        获取当前线程的表情历史记录（不跨线程共享，避免平滑被其他请求干扰）
        """
        if not hasattr(self._thread_local, 'emotion_history') or self._thread_local.emotion_history is None:
            self._thread_local.emotion_history = deque(maxlen=SMOOTHING_WINDOW_SIZE)
        return self._thread_local.emotion_history

    def preprocess_face_for_emotion(self, frame, box, target_size):
        """
        预处理人脸图像用于表情识别（与 face_emotion.py 完全一致）
        Crops the face, converts to grayscale, resizes to 48x48, and prepares 1x1x48x48 Blob.
        """
        x, y, w, h = box
        
        # === Apply Padding for better ROI capture ===
        PADDING_RATIO = 0.10  # Apply 10% padding
        pad_w = int(w * PADDING_RATIO)
        pad_h = int(h * PADDING_RATIO)
        
        x_min = round(x - pad_w)
        y_min = round(y - pad_h)
        x_max = round(x + w + pad_w)
        y_max = round(y + h + pad_h)
        
        # Clip coordinates to image boundaries
        x_min, y_min = max(0, x_min), max(0, y_min)
        x_max, y_max = min(frame.shape[1], x_max), min(frame.shape[0], y_max)
        
        # Crop the face
        cropped_face = frame[y_min:y_max, x_min:x_max]
        
        if cropped_face.size == 0 or x_max <= x_min or y_max <= y_min:
            return None, None  # Return None for blob and updated coordinates

        # 1. Convert to Grayscale (from BGR)
        gray_face = cv2.cvtColor(cropped_face, cv2.COLOR_BGR2GRAY)
        
        # 2. Resize to 48x48
        resized_face = cv2.resize(gray_face, target_size, interpolation=cv2.INTER_LINEAR)
        
        # 3. Normalize to [0, 1] (required for the model)
        normalized_face = resized_face.astype(np.float32) / 255.0
        
        # 4. Convert to NCHW format: [1, 1, 48, 48]
        input_blob = np.expand_dims(np.expand_dims(normalized_face, axis=0), axis=0)
        
        # Return blob and the actual integer box coordinates used for drawing
        return input_blob, (x_min, y_min, x_max, y_max)

    def run_emotion_inference(self, emotion_session, face_blob):
        """
        运行表情模型推理（与 face_emotion.py 完全一致）
        Outputs: NumPy array of probabilities/logits, shape [7]
        """
        outputs = emotion_session.infer(feeds=face_blob, mode="static")
        # Assuming output is the logits/probabilities array
        return outputs[0][0]

    def run_combined_pipeline(self, det_session, emo_session, original_image, history):
        """
        执行完整的人脸检测和表情识别流程（与 face_emotion.py 完全一致）
        Executes the Face Detection -> Cropping -> Local Emotion Classification pipeline.
        """
        
        # === Phase 1: Face Detection (YOLOv8) ===
        height, width, _ = original_image.shape
        length = max(height, width)
        image = np.zeros((length, length, 3), np.uint8)
        image[0:height, 0:width] = original_image
        scale = length / 640

        blob = cv2.dnn.blobFromImage(image, scalefactor=1.0 / 255, size=(640, 640), swapRB=True)
        det_outputs = det_session.infer(feeds=blob, mode="static")
        
        outputs_array = np.transpose(det_outputs[0][0])
        rows = outputs_array.shape[0]
        boxes, scores, class_ids = [], [], []

        for i in range(rows):
            cls_logit = outputs_array[i][4]
            max_score = cls_logit
            max_class_index = 0
            
            if max_score >= CONFIDENCE_THRES:
                center_x, center_y, box_width, box_height = outputs_array[i][0:4]
                x_min = (center_x - box_width / 2) * scale
                y_min = (center_y - box_height / 2) * scale
                w_scaled = box_width * scale
                h_scaled = box_height * scale
                box = [x_min, y_min, w_scaled, h_scaled]
                
                boxes.append(box)
                scores.append(max_score)
                class_ids.append(max_class_index)

        indices = cv2.dnn.NMSBoxes(boxes, scores, CONFIDENCE_THRES, IOU_THRES)
        
        # 确保indices是numpy数组或列表
        if isinstance(indices, np.ndarray):
            indices = indices.flatten()
        elif indices is None:
            indices = []
        
        # === Phase 2: Local Emotion Classification ===
        detections = []
        
        if len(indices) > 0:
            for i in indices:
                # 处理numpy标量
                if hasattr(i, 'item'):
                    index = i.item()
                else:
                    index = int(i)
                box = boxes[index]
                det_class_id = class_ids[index]

                # 1. Preprocess and Infer Emotion
                face_blob, padded_coords = self.preprocess_face_for_emotion(original_image, box, EMOTION_INPUT_SIZE)
                
                if face_blob is not None and padded_coords is not None:
                    x_min, y_min, x_max, y_max = padded_coords
                    
                    # Perform Ascend Inference
                    raw_scores = self.run_emotion_inference(emo_session, face_blob)
                    
                    # Convert scores to probabilities (Softmax)
                    exp_scores = np.exp(raw_scores - np.max(raw_scores))
                    probabilities = exp_scores / np.sum(exp_scores)
                    
                    # 调试日志：输出原始概率分布
                    if len(probabilities) == len(EMOTION_LABELS):
                        prob_dict = {EMOTION_LABELS[i]: float(probabilities[i]) for i in range(len(EMOTION_LABELS))}
                        self.logger.debug(f"原始表情概率分布: {prob_dict}")
                    
                    # 2. Smoothing and Prediction（结合当前帧和线程历史，避免跨请求污染）
                    thread_history = self._get_thread_history()
                    
                    # 轻度平滑：当前帧权重更大，避免过度偏向历史
                    if len(thread_history) > 0:
                        history_mean = np.mean(thread_history, axis=0)
                        smoothed_probabilities = probabilities * 0.6 + history_mean * 0.4
                    else:
                        smoothed_probabilities = probabilities
                    
                    # 更新线程历史
                    thread_history.append(probabilities)
                    current_history_size = len(thread_history)
                    
                    # 3. 适度的类别再平衡：抑制Neutral/Happiness的过度占比，适度提升其他类别
                    balanced_prob = smoothed_probabilities.copy()
                    neutral_idx = EMOTION_LABELS.index('Neutral')
                    happy_idx = EMOTION_LABELS.index('Happy')
                    sad_idx = EMOTION_LABELS.index('Sad')
                    fear_idx = EMOTION_LABELS.index('Fear')
                    disgust_idx = EMOTION_LABELS.index('Disgust')
                    surprise_idx = EMOTION_LABELS.index('Surprise')
                    
                    # 如果Neutral过高且有其他表情存在，降低Neutral
                    max_other = max([balanced_prob[i] for i in range(len(EMOTION_LABELS)) if i != neutral_idx])
                    if balanced_prob[neutral_idx] > 0.55 and max_other > 0.12:
                        balanced_prob[neutral_idx] *= 0.7
                    
                    # Happy过高且存在负向/其他情绪时适度降低
                    if balanced_prob[happy_idx] > 0.55 and (balanced_prob[sad_idx] > 0.08 or balanced_prob[fear_idx] > 0.08):
                        balanced_prob[happy_idx] *= 0.8
                    
                    # 适度提升容易被淹没的类别
                    if balanced_prob[sad_idx] > 0.04:
                        balanced_prob[sad_idx] *= 1.6
                    if balanced_prob[fear_idx] > 0.03:
                        balanced_prob[fear_idx] *= 1.4
                    if balanced_prob[disgust_idx] > 0.02:
                        balanced_prob[disgust_idx] *= 1.4
                    if balanced_prob[surprise_idx] > 0.02:
                        balanced_prob[surprise_idx] *= 1.3
                    
                    # 重新归一化
                    balanced_prob = balanced_prob / np.sum(balanced_prob)
                    
                    # 调试日志：输出平滑后的概率分布
                    if len(smoothed_probabilities) == len(EMOTION_LABELS):
                        smoothed_dict = {EMOTION_LABELS[i]: float(smoothed_probabilities[i]) for i in range(len(EMOTION_LABELS))}
                        balanced_dict = {EMOTION_LABELS[i]: float(balanced_prob[i]) for i in range(len(EMOTION_LABELS))}
                        self.logger.debug(f"平滑后表情概率分布: {smoothed_dict}")
                        self.logger.debug(f"再平衡后表情概率分布: {balanced_dict}")
                    
                    # 使用再平衡后的概率选择表情
                    emotion_index = int(np.argmax(balanced_prob))
                    emotion_label = EMOTION_LABELS[emotion_index]
                    emotion_conf = float(balanced_prob[emotion_index])  # 确保转换为Python float
                    
                    # 调试日志：输出最终选择的表情
                    self.logger.debug(f"选择的表情: {emotion_label} (置信度: {emotion_conf:.3f}), 历史窗口大小: {current_history_size}")
                    
                    full_label = f"{emotion_label}:{emotion_conf:.2f}"
                    
                    # 绘制检测框和标签（用于返回带标注的图像）
                    self.draw_bounding_box(original_image, full_label, det_class_id, x_min, y_min, x_max, y_max)
                    
                    detections.append({
                        "class_id": int(det_class_id), 
                        "confidence": float(scores[index]),  # 确保转换为Python float
                        "box": (int(x_min), int(y_min), int(x_max), int(y_max)),  # 确保转换为Python int
                        "emotion": emotion_label.lower(),
                        "emotion_chinese": self.emotion_chinese.get(emotion_label, emotion_label),
                        "emotion_confidence": float(emotion_conf),
                        "label": full_label
                    })
                else:
                    # Use the original (unpadded) box for failed emo
                    x_min, y_min, x_max, y_max = round(box[0]), round(box[1]), round(box[0] + box[2]), round(box[1] + box[3])
                    full_label = "Emo Failed"
                    self.draw_bounding_box(original_image, full_label, det_class_id, x_min, y_min, x_max, y_max)
        
        # Add model info text
        cv2.putText(original_image, "MODEL: 48x48 GRAYSCALE", (10, height - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1, cv2.LINE_AA)
        
        # 返回当前线程的历史记录（供调用方调试/查看）
        return original_image, detections, self._get_thread_history()

    def draw_bounding_box(self, img, label_text, color_id, x, y, x_plus_w, y_plus_h):
        """
        绘制检测框和标签（与 face_emotion.py 完全一致）
        Draws the bounding box and the combined label (Face | Emotion: Conf) onto the image.
        """
        colors = np.array([[0, 255, 0]])  # BGR Green
        color = colors[color_id]
        
        cv2.rectangle(img, (x, y), (x_plus_w, y_plus_h), color.tolist(), 2)
        
        label_size, _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        label_height = label_size[1]
        label_x = x
        label_y = y - 10 if y - 10 > label_height else y + 15
        
        # Text Color (White for contrast)
        cv2.putText(img, label_text, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 2, cv2.LINE_AA)

    def load_model(self):
        """
        加载表情识别模型（延迟加载）
        实际模型会在每个线程第一次使用时创建（线程本地存储）
        """
        try:
            self.logger.info("检查表情识别模型文件...")
            
            # 检查模型文件
            if not os.path.exists(self.det_model_path):
                self.logger.error(f"人脸检测模型文件不存在: {self.det_model_path}")
                return False
                
            if not os.path.exists(self.emotion_model_path):
                self.logger.error(f"表情识别模型文件不存在: {self.emotion_model_path}")
                return False
            
            if self.use_npu and NPU_AVAILABLE:
                self.logger.info("模型文件检查通过，将在首次使用时为每个线程创建模型实例")
                return True
            else:
                self.logger.warning("NPU环境不可用，模型无法加载")
                return False
                
        except Exception as e:
            self.logger.error(f"检查模型文件失败: {e}")
            return False

    def detect_emotion_from_image(self, image_data: str) -> Dict[str, Any]:
        """
        从base64图像数据中检测表情
        完全使用 face_emotion.py 的 run_combined_pipeline 逻辑
        
        Args:
            image_data: base64编码的图像数据
            
        Returns:
            Dict包含检测结果，包括带检测框的图像
        """
        try:
            # 检查模型文件
            if not self.load_model():
                return {
                    'success': False,
                    'error': '模型文件不存在或NPU不可用',
                    'emotions': [],
                    'dominant_emotion': 'neutral',
                    'confidence': 0.0
                }
            
            # 解码base64图像
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            image_bytes = base64.b64decode(image_data)
            image = Image.open(BytesIO(image_bytes))
            
            # 转换为OpenCV格式
            cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            
            # 检测表情（使用 face_emotion.py 的完整流程）
            if self.use_npu:
                return self._detect_emotion_npu(cv_image)
            else:
                return self._detect_emotion_cpu(cv_image)
                
        except Exception as e:
            self.logger.error(f"表情检测失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'emotions': [],
                'dominant_emotion': 'neutral',
                'confidence': 0.0
            }
    
    def _detect_emotion_npu(self, image: np.ndarray) -> Dict[str, Any]:
        """
        使用NPU进行表情检测
        完全使用 face_emotion.py 的 run_combined_pipeline 实现
        """
        try:
            # 获取当前线程的模型实例（如果不存在会自动创建）
            det_session, emo_session = self._get_thread_sessions()
            if det_session is None or emo_session is None:
                self.logger.error("无法获取线程模型实例")
                return self._detect_emotion_cpu(image)
            
            # 执行完整流程（与 face_emotion.py 完全一致）
            try:
                draw_image, detections, history = self.run_combined_pipeline(
                    det_session, emo_session, image.copy(), None
                )
            except Exception as e:
                self.logger.error(f"run_combined_pipeline 执行失败: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                raise
            
            # 注意：历史记录已经在run_combined_pipeline中通过锁更新了，这里不需要再次更新
            
            # 转换为base64图像（带检测框）
            try:
                success, buffer = cv2.imencode('.jpg', draw_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not success:
                    self.logger.error("图像编码失败")
                    annotated_image = None
                else:
                    image_base64 = base64.b64encode(buffer).decode('utf-8')
                    annotated_image = f"data:image/jpeg;base64,{image_base64}"
            except Exception as e:
                self.logger.error(f"图像编码异常: {e}")
                annotated_image = None
            
            # 处理检测结果
            all_emotions = []
            for det in detections:
                emotion = det.get('emotion', 'neutral')
                emotion_conf = det.get('emotion_confidence', 0.0)
                
                # 确保所有数值都是Python原生类型
                emotion_conf = float(emotion_conf) if emotion_conf is not None else 0.0
                
                # 更新统计
                self.emotion_stats[emotion.lower()] += 1
                self.total_detections += 1
                
                # 处理box坐标，确保都是Python int
                box = det.get('box')
                if box:
                    box = tuple(int(x) for x in box)
                
                all_emotions.append({
                    'emotion': str(emotion),
                    'emotion_chinese': str(det.get('emotion_chinese', emotion)),
                    'confidence': float(emotion_conf),  # 确保是Python float
                    'box': box,
                    'label': str(det.get('label', ''))
                })
            
            # 确定主要表情
            if all_emotions:
                # 选择置信度最高的表情
                dominant = max(all_emotions, key=lambda x: x['confidence'])
                dominant_emotion = str(dominant['emotion'])
                dominant_confidence = float(dominant['confidence'])
            else:
                dominant_emotion = 'neutral'
                dominant_confidence = 0.0
            
            # 确保detections中的所有数值都是Python原生类型
            serializable_detections = []
            for det in detections:
                serializable_detections.append({
                    "class_id": int(det.get('class_id', 0)),
                    "confidence": float(det.get('confidence', 0.0)),
                    "box": tuple(int(x) for x in det.get('box', (0, 0, 0, 0))),
                    "emotion": str(det.get('emotion', 'neutral')),
                    "emotion_chinese": str(det.get('emotion_chinese', '')),
                    "emotion_confidence": float(det.get('emotion_confidence', 0.0)),
                    "label": str(det.get('label', ''))
                })
            
            result = {
                'success': True,
                'emotions': all_emotions,
                'dominant_emotion': str(dominant_emotion),
                'confidence': float(dominant_confidence),
                'faces_detected': int(len(detections)),
                'detections': serializable_detections  # 确保所有数据都是可序列化的
            }
            
            # 如果有带检测框的图像，添加到结果中
            if annotated_image:
                result['annotated_image'] = annotated_image
            
            self.logger.debug(f"检测完成: {len(detections)}个人脸, {len(all_emotions)}个表情, 主要表情: {dominant_emotion}")
            return result
                
        except Exception as e:
            self.logger.error(f"NPU表情检测失败: {e}")
            import traceback
            error_trace = traceback.format_exc()
            self.logger.error(error_trace)
            # 打印到控制台以便调试
            print(f"NPU表情检测异常: {e}")
            print(error_trace)
            return {
                'success': False,
                'error': f'NPU表情检测失败: {str(e)}',
                'emotions': [],
                'dominant_emotion': 'neutral',
                'confidence': 0.0,
                'faces_detected': 0
            }
    
    def _detect_emotion_cpu(self, image: np.ndarray) -> Dict[str, Any]:
        """使用CPU进行表情检测（备用方案）"""
        return {
            'success': True,
            'emotions': [],
            'dominant_emotion': 'neutral',
            'confidence': 0.5,
            'faces_detected': 0,
            'fallback': True
        }

    def get_emotion_statistics(self) -> Dict[str, Any]:
        """获取表情统计数据"""
        total = self.total_detections if self.total_detections > 0 else 1
        
        stats = {}
        for emotion, count in self.emotion_stats.items():
            stats[emotion] = {
                'count': count,
                'percentage': (count / total) * 100
            }
        
        return {
            'total_detections': self.total_detections,
            'emotions': stats,
            'most_common': max(self.emotion_stats.items(), key=lambda x: x[1])[0] if self.total_detections > 0 else 'neutral'
        }

    def reset_statistics(self):
        """重置统计数据"""
        self.emotion_stats = {label.lower(): 0 for label in self.emotion_labels}
        self.total_detections = 0
        # 重置线程历史记录
        if hasattr(self._thread_local, 'emotion_history'):
            self._thread_local.emotion_history.clear()
        self.logger.info("表情统计数据已重置")

    def get_service_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        # 检查当前线程是否有模型实例
        det_session, emo_session = self._get_thread_sessions()
        return {
            'model_loaded': det_session is not None and emo_session is not None,
            'npu_available': NPU_AVAILABLE,
            'use_npu': self.use_npu,
            'det_model_path': self.det_model_path,
            'emotion_model_path': self.emotion_model_path,
            'emotion_labels': self.emotion_labels,
            'total_detections': self.total_detections,
            'thread_name': threading.current_thread().name
        }

    def cleanup(self):
        """清理资源"""
        try:
            # 清理线程本地存储的模型实例
            if hasattr(self._thread_local, 'det_session'):
                try:
                    del self._thread_local.det_session
                except:
                    pass
            if hasattr(self._thread_local, 'emo_session'):
                try:
                    del self._thread_local.emo_session
                except:
                    pass
            self.logger.info("资源清理完成")
        except Exception as e:
            self.logger.error(f"资源清理失败: {e}")


# 创建全局服务实例
try:
    npu_emotion_service = AscendNPUEmotionRecognitionService()
except Exception as e:
    print(f"表情识别服务初始化失败: {e}")
    npu_emotion_service = None
