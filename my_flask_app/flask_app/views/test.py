from flask import Blueprint, session, render_template, request, redirect, jsonify, Response
import datetime
import json
import cv2
import numpy as np
import time

from utils import db
# 使用NPU加速的语音识别服务
from utils.speech_recognition_npu import npu_speech_service as speech_service
print("使用NPU加速的语音识别服务")

def get_beijing_time():
    """获取北京时间 - 直接使用系统时间（系统已配置为UTC+8）"""
    # 系统本地时间已经是北京时间，直接返回
    beijing_time = datetime.datetime.now()
    
    # 强制调试信息 - 确保看到正确的时间
    print("=" * 60)
    print(f"!!! GET_BEIJING_TIME 被调用 !!!")
    print(f"返回时间: {beijing_time}")
    print(f"这应该是当前北京时间！如果不是，说明代码没有重新加载！")
    print("=" * 60)
    
    return beijing_time

# 模块加载时打印信息
print("\n" + "=" * 70)
print("✓✓✓ test.py 模块已重新加载 - get_beijing_time() 函数已更新！✓✓✓")
print(f"当前系统时间: {datetime.datetime.now()}")
print("=" * 70 + "\n")

try:
    # 导入NPU表情识别服务（用于统计数据等）
    from utils.emotion_recognition_npu import npu_emotion_service
    print("使用NPU加速的表情识别服务")
except ImportError as e:
    print(f"表情识别服务不可用: {e}")
    npu_emotion_service = None

# 导入简化版MJPEG视频流（完全模仿face_emotion.py）
try:
    from utils import simple_mjpeg_stream
    print("使用简化版MJPEG视频流服务（模仿face_emotion.py）")
except ImportError as e:
    print(f"简化版MJPEG视频流服务不可用: {e}")
    simple_mjpeg_stream = None

#蓝图对象
ts = Blueprint("test", __name__)

@ts.route('/SDS/debug', methods=["GET"])
def SDS_debug():
    """调试接口 - 检查session状态"""
    return jsonify({
        'userinfo': session.get("userinfo"),
        'test_id': session.get("test_id"),
        'session_keys': list(session.keys())
    })

@ts.route('/SDS', methods=["GET", "POST"])
def SDS():
    userinfo = session.get("userinfo")
    if not userinfo:
        return redirect('/login')
    
    now_time = get_beijing_time()
    test_id = db.insert("INSERT INTO test (role, user_id, start_time, status) VALUES (?, ?, ?, ?)", [1, userinfo['id'], now_time, "未完成"])

    session["test_id"] = test_id
    print(f"测评开始 - 用户ID: {userinfo['id']}, 测评ID: {test_id}, 北京时间: {now_time}")

    # 使用 SDS_working.html（使用 MJPEG 流，不使用 emotion-recognition.js）
    return render_template("SDS_working.html")

@ts.route('/SDS/submit', methods=["GET", "POST"])
def SDS_submit():
    test_id = session.get("test_id")

    # 获取前端发送的数据
    data = request.get_json()
    answers = data.get('answers')
    total_time = data.get('totalTime')
    finish_time = get_beijing_time()

    # 转为字符串答案answer
    answer = []
    for i in range(1, 21):
        key = str(i)
        if key in answers:
            answer.append(str(answers[key]['value']))
        else:
            answer.append('0')
    answer = ''.join(answer)

    # 计算分值和抑郁程度
    # 反向评分题题号（2,5,6,11,12,14,16,17,18,20）
    reverse_questions = {2, 5, 6, 11, 12, 14, 16, 17, 18, 20}

    total_raw_score = 0

    # 遍历1-20题
    for i in range(1, 21):
        key = str(i)
        if key in answers:
            value = answers[key]['value']
            # 检查是否为反向评分题
            if i in reverse_questions:
                # 反向评分：4->1, 3->2, 2->3, 1->4
                score = 5 - value  # 例如value=1时，score=5-1=4
            else:
                # 正向评分
                score = value
            total_raw_score += score
        else:
            # 若某题未回答，默认给0分（也可根据实际情况处理为缺失值）
            total_raw_score += 0

        # 方法二：计算标准分
        standard_score = int(total_raw_score * 1.25)

        # 根据标准分判断焦虑程度（注意：SDS主要评估抑郁，此处可能是用户口误）
        if standard_score < 50:
            anxiety_level = "无抑郁"
        elif 50 <= standard_score <= 60:
            anxiety_level = "轻度抑郁"
        elif 61 <= standard_score <= 70:
            anxiety_level = "中度抑郁"
        else:
            anxiety_level = "重度抑郁"

    finish_status = "未完成" if '0' in answer else "已完成"

    db.update("UPDATE test SET finish_time = ?, use_time = ?, status = ?, result = ?, choose = ?, score = ? WHERE id = ?",
              [finish_time, total_time, finish_status, anxiety_level, answer, standard_score, test_id])

    return '1'

