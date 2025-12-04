# -*- coding: utf-8 -*-
"""
简化版MJPEG视频流 - 完全模仿 face_emotion.py 的逻辑
不使用多线程，直接在Generator中循环处理每一帧
这是最接近 face_emotion.py 的实现方式
"""

import cv2
import numpy as np
import os
import sys
from collections import deque

# 添加项目路径
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))

# 导入昇腾NPU推理
try:
    from ais_bench.infer.interface import InferSession
    NPU_AVAILABLE = True
    print("[SimpleMJPEG] 昇腾NPU环境可用")
except ImportError as e:
    NPU_AVAILABLE = False
    print(f"[SimpleMJPEG] 昇腾NPU环境不可用: {e}")
    InferSession = None

# === 常量配置（与 face_emotion.py 完全一致）===
CONFIDENCE_THRES = 0.4
IOU_THRES = 0.45
EMOTION_LABELS = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']
EMOTION_INPUT_SIZE = (48, 48)
SMOOTHING_WINDOW_SIZE = 5

# 表情中文映射
EMOTION_CHINESE = {
    'Angry': '愤怒', 'Disgust': '厌恶', 'Fear': '害怕',
    'Happy': '高兴', 'Sad': '悲伤', 'Surprise': '惊讶', 'Neutral': '自然'
}

# 模型路径
DET_MODEL_PATH = os.path.join(project_root, "models", "yolov8s.om")
EMOTION_MODEL_PATH = os.path.join(project_root, "models", "48model.om")

# 全局变量 - 模型会话（单例）
_det_session = None
_emo_session = None
_model_loaded = False

# 全局摄像头对象
_global_cap = None
_stream_active = False

# 全局统计
emotion_stats = {label.lower(): 0 for label in EMOTION_LABELS}
total_detections = 0


def load_models():
    """加载模型（单例模式，只加载一次）"""
    global _det_session, _emo_session, _model_loaded
    
    # 检查模型是否已加载且会话对象有效
    if _model_loaded and _det_session is not None and _emo_session is not None:
        print("[SimpleMJPEG] 模型已加载，跳过")
        return True
    
    if not NPU_AVAILABLE:
        print("[SimpleMJPEG] NPU不可用")
        return False
    
    try:
        # 如果之前的会话还存在，先清理
        if _det_session is not None:
            print("[SimpleMJPEG] 清理旧的人脸检测会话")
            del _det_session
            _det_session = None
        
        if _emo_session is not None:
            print("[SimpleMJPEG] 清理旧的表情识别会话")
            del _emo_session
            _emo_session = None
        
        print(f"[SimpleMJPEG] 加载人脸检测模型: {DET_MODEL_PATH}")
        if not os.path.exists(DET_MODEL_PATH):
            print(f"[SimpleMJPEG] 模型文件不存在: {DET_MODEL_PATH}")
            return False
        
        print(f"[SimpleMJPEG] 加载表情识别模型: {EMOTION_MODEL_PATH}")
        if not os.path.exists(EMOTION_MODEL_PATH):
            print(f"[SimpleMJPEG] 模型文件不存在: {EMOTION_MODEL_PATH}")
            return False
        
        _det_session = InferSession(device_id=0, model_path=DET_MODEL_PATH)
        _emo_session = InferSession(device_id=0, model_path=EMOTION_MODEL_PATH)
        _model_loaded = True
        
        print("[SimpleMJPEG] 模型加载成功！")
        return True
        
    except Exception as e:
        print(f"[SimpleMJPEG] 模型加载失败: {e}")
        import traceback
        traceback.print_exc()
        _model_loaded = False
        return False


def preprocess_face_for_emotion(frame, box, target_size):
    """
    预处理人脸图像用于表情识别（与 face_emotion.py 完全一致）
    """
    x, y, w, h = box
    
    PADDING_RATIO = 0.10
    pad_w = int(w * PADDING_RATIO)
    pad_h = int(h * PADDING_RATIO)
    
    x_min = round(x - pad_w)
    y_min = round(y - pad_h)
    x_max = round(x + w + pad_w)
    y_max = round(y + h + pad_h)
    
    x_min, y_min = max(0, x_min), max(0, y_min)
    x_max, y_max = min(frame.shape[1], x_max), min(frame.shape[0], y_max)
    
    cropped_face = frame[y_min:y_max, x_min:x_max]
    
    if cropped_face.size == 0 or x_max <= x_min or y_max <= y_min:
        return None, None
    
    gray_face = cv2.cvtColor(cropped_face, cv2.COLOR_BGR2GRAY)
    resized_face = cv2.resize(gray_face, target_size, interpolation=cv2.INTER_LINEAR)
    normalized_face = resized_face.astype(np.float32) / 255.0
    input_blob = np.expand_dims(np.expand_dims(normalized_face, axis=0), axis=0)
    
    return input_blob, (x_min, y_min, x_max, y_max)