@ts.route('/test/process', methods=['POST'])
def process():
    """
    处理SDS量表的语音输入
    支持音频文件上传和语音识别
    """
    try:
        # 检查是否有音频文件
        if 'audio' in request.files:
            # 处理音频文件
            audio_file = request.files['audio']

            if audio_file.filename == '':
                return jsonify({'error': '没有选择音频文件'}), 400

            # 读取音频数据
            audio_data = audio_file.read()

            # 使用语音识别服务进行处理
            result = speech_service.process_speech_for_sds(audio_data)
            
            # 添加额外信息
            result['source'] = 'audio_file'
            result['processed_text'] = result.get('text', '')
            result['auto_selected'] = result.get('answer') is not None

            return jsonify(result)

        elif request.is_json:
            # 处理JSON数据（文本输入）
            data = request.json
            text = data.get('text', '').strip()

            if not text:
                return jsonify({'error': '未接收到语音文本'}), 400

            # 直接从文本中提取答案
            answer = speech_service.extract_answer_from_text(text)

            if answer:
                # 计算置信度（基于文本长度和关键词匹配度）
                confidence = min(0.95, 0.6 + len(text) / 100)  # 基础置信度 + 文本长度加成
                
                response = {
                    'answer': answer,
                    'confidence': confidence,
                    'text': text,
                    'message': f'识别到选项: {answer}',
                    'processed_text': f'语音识别: {text}',
                    'auto_selected': True
                }
            else:
                response = {
                    'answer': None,
                    'confidence': 0.1,
                    'text': text,
                    'message': '无法从语音中识别到有效选项，请尝试更清楚地说出选项',
                    'processed_text': f'语音识别: {text}',
                    'auto_selected': False,
                    'suggestions': [
                        '请尝试说："选择A"、"选B"、"我选C"等',
                        '或直接说数字："1"、"二"、"第三个"等',
                        '或说出对应含义："没有"、"偶尔"、"经常"、"总是"等'
                    ]
                }

            return jsonify(response)
        else:
            return jsonify({'error': '不支持的请求格式'}), 400

    except Exception as e:
        print(f"语音处理错误: {e}")
        return jsonify({'error': f'语音处理失败: {str(e)}'}), 500


@ts.route('/test/speech-status', methods=['GET'])
def get_speech_status():
    """
    获取语音识别服务状态
    """
    try:
        # 检查模型是否已加载
        if speech_service.model is None:
            try:
                speech_service.load_model()
                return jsonify({
                    'status': 'ready',
                    'message': '语音识别服务已启动'
                })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': f'语音识别服务启动失败: {str(e)}'
                })
        else:
            return jsonify({
                'status': 'ready',
                'message': '语音识别服务正在运行'
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'检查服务状态失败: {str(e)}'
        }), 500


@ts.route('/test/speech-test', methods=['POST'])
def test_speech_extraction():
    """
    测试语音文本提取功能
    """
    try:
        data = request.get_json()
        test_text = data.get('text', '').strip()
        
        if not test_text:
            return jsonify({'error': '请提供测试文本'}), 400
        
        # 测试答案提取
        answer = speech_service.extract_answer_from_text(test_text)
        
        return jsonify({
            'input_text': test_text,
            'extracted_answer': answer,
            'success': answer is not None,
            'message': f'从文本"{test_text}"中提取答案: {answer}' if answer else f'无法从文本"{test_text}"中提取有效答案'
        })
        
    except Exception as e:
        return jsonify({
            'error': f'测试失败: {str(e)}'
        }), 500


# ================================================================================
# 表情识别相关API
# ================================================================================