def run_emotion_inference(emotion_session, face_blob):
    """运行表情推理（与 face_emotion.py 完全一致）"""
    outputs = emotion_session.infer(feeds=face_blob, mode="static")
    return outputs[0][0]


def draw_bounding_box(img, label_text, color_id, x, y, x_plus_w, y_plus_h):
    """绘制检测框（与 face_emotion.py 完全一致）"""
    colors = np.array([[0, 255, 0]])
    color = colors[color_id]
    
    cv2.rectangle(img, (x, y), (x_plus_w, y_plus_h), color.tolist(), 2)
    
    label_size, _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    label_height = label_size[1]
    label_x = x
    label_y = y - 10 if y - 10 > label_height else y + 15
    
    cv2.putText(img, label_text, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 2, cv2.LINE_AA)


def run_combined_pipeline(det_session, emo_session, original_image, history):
    """
    执行完整的人脸检测和表情识别流程（与 face_emotion.py 完全一致）
    """
    global emotion_stats, total_detections
    
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
    
    detections = []
    
    if len(indices) > 0:
        for i in indices:
            index = i.item() if hasattr(i, 'item') else int(i)
            box = boxes[index]
            det_class_id = class_ids[index]

            face_blob, padded_coords = preprocess_face_for_emotion(original_image, box, EMOTION_INPUT_SIZE)
            
            if face_blob is not None and padded_coords is not None:
                x_min, y_min, x_max, y_max = padded_coords
                
                raw_scores = run_emotion_inference(emo_session, face_blob)
                
                exp_scores = np.exp(raw_scores - np.max(raw_scores))
                probabilities = exp_scores / np.sum(exp_scores)
                
                history.append(probabilities)
                smoothed_probabilities = np.mean(history, axis=0)
                
                emotion_index = np.argmax(smoothed_probabilities)
                emotion_label = EMOTION_LABELS[emotion_index]
                emotion_conf = smoothed_probabilities[emotion_index]
                
                # 更新统计
                emotion_stats[emotion_label.lower()] += 1
                total_detections += 1
                
                full_label = f"{emotion_label}:{emotion_conf:.2f}"
            else:
                x_min, y_min, x_max, y_max = round(box[0]), round(box[1]), round(box[0] + box[2]), round(box[1] + box[3])
                full_label = "Emo Failed"
            
            detections.append({
                "class_id": det_class_id, 
                "confidence": scores[index], 
                "box": (x_min, y_min, x_max, y_max), 
                "emotion": full_label
            })
            
            draw_bounding_box(original_image, full_label, det_class_id, x_min, y_min, x_max, y_max)
    
    cv2.putText(original_image, "NPU MJPEG", (10, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 1, cv2.LINE_AA)
        
    return original_image, detections, history


def stop_stream():
    """主动停止流并释放摄像头"""
    global _global_cap, _stream_active, _det_session, _emo_session, _model_loaded
    
    _stream_active = False
    
    if _global_cap is not None:
        try:
            _global_cap.release()
            print("[SimpleMJPEG] 摄像头已主动释放")
        except:
            pass
        _global_cap = None
    
    # 清理NPU会话，避免context失效
    try:
        if _det_session is not None:
            del _det_session
            _det_session = None
            print("[SimpleMJPEG] 人脸检测会话已清理")
        
        if _emo_session is not None:
            del _emo_session
            _emo_session = None
            print("[SimpleMJPEG] 表情识别会话已清理")
        
        _model_loaded = False
    except Exception as e:
        print(f"[SimpleMJPEG] 清理NPU会话失败: {e}")
    
    print("[SimpleMJPEG] 视频流已停止")


def generate_mjpeg_frames():
    """
    生成MJPEG视频流帧 - 完全模仿 face_emotion.py 的主循环
    
    关键优化：
    1. 使用全局摄像头对象，避免重复打开
    2. 使用 cap.grab() + cap.retrieve() 确保获取最新帧
    3. 不使用 sleep，让循环自然运行
    4. 单线程处理，避免同步问题
    """
    global _det_session, _emo_session, _global_cap, _stream_active
    
    print("[SimpleMJPEG] generate_mjpeg_frames() 被调用")
    
    # 如果之前的流还在运行，先停止
    if _stream_active:
        print("[SimpleMJPEG] 检测到旧的流还在运行，先停止...")
        stop_stream()
        import time
        time.sleep(0.8)  # 等待旧流完全停止
    
    # 加载模型（如果被清理了，会重新加载）
    if not load_models():
        # 返回错误帧
        print("[SimpleMJPEG] 模型加载失败，返回错误帧")
        error_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(error_frame, "Model Load Failed", (30, 120), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        _, buffer = cv2.imencode('.jpg', error_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        return
    
    # 初始化摄像头 - 使用全局对象
    CAMERA_SOURCE = 0
    WIDTH = 320
    HEIGHT = 240
    
    # 如果摄像头已经被占用，先释放
    if _global_cap is not None:
        print("[SimpleMJPEG] 检测到摄像头已打开，先释放...")
        try:
            _global_cap.release()
        except:
            pass
        _global_cap = None
        import time
        time.sleep(0.5)  # 等待摄像头完全释放
    
    # 打开摄像头
    _global_cap = cv2.VideoCapture(CAMERA_SOURCE)
    if not _global_cap.isOpened():
        print("[SimpleMJPEG] 摄像头打开失败")
        error_frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        cv2.putText(error_frame, "Camera Error", (60, 120), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        _, buffer = cv2.imencode('.jpg', error_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        _global_cap = None
        return
    
    # 摄像头优化设置 - 与 face_emotion.py 完全一致
    _global_cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    _global_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    try:
        _global_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        _global_cap.set(cv2.CAP_PROP_FPS, 30.0)
        _global_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except:
        pass
    
    print("[SimpleMJPEG] 开始视频流生成...")
    _stream_active = True
    
    # 表情历史记录
    emotion_history = deque(maxlen=SMOOTHING_WINDOW_SIZE)
    
    # JPEG编码参数
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 80]
    
    # 帧计数器（用于调试）
    frame_count = 0
    
    try:
        # 主循环 - 与 face_emotion.py 的 while True 完全对应
        while _stream_active:
            # 关键优化：先grab丢弃旧帧，再retrieve获取最新帧
            # 这样可以确保我们总是处理最新的帧
            _global_cap.grab()  # 丢弃缓冲区中的旧帧
            success, frame = _global_cap.retrieve()
            
            frame_count += 1
            if frame_count % 30 == 0:  # 每30帧输出一次日志
                print(f"[SimpleMJPEG] 已处理 {frame_count} 帧")
            
            if not success:
                # 如果retrieve失败，尝试普通read
                success, frame = _global_cap.read()
                if not success:
                    continue
            
            # 运行完整的检测流程 - 与 face_emotion.py 完全一致
            draw_image, detections, emotion_history = run_combined_pipeline(
                _det_session, _emo_session, frame, emotion_history
            )
            
            # 编码为JPEG并输出
            success_encode, buffer = cv2.imencode('.jpg', draw_image, encode_params)
            
            if success_encode:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            
            # 注意：不使用 time.sleep()，让循环自然运行
            # 这样可以最大化帧率，与 face_emotion.py 一致
            
    except GeneratorExit:
        print("[SimpleMJPEG] 客户端断开连接")
    except Exception as e:
        print(f"[SimpleMJPEG] 流生成错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if _global_cap is not None:
            _global_cap.release()
            _global_cap = None
        _stream_active = False
        print("[SimpleMJPEG] 摄像头已释放")


def get_statistics():
    """获取统计数据"""
    global emotion_stats, total_detections
    
    total = max(1, total_detections)
    stats = {}
    for emotion, count in emotion_stats.items():
        stats[emotion] = {
            'count': count,
            'percentage': (count / total) * 100
        }
    
    return {
        'total_detections': total_detections,
        'emotions': stats,
        'most_common': max(emotion_stats.items(), key=lambda x: x[1])[0] if total_detections > 0 else 'neutral'
    }


def reset_statistics():
    """重置统计"""
    global emotion_stats, total_detections
    emotion_stats = {label.lower(): 0 for label in EMOTION_LABELS}
    total_detections = 0
    print("[SimpleMJPEG] 统计数据已重置")


def cleanup():
    """清理资源"""
    global _det_session, _emo_session, _model_loaded
    
    try:
        if _det_session:
            del _det_session
            _det_session = None
        if _emo_session:
            del _emo_session
            _emo_session = None
        _model_loaded = False
        print("[SimpleMJPEG] 资源已清理")
    except Exception as e:
        print(f"[SimpleMJPEG] 清理失败: {e}")