@ts.route('/emotion/detect', methods=['POST'])
def emotion_detect():
    """表情检测API"""
    try:
        if not npu_emotion_service:
            return jsonify({
                'success': False,
                'error': '表情识别服务不可用'
            }), 503
        
        data = request.get_json()
        image_data = data.get('image')
        
        if not image_data:
            return jsonify({
                'success': False,
                'error': '缺少图像数据'
            }), 400
        
        # 进行表情检测
        result = npu_emotion_service.detect_emotion_from_image(image_data)
        
        # 记录详细错误信息
        if not result.get('success', False):
            import traceback
            print(f"表情检测返回失败: {result.get('error', '未知错误')}")
            print(traceback.format_exc())
        
        return jsonify(result)
        
    except Exception as e:
        import traceback
        error_msg = f'表情检测失败: {str(e)}'
        print(f"API异常: {error_msg}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500

@ts.route('/emotion/statistics', methods=['GET'])
def emotion_statistics():
    """获取表情统计数据（优先使用简化版MJPEG服务的统计）"""
    try:
        # 优先使用简化版MJPEG流服务的统计数据
        if simple_mjpeg_stream:
            stats = simple_mjpeg_stream.get_statistics()
            return jsonify({
                'success': True,
                'data': stats,
                'source': 'simple_mjpeg'
            })
        
        # 备用：使用原有服务的统计数据
        if npu_emotion_service:
            stats = npu_emotion_service.get_emotion_statistics()
            return jsonify({
                'success': True,
                'data': stats,
                'source': 'npu_service'
            })
        
        return jsonify({
            'success': False,
            'error': '表情识别服务不可用'
        }), 503
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'获取统计数据失败: {str(e)}'
        }), 500

@ts.route('/emotion/reset', methods=['POST'])
def emotion_reset():
    """重置表情统计"""
    try:
        reset_count = 0
        
        # 重置简化版MJPEG服务统计
        if simple_mjpeg_stream:
            simple_mjpeg_stream.reset_statistics()
            reset_count += 1
        
        # 重置原有服务统计
        if npu_emotion_service:
            npu_emotion_service.reset_statistics()
            reset_count += 1
        
        if reset_count == 0:
            return jsonify({
                'success': False,
                'error': '表情识别服务不可用'
            }), 503
        
        return jsonify({
            'success': True,
            'message': f'表情统计已重置（{reset_count}个服务）'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'重置统计失败: {str(e)}'
        }), 500

@ts.route('/emotion/service-info', methods=['GET'])
def emotion_service_info():
    """获取表情识别服务信息"""
    try:
        if not npu_emotion_service:
            return jsonify({
                'success': False,
                'error': '表情识别服务不可用'
            }), 503
        
        info = npu_emotion_service.get_service_info()
        return jsonify({
            'success': True,
            'data': info
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'获取服务信息失败: {str(e)}'
        }), 500

# ================================================================================
# MJPEG视频流 - 简化版，完全模仿 face_emotion.py 的逻辑
# ================================================================================

@ts.route('/emotion/video_stream')
def emotion_video_stream():
    """
    简化版MJPEG视频流端点 - 完全模仿 face_emotion.py
    
    核心逻辑：
    1. 单线程循环，与 face_emotion.py 的 while True 完全对应
    2. 使用 cap.grab() + cap.retrieve() 确保获取最新帧
    3. 不使用 sleep，让循环自然运行（最大化帧率）
    4. 直接调用NPU推理，与 face_emotion.py 一致
    
    前端使用 <img src="/emotion/video_stream"> 即可显示
    """
    if simple_mjpeg_stream is None:
        # 服务不可用，返回错误帧
        error_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(error_frame, "MJPEG Service Unavailable", (10, 120), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        _, buffer = cv2.imencode('.jpg', error_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        
        def error_generator():
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        
        return Response(
            error_generator(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
    
    return Response(
        simple_mjpeg_stream.generate_mjpeg_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@ts.route('/eeg/latest')
def eeg_latest_data():
    """获取最新的脑电数据（用于实时更新）"""
    try:
        from flask_app.utils.eeg_receiver import get_eeg_receiver
        receiver = get_eeg_receiver()
        latest = receiver.get_latest_data()
        
        return jsonify({
            'success': True,
            'data': latest
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'channel': 0,
                'value': 0.0,
                'theta': 0.0,
                'alpha': 0.0,
                'beta': 0.0,
                'timestamp': time.time()
            }
        })

@ts.route('/eeg/channels')
def eeg_all_channels():
    """获取所有3个通道的数据"""
    try:
        from flask_app.utils.eeg_receiver import get_eeg_receiver
        receiver = get_eeg_receiver()
        all_data = receiver.get_all_channels_data()
        
        # 调试日志
        print(f"[EEG API] 返回数据统计:")
        for ch in [1, 2, 3]:
            ch_key = f'channel{ch}'
            if ch_key in all_data:
                ch_data = all_data[ch_key]
                waveform_len = len(ch_data.get('waveform', []))
                features = ch_data.get('features', {})
                hist = features.get('history', {})
                print(f"  通道{ch}: 波形={waveform_len}, Theta={len(hist.get('theta', []))}, Alpha={len(hist.get('alpha', []))}, Beta={len(hist.get('beta', []))}")
        
        return jsonify({
            'success': True,
            'data': all_data
        })
    except Exception as e:
        import traceback
        print(f"[EEG API] 错误: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'channel1': {'waveform': [], 'timestamps': [], 'features': {'current': {}, 'history': {'theta': [], 'alpha': [], 'beta': [], 'timestamps': []}}},
                'channel2': {'waveform': [], 'timestamps': [], 'features': {'current': {}, 'history': {'theta': [], 'alpha': [], 'beta': [], 'timestamps': []}}},
                'channel3': {'waveform': [], 'timestamps': [], 'features': {'current': {}, 'history': {'theta': [], 'alpha': [], 'beta': [], 'timestamps': []}}}
            }
        })

@ts.route('/eeg/history')
def eeg_history_data():
    """获取历史脑电数据（用于绘制波形图）- 保留兼容性"""
    try:
        from flask_app.utils.eeg_receiver import get_eeg_receiver
        receiver = get_eeg_receiver()
        all_data = receiver.get_all_channels_data()
        
        return jsonify({
            'success': True,
            'data': all_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {}
        })

@ts.route('/eeg-test')
def eeg_test_page():
    """返回脑电数据测试页面"""
    return render_template('eeg_test.html')

@ts.route('/eeg/stream')
def eeg_stream_data():
    """SSE流式传输脑电数据"""
    def generate():
        try:
            from flask_app.utils.eeg_receiver import get_eeg_receiver
            receiver = get_eeg_receiver()
            print("[EEG] SSE流已建立，开始推送数据...")
            
            while True:
                batch = receiver.get_stream_data()
                if batch:
                    try:
                        # 确保数据可以被JSON序列化
                        json_str = json.dumps(batch)
                        yield f"data: {json_str}\n\n"
                        print(f"[EEG] 推送了 {len(batch)} 条数据")
                    except (ValueError, TypeError) as e:
                        print(f"[EEG] JSON序列化失败: {e}")
                        # 发送空数组而不是错误
                        yield f"data: []\n\n"
                else:
                    # 发送心跳包保持连接
                    yield f": heartbeat\n\n"
                
                time.sleep(0.05)  # 20Hz 更新率
                
        except GeneratorExit:
            print("[EEG] SSE流已关闭")
        except Exception as e:
            print(f"[EEG] SSE流错误: {e}")
            yield f"data: {json.dumps([])}\n\n"
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@ts.route('/emotion/stream_status')
def emotion_stream_status():
    """获取视频流服务状态"""
    if simple_mjpeg_stream is None:
        return jsonify({
            'success': False,
            'error': 'MJPEG服务不可用'
        }), 503
    
    return jsonify({
        'success': True,
        'model_loaded': simple_mjpeg_stream._model_loaded,
        'npu_available': simple_mjpeg_stream.NPU_AVAILABLE
    })

@ts.route('/emotion/stop_stream', methods=['POST'])
def emotion_stop_stream():
    """停止视频流并释放摄像头"""
    if simple_mjpeg_stream is None:
        return jsonify({
            'success': False,
            'error': 'MJPEG服务不可用'
        }), 503
    
    try:
        simple_mjpeg_stream.stop_stream()
        return jsonify({
            'success': True,
            'message': '视频流已停止'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'停止失败: {str(e)}'
        }), 500

@ts.route('/SDS/submit_with_emotion', methods=['POST'])
def SDS_submit_with_emotion():
    """提交SDS问卷（包含表情数据和综合评分）"""
    try:
        # 检查用户session
        userinfo = session.get("userinfo")
        if not userinfo:
            return jsonify({
                'success': False,
                'error': '用户未登录'
            }), 401
        
        # 检查测评session
        test_id = session.get("test_id")
        print(f"提交测评 - 用户: {userinfo.get('name', 'unknown')}, 测评ID: {test_id}")
        if not test_id:
            return jsonify({
                'success': False,
                'error': '请先开始测评，session中无test_id'
            }), 400
        
        from utils.scoring_system import scoring_system
        
        # 获取前端发送的数据
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '无效的请求数据'
            }), 400
        answers = data.get('answers')
        total_time = data.get('totalTime')
        emotion_data = data.get('emotionData', {})  # 表情数据
        finish_time = get_beijing_time()

        # 转为字符串答案answer
        answer = []
        for i in range(1, 21):
            key = str(i)
            if key in answers:
                answer.append(str(answers[key]['value']))
            else:
                answer.append('0')
        answer = ''.join(answer)

        # 计算SDS标准分
        # 反向评分题题号（2,5,6,11,12,14,16,17,18,20）
        reverse_questions = {2, 5, 6, 11, 12, 14, 16, 17, 18, 20}

        total_score = 0
        for i, score_str in enumerate(answer):
            score = int(score_str)
            question_num = i + 1
            
            if question_num in reverse_questions:
                # 反向评分：4-原分数
                score = 4 - score
            
            total_score += score

        # 计算标准分
        standard_score = int(total_score * 1.25)

        # 使用新的综合评分系统
        comprehensive_result = scoring_system.calculate_comprehensive_score(
            sds_score=standard_score,
            emotion_data=emotion_data
        )
        
        # 获取综合评分结果
        comprehensive_score = comprehensive_result['comprehensive_score']
        depression_level = comprehensive_result['depression_level']
        
        # 转换depression_level到中文
        level_mapping = {
            'none': '无抑郁',
            'mild': '轻度抑郁', 
            'moderate': '中度抑郁',
            'severe': '重度抑郁'
        }
        result_chinese = level_mapping.get(depression_level, '未知')

        # 将表情数据和综合评分结果转换为JSON字符串存储
        emotion_json = json.dumps(emotion_data) if emotion_data else None
        comprehensive_json = json.dumps(comprehensive_result)

        # 打印调试信息
        print(f"准备更新数据库 - test_id: {test_id}")
        print(f"  - 答案: {answer}")
        print(f"  - 结果: {result_chinese}")
        print(f"  - 分数: {standard_score}")
        print(f"  - 综合分数: {comprehensive_score}")
        print(f"  - 用时: {total_time}")
        print(f"  - 完成时间（北京时间）: {finish_time}")
        
        # 更新数据库，包含所有评分数据
        try:
            affected_rows = db.update("""
                UPDATE test 
                SET choose=?, result=?, score=?, use_time=?, finish_time=?, status=?, 
                    emotion_data=?, comprehensive_score=?, comprehensive_result=?
                WHERE id=?
            """, [answer, result_chinese, standard_score, total_time, finish_time, "已完成", 
                  emotion_json, comprehensive_score, comprehensive_json, test_id])
            
            print(f"✓ 数据库更新完成 - test_id: {test_id}, 受影响行数: {affected_rows}")
            
            if affected_rows == 0:
                print(f"✗ 警告：UPDATE 没有影响任何记录！test_id={test_id} 可能不存在")
                # 检查记录是否存在
                existing = db.fetch_one("SELECT * FROM test WHERE id=?", [test_id])
                if existing:
                    print(f"  记录存在，状态: {existing.get('status')}")
                else:
                    print(f"  记录不存在！")
            else:
                # 验证更新是否成功
                updated_record = db.fetch_one("SELECT * FROM test WHERE id=?", [test_id])
                if updated_record:
                    print(f"✓ 验证成功 - 记录状态: {updated_record.get('status')}, 结果: {updated_record.get('result')}, 分数: {updated_record.get('score')}")
                else:
                    print(f"✗ 错误：更新后找不到记录！")
                
        except Exception as update_error:
            print(f"✗ 数据库更新失败: {update_error}")
            import traceback
            traceback.print_exc()
            raise

        return jsonify({
            'success': True,
            'assessment_id': test_id,  # 添加测评ID
            'result': result_chinese,
            'sds_score': standard_score,
            'comprehensive_score': comprehensive_score,
            'comprehensive_result': comprehensive_result,
            'emotion_summary': emotion_data.get('summary', {})
        })

    except Exception as e:
        print(f"提交错误详情: {e}")
        return jsonify({
            'success': False,
            'error': f'提交失败: {str(e)}'
        }), 500
