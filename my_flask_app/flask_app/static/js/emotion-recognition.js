/**
 * 表情识别前端组件
 * 基于昇腾NPU的实时表情识别
 */

class EmotionRecognition {
    constructor(options = {}) {
        this.videoElement = null;
        this.canvasElement = null;
        this.stream = null;
        this.isRecording = false;
        this.detectionInterval = null;
        
        // 配置参数 - 强制使用传入的值
        // 检查options是否存在，以及autoStart是否明确传入
        const hasAutoStart = options && options.hasOwnProperty('autoStart');
        const autoStartValue = hasAutoStart ? options.autoStart : false;
        
        this.config = {
            videoWidth: options?.videoWidth || 320,
            videoHeight: options?.videoHeight || 240,
            detectionInterval: options?.detectionInterval || 50, // 50ms检测一次（20fps），更接近实时
            maxDetections: options?.maxDetections || 100,
            autoStart: autoStartValue === true, // 明确检查是否为true
            showVideo: options?.showVideo !== false, // 默认显示视频
            containerId: options?.containerId || 'emotion-container',
            jpegQuality: options?.jpegQuality || 0.7 // 降低JPEG质量以提高编码速度
        };
        
        // 调试日志：确认配置
        console.log('表情识别组件配置:', {
            '原始options对象': options,
            'options存在': !!options,
            'hasAutoStart属性': hasAutoStart,
            'options.autoStart原始值': options?.autoStart,
            'autoStartValue': autoStartValue,
            'this.config.autoStart最终值': this.config.autoStart,
            'typeof options.autoStart': typeof options?.autoStart,
            detectionInterval: this.config.detectionInterval,
            containerId: this.config.containerId
        });
        
        // Canvas用于绘制检测框
        this.overlayCanvas = null;
        this.overlayContext = null;
        this.currentDetections = []; // 当前检测结果
        
        // 请求管理：取消过期的请求，只保留最新的
        this.pendingRequest = null;
        this.requestAbortController = null;
        this.lastDetectionTime = 0;
        
        // 检测框位置平滑过渡（用于实时跟随，类似face_emotion.py）
        this.lastDetectionBoxes = []; // 上一次的检测框位置
        this.currentDisplayBoxes = []; // 当前显示的检测框位置（用于平滑过渡）
        this.detectionVelocities = []; // 检测框的运动速度（用于预测）
        this.lastDetectionTimestamp = 0; // 上一次检测的时间戳
        this.boxUpdateRate = 0.3; // 位置更新速率（0-1），值越大跟随越快，类似face_emotion.py的实时效果
        
        // 表情数据存储
        this.emotionHistory = [];
        this.emotionStats = {
            angry: 0,
            disgust: 0,
            fear: 0,
            happy: 0,
            neutral: 0,
            sad: 0,
            surprised: 0
        };
        
        // 表情中文映射
        this.emotionChinese = {
            angry: '愤怒',
            disgust: '厌恶',
            fear: '害怕',
            happy: '高兴',
            neutral: '自然',
            sad: '悲伤',
            surprised: '惊讶'
        };
        
        // 回调函数
        this.onEmotionDetected = options.onEmotionDetected || null;
        this.onError = options.onError || null;
        this.onStatusChange = options.onStatusChange || null;
        
        this.init();
    }
    
    async init() {
        try {
            await this.createElements();
            
            // 显示初始化状态
            this.updateStatus('正在初始化摄像头...', 'loading');
            
            await this.setupCamera();
            
            // 等待视频元素加载元数据并开始播放
            await new Promise((resolve) => {
                if (this.videoElement.readyState >= 2 && !this.videoElement.paused) {
                    console.log('视频已就绪并正在播放');
                    resolve();
                } else {
                    const checkReady = () => {
                        if (this.videoElement.readyState >= 2) {
                            // 确保视频正在播放
                            if (this.videoElement.paused) {
                                this.videoElement.play().then(() => {
                                    console.log('视频自动播放成功');
                                    resolve();
                                }).catch(err => {
                                    console.warn('视频自动播放失败，但继续:', err);
                                    resolve(); // 即使播放失败也继续
                                });
                            } else {
                                resolve();
                            }
                        }
                    };
                    
                    this.videoElement.onloadedmetadata = checkReady;
                    this.videoElement.oncanplay = checkReady;
                    
                    // 超时保护
                    setTimeout(() => {
                        console.log('视频加载超时，但继续执行，readyState:', this.videoElement.readyState);
                        resolve();
                    }, 5000);
                }
            });
            
            // 额外等待一小段时间，确保视频流完全稳定
            await new Promise(resolve => setTimeout(resolve, 300));
            
            // 摄像头就绪，显示控制按钮
            this.updateStatus('摄像头已就绪，自动开始检测', 'ready');
            const toggleBtn = document.getElementById('emotion-toggle-btn');
            if (toggleBtn) toggleBtn.disabled = false;
            
            // 如果设置了自动开始，在摄像头就绪后立即自动开始检测
            console.log('检查自动启动配置:', {
                'this.config.autoStart': this.config.autoStart,
                'typeof this.config.autoStart': typeof this.config.autoStart,
                'this.config': this.config,
                'stream存在': !!this.stream,
                'videoElement存在': !!this.videoElement,
                'readyState': this.videoElement?.readyState,
                'paused': this.videoElement?.paused
            });
            
            // 强制启用自动启动：检查配置或检测到SDS页面
            // 如果配置为true，或者容器ID是emotion-container（SDS页面），强制启用
            const isSDSPage = this.config.containerId === 'emotion-container';
            const shouldAutoStart = this.config.autoStart === true || isSDSPage;
            
            console.log('自动启动判断:', {
                'config.autoStart': this.config.autoStart,
                'isSDSPage': isSDSPage,
                'shouldAutoStart': shouldAutoStart
            });
            
            if (shouldAutoStart) {
                console.log('✅ 自动启动检测模式已启用，开始检测...');
                // 直接调用_doStartDetection，跳过startDetection中的检查
                if (this.stream && this.videoElement && this.videoElement.readyState >= 2) {
                    console.log('视频已就绪，直接启动检测');
                    this._doStartDetection();
                } else {
                    console.log('视频未完全就绪，使用startDetection等待');
                    // 如果还没完全准备好，使用startDetection（它会等待）
                this.startDetection();
                }
            } else {
                console.warn('❌ 自动启动检测模式未启用，需要手动点击开始按钮', {
                    'config.autoStart': this.config.autoStart,
                    '类型': typeof this.config.autoStart
                });
            }
            
        } catch (error) {
            console.error('表情识别初始化失败:', error);
            this.handleCameraError(error);
        }
    }

    handleCameraError(error) {
        // 创建友好的错误消息和解决方案
        const errorContainer = document.querySelector('.emotion-status');
        if (errorContainer) {
            errorContainer.innerHTML = `
                <div class="camera-error-container">
                    <div class="error-icon">⚠️</div>
                    <div class="error-message">
                        <h4>摄像头无法使用</h4>
                        <p>${error.message}</p>
                    </div>
                    <div class="error-solutions">
                        <h5>可能的解决方案：</h5>
                        <ol>
                            <li>🔌 检查摄像头是否已正确连接</li>
                            <li>🖥️ 关闭其他可能占用摄像头的程序</li>
                            <li>🔄 刷新浏览器页面重试</li>
                            <li>⚙️ 在浏览器设置中允许摄像头权限</li>
                            <li>🔧 运行摄像头修复工具：bash /home/HwHiAiUser/dsh_抑郁症2/fix_camera.sh</li>
                        </ol>
                    </div>
                    <div class="error-actions">
                        <button onclick="location.reload()" class="retry-btn">重新尝试</button>
                        <button onclick="emotionRecognition.enableFallbackMode()" class="fallback-btn">继续答题(无表情检测)</button>
                    </div>
                </div>
            `;
        }
        
        // 禁用表情检测相关按钮
        const buttons = ['emotion-toggle-btn', 'emotion-reset-btn'];
        buttons.forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = true;
        });
    }

    enableFallbackMode() {
        // 启用备用模式，隐藏摄像头区域，允许继续答题
        const videoSection = document.querySelector('.emotion-video-section');
        if (videoSection) {
            videoSection.style.display = 'none';
        }
        
        const statusElement = document.querySelector('.emotion-status');
        if (statusElement) {
            statusElement.innerHTML = `
                <div class="fallback-mode">
                    <p>📝 已进入答题模式（不包含表情检测）</p>
                    <p>您可以正常完成问卷，但不会记录表情数据。</p>
                </div>
            `;
        }
        
        // 启用问卷提交功能
        this.fallbackMode = true;
        
        // 通知主应用程序进入备用模式
        if (window.questionnaireSystem) {
            window.questionnaireSystem.setEmotionFallbackMode(true);
        }
    }
    
    createElements() {
        const container = document.getElementById(this.config.containerId);
        if (!container) {
            throw new Error(`找不到容器元素: ${this.config.containerId}`);
        }
        
        // 创建UI结构
        container.innerHTML = `
            <div class="emotion-recognition-widget">
                <!-- 表情识别状态栏 -->
                <div class="emotion-status-bar">
                    <div class="status-indicator">
                        <span class="status-dot" id="emotion-status-dot"></span>
                        <span class="status-text" id="emotion-status-text">准备中...</span>
                    </div>
                    <div class="control-buttons">
                        <button id="emotion-toggle-btn" class="btn btn-primary btn-sm">
                            <i class="fas fa-pause"></i> <span id="emotion-toggle-text">暂停检测</span>
                        </button>
                        <button id="emotion-reset-btn" class="btn btn-outline-secondary btn-sm">
                            <i class="fas fa-refresh"></i> 重置统计
                        </button>
                    </div>
                </div>
                
                <!-- 主要内容区域 -->
                <div class="emotion-content">
                    <!-- 视频和检测区域 -->
                    <div class="emotion-video-section ${this.config.showVideo ? '' : 'hidden'}">
                        <div class="video-container" style="position: relative; display: inline-block;">
                            <video id="emotion-video" autoplay muted playsinline style="width: 100%; max-width: 100%; display: block;"></video>
                            <canvas id="emotion-canvas" style="display: none;"></canvas>
                            <!-- Canvas用于实时绘制检测框（叠加在视频上方） -->
                            <canvas id="emotion-overlay-canvas" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></canvas>
                            <div class="detection-overlay" id="emotion-overlay">
                                <div class="current-emotion" id="current-emotion">
                                    <span class="emotion-label">当前表情</span>
                                    <span class="emotion-value" id="current-emotion-value">-</span>
                                    <span class="confidence-value" id="confidence-value">0%</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 表情统计区域 -->
                    <div class="emotion-stats-section">
                        <h6 class="stats-title">
                            <i class="fas fa-chart-bar"></i> 表情统计 
                            <small class="text-muted">(<span id="detection-count">0</span> 次检测)</small>
                        </h6>
                        <div class="emotion-stats-grid" id="emotion-stats-grid">
                            <!-- 动态生成统计图表 -->
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // 获取元素引用
        this.videoElement = document.getElementById('emotion-video');
        this.canvasElement = document.getElementById('emotion-canvas');
        this.overlayCanvas = document.getElementById('emotion-overlay-canvas');
        
        // 设置视频尺寸
        this.videoElement.width = this.config.videoWidth;
        this.videoElement.height = this.config.videoHeight;
        this.canvasElement.width = this.config.videoWidth;
        this.canvasElement.height = this.config.videoHeight;
        
        // 设置叠加Canvas尺寸（与视频一致）
        if (this.overlayCanvas) {
            this.overlayCanvas.width = this.config.videoWidth;
            this.overlayCanvas.height = this.config.videoHeight;
            this.overlayContext = this.overlayCanvas.getContext('2d');
        }
        
        // 监听视频尺寸变化，同步Canvas尺寸
        this.videoElement.addEventListener('loadedmetadata', () => {
            const videoWidth = this.videoElement.videoWidth || this.config.videoWidth;
            const videoHeight = this.videoElement.videoHeight || this.config.videoHeight;
            if (this.overlayCanvas) {
                this.overlayCanvas.width = videoWidth;
                this.overlayCanvas.height = videoHeight;
            }
            if (this.canvasElement) {
                this.canvasElement.width = videoWidth;
                this.canvasElement.height = videoHeight;
            }
        });
        
        // 绑定事件
        this.bindEvents();
        
        // 初始化统计图表
        this.updateStatsDisplay();
    }
    
    bindEvents() {
        // 开关按钮：点击切换检测状态
        document.getElementById('emotion-toggle-btn').addEventListener('click', () => {
            if (this.isRecording) {
                this.stopDetection();
            } else {
            this.startDetection();
            }
        });
        
        document.getElementById('emotion-reset-btn').addEventListener('click', () => {
            this.resetStatistics();
        });
    }
    
    async setupCamera() {
        try {
            // 检查浏览器是否支持摄像头
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('浏览器不支持摄像头功能');
            }

            // 尝试多种摄像头配置
            const cameraConfigs = [
                // 首选配置
                {
                    video: {
                        width: this.config.videoWidth,
                        height: this.config.videoHeight,
                        facingMode: 'user'
                    },
                    audio: false
                },
                // 备用配置1：移除facingMode
                {
                    video: {
                        width: this.config.videoWidth,
                        height: this.config.videoHeight
                    },
                    audio: false
                },
                // 备用配置2：使用默认分辨率
                {
                    video: {
                        facingMode: 'user'
                    },
                    audio: false
                },
                // 备用配置3：最基本配置
                {
                    video: true,
                    audio: false
                }
            ];

            let lastError = null;
            
            // 依次尝试每个配置
            for (let i = 0; i < cameraConfigs.length; i++) {
                try {
                    console.log(`尝试摄像头配置 ${i + 1}/${cameraConfigs.length}:`, cameraConfigs[i]);
                    
                    this.stream = await navigator.mediaDevices.getUserMedia(cameraConfigs[i]);
                    this.videoElement.srcObject = this.stream;
                    
                    return new Promise((resolve, reject) => {
                        this.videoElement.onloadedmetadata = () => {
                            this.videoElement.play().then(() => {
                                console.log('✅ 摄像头启动成功，配置:', cameraConfigs[i]);
                                resolve();
                            }).catch(reject);
                        };
                        this.videoElement.onerror = reject;
                        
                        // 添加超时检测
                        setTimeout(() => {
                            reject(new Error('摄像头加载超时'));
                        }, 10000); // 10秒超时
                    });
                    
                } catch (error) {
                    console.warn(`摄像头配置 ${i + 1} 失败:`, error.message);
                    lastError = error;
                    
                    // 清理失败的stream
                    if (this.stream) {
                        this.stream.getTracks().forEach(track => track.stop());
                        this.stream = null;
                    }
                    continue;
                }
            }
            
            // 所有配置都失败，抛出最后一个错误
            throw lastError || new Error('无法访问摄像头');
            
        } catch (error) {
            // 详细的错误处理
            let errorMessage = '摄像头初始化失败: ';
            
            if (error.name === 'NotFoundError' || error.name === 'DeviceNotFoundError') {
                errorMessage += '未找到摄像头设备。请检查摄像头是否已连接并正确安装驱动程序。';
            } else if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
                errorMessage += '摄像头访问被拒绝。请在浏览器设置中允许摄像头权限。';
            } else if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
                errorMessage += '摄像头正在被其他应用程序使用，或设备驱动程序存在问题。';
            } else if (error.name === 'OverconstrainedError' || error.name === 'ConstraintNotSatisfiedError') {
                errorMessage += '摄像头不支持所请求的配置。';
            } else if (error.name === 'NotSupportedError') {
                errorMessage += '浏览器不支持摄像头功能。';
            } else {
                errorMessage += error.message || '未知错误';
            }
            
            console.error('摄像头初始化详细错误:', {
                name: error.name,
                message: error.message,
                constraint: error.constraint
            });
            
            throw new Error(errorMessage);
        }
    }
    
    startDetection() {
        if (this.isRecording) {
            console.log('检测已在运行中');
            return;
        }
        
        // 检查是否在备用模式
        if (this.fallbackMode) {
            this.updateStatus('备用模式：表情检测不可用', 'warning');
            return;
        }
        
        // 检查摄像头是否可用
        if (!this.stream || !this.videoElement) {
            console.warn('摄像头未就绪，等待摄像头初始化...');
            this.updateStatus('摄像头未就绪，请重新初始化', 'error');
            // 如果摄像头还没就绪，等待一下再试
            if (this.config.autoStart) {
                setTimeout(() => {
                    if (this.stream && this.videoElement && this.videoElement.readyState >= 2) {
                        this.startDetection();
                    }
                }, 2000);
            }
            return;
        }
        
        // 检查视频元素是否已加载元数据
        if (this.videoElement.readyState === 0 || this.videoElement.readyState === 1) {
            console.warn('视频元素未完全加载，等待加载...', 'readyState:', this.videoElement.readyState);
            // 如果已经设置了onloadedmetadata监听器，先移除旧的
            const existingHandler = this.videoElement.onloadedmetadata;
            this.videoElement.onloadedmetadata = () => {
                console.log('视频元数据已加载，readyState:', this.videoElement.readyState);
                if (existingHandler) {
                    existingHandler();
                }
                // 确保视频正在播放
                if (this.videoElement.paused) {
                    this.videoElement.play().catch(err => {
                        console.warn('自动播放失败:', err);
                    });
                }
                // 延迟一点确保视频完全就绪
                setTimeout(() => {
                    this._doStartDetection();
                }, 100);
            };
            // 如果readyState已经是1（HAVE_METADATA），可能onloadedmetadata已经触发过了
            if (this.videoElement.readyState >= 1) {
                setTimeout(() => {
                    if (this.videoElement.readyState >= 2) {
                        this._doStartDetection();
                    }
                }, 200);
            }
            return;
        }
        
        // 确保视频正在播放
        if (this.videoElement.paused) {
            this.videoElement.play().catch(err => {
                console.warn('自动播放失败:', err);
            });
        }
        
        this._doStartDetection();
    }
    
    _doStartDetection() {
        this.isRecording = true;
        this.updateStatus('检测中...', 'active');
        
        // 更新开关按钮状态（显示为"暂停检测"）
        const toggleBtn = document.getElementById('emotion-toggle-btn');
        const toggleText = document.getElementById('emotion-toggle-text');
        if (toggleBtn) {
            toggleBtn.className = 'btn btn-primary btn-sm';
            // 更新图标
            const icon = toggleBtn.querySelector('i');
            if (icon) {
                icon.className = 'fas fa-pause';
            }
        }
        if (toggleText) {
            toggleText.textContent = '暂停检测';
        }
        
        // 启动动画循环，持续绘制检测框（类似face_emotion.py的实时效果）
        this.startDetectionLoop();
        
        // 使用requestAnimationFrame同步检测，而不是setInterval
        // 这样可以更好地与浏览器渲染同步，实现更流畅的效果
        this.startRealTimeDetection();
        
        console.log('表情检测已启动（实时模式）');
        
        if (this.onStatusChange) {
            this.onStatusChange('started');
        }
    }
    
    startRealTimeDetection() {
        /**
         * 使用requestAnimationFrame实现实时检测（类似face_emotion.py的while循环）
         * 每100ms检测一次，但使用RAF同步，更流畅
         */
        let lastDetectionTime = 0;
        
        const detectionLoop = (currentTime) => {
            if (!this.isRecording) {
                return;
            }
            
            // 检查是否到了检测时间间隔
            const timeSinceLastDetection = currentTime - lastDetectionTime;
            if (timeSinceLastDetection >= this.config.detectionInterval) {
                // 取消之前的请求（如果有）
                if (this.requestAbortController) {
                    this.requestAbortController.abort();
                }
                
                // 执行检测
            this.captureAndDetect();
                lastDetectionTime = currentTime;
            }
            
            // 继续循环
            requestAnimationFrame(detectionLoop);
        };
        
        // 立即执行一次检测
        this.captureAndDetect();
        lastDetectionTime = performance.now();
        
        // 启动检测循环
        requestAnimationFrame(detectionLoop);
    }
    
    startDetectionLoop() {
        /**
         * 启动检测循环，持续绘制检测框（类似face_emotion.py的实时效果）
         * 关键改进：持续绘制检测框，即使没有新结果也保持显示，实现实时跟随
         */
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
        }
        
        const loop = () => {
            if (this.isRecording) {
                // 持续绘制检测框（每帧都绘制，类似face_emotion.py的while循环）
                // 这样即使没有新检测结果，检测框也会保持显示，实现实时跟随效果
                this.drawDetectionsOnCanvas();
                this.animationFrameId = requestAnimationFrame(loop);
        }
        };
        
        this.animationFrameId = requestAnimationFrame(loop);
    }
    
    stopDetection() {
        if (!this.isRecording) return;
        
        this.isRecording = false;
        this.updateStatus('已停止', 'stopped');
        
        // 取消正在进行的请求
        if (this.requestAbortController) {
            this.requestAbortController.abort();
            this.requestAbortController = null;
        }
        
        // 清除定时器
        if (this.detectionInterval) {
            clearInterval(this.detectionInterval);
            this.detectionInterval = null;
        }
        
        // 停止动画循环
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }
        
        // 清空检测框
        if (this.overlayContext && this.overlayCanvas) {
            this.overlayContext.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);
        }
        this.currentDetections = [];
        
        // 更新开关按钮状态（显示为"继续检测"）
        const toggleBtn = document.getElementById('emotion-toggle-btn');
        const toggleText = document.getElementById('emotion-toggle-text');
        if (toggleBtn) {
            toggleBtn.className = 'btn btn-secondary btn-sm';
            // 更新图标
            const icon = toggleBtn.querySelector('i');
            if (icon) {
                icon.className = 'fas fa-play';
            }
        }
        if (toggleText) {
            toggleText.textContent = '继续检测';
        }
        
        if (this.onStatusChange) {
            this.onStatusChange('stopped');
        }
    }
    
    async captureAndDetect() {
        // 在try外面声明abortController，确保finally块可以访问
        let abortController = null;
        
        try {
            // 捕获当前帧
            const context = this.canvasElement.getContext('2d');
            context.drawImage(this.videoElement, 0, 0, this.config.videoWidth, this.config.videoHeight);
            
            // 转换为base64（降低质量以提高编码速度）
            const imageData = this.canvasElement.toDataURL('image/jpeg', this.config.jpegQuality);
            
            // 创建AbortController用于取消请求
            abortController = new AbortController();
            this.requestAbortController = abortController;
            
            // 发送到服务器进行检测（使用signal支持取消）
            const response = await fetch('/emotion/detect', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    image: imageData
                }),
                signal: abortController.signal
            });
            
            // 如果请求被取消，直接返回
            if (abortController.signal.aborted) {
                return;
            }
            
            const result = await response.json();
            
            // 调试日志
            console.log('检测API返回结果:', {
                success: result.success,
                faces_detected: result.faces_detected,
                emotions_count: result.emotions ? result.emotions.length : 0,
                dominant_emotion: result.dominant_emotion,
                has_annotated_image: !!result.annotated_image,
                error: result.error
            });
            
            // 如果请求被取消，直接返回
            if (abortController.signal.aborted) {
                return;
            }
            
            if (result.success) {
                this.processDetectionResult(result);
            } else {
                console.error('表情检测失败:', result.error);
                this.handleError('检测失败: ' + (result.error || '未知错误'));
            }
            
        } catch (error) {
            // 忽略被取消的请求错误
            if (error.name === 'AbortError') {
                return;
            }
            console.error('检测过程出错:', error);
            this.handleError('检测失败: ' + error.message);
        } finally {
            // 清除AbortController引用（如果还是当前请求）
            if (abortController && this.requestAbortController === abortController) {
                this.requestAbortController = null;
            }
        }
    }
    
    processDetectionResult(result) {
        const timestamp = new Date();
        
        console.log('处理检测结果:', {
            dominant_emotion: result.dominant_emotion,
            confidence: result.confidence,
            emotions_count: result.emotions ? result.emotions.length : 0,
            faces_detected: result.faces_detected,
            has_annotated_image: !!result.annotated_image
        });
        
        // 更新当前表情显示
        const dominantEmotion = result.dominant_emotion || 'neutral';
        const confidence = Math.round((result.confidence || 0) * 100);
        
        const emotionValueEl = document.getElementById('current-emotion-value');
        const confidenceValueEl = document.getElementById('confidence-value');
        
        if (emotionValueEl) {
            emotionValueEl.textContent = this.emotionChinese[dominantEmotion] || dominantEmotion;
        }
        if (confidenceValueEl) {
            confidenceValueEl.textContent = `${confidence}%`;
        }
        
        // 保存当前检测结果，用于绘制检测框
        const newDetections = result.emotions || [];
        
        // 关键改进：平滑更新检测框位置（类似face_emotion.py的实时效果）
        // 计算位置变化速度，用于平滑过渡
        const currentTime = performance.now();
        const timeDelta = currentTime - this.lastDetectionTimestamp;
        this.lastDetectionTimestamp = currentTime;
        
        // 更新检测框位置（平滑过渡，避免跳跃）
        if (newDetections.length > 0) {
            // 如果有新检测结果，更新位置
            this.currentDetections = newDetections;
            this.lastDetectionBoxes = newDetections.map(det => ({
                box: [...(det.box || [])],
                emotion: det.emotion,
                emotion_chinese: det.emotion_chinese,
                confidence: det.confidence
            }));
            
            // 计算速度（用于预测）
            if (this.currentDisplayBoxes.length > 0 && timeDelta > 0) {
                this.detectionVelocities = newDetections.map((det, idx) => {
                    if (idx < this.currentDisplayBoxes.length && det.box && this.currentDisplayBoxes[idx].box) {
                        const [x1, y1, x2, y2] = det.box;
                        const [oldX1, oldY1, oldX2, oldY2] = this.currentDisplayBoxes[idx].box;
                        return {
                            vx: (x1 - oldX1) / timeDelta,
                            vy: (y1 - oldY1) / timeDelta,
                            vw: ((x2 - x1) - (oldX2 - oldX1)) / timeDelta,
                            vh: ((y2 - y1) - (oldY2 - oldY1)) / timeDelta
                        };
                    }
                    return { vx: 0, vy: 0, vw: 0, vh: 0 };
                });
            }
            
            // 立即更新显示位置（快速跟随，类似face_emotion.py）
            this.currentDisplayBoxes = newDetections.map(det => ({
                box: [...(det.box || [])],
                emotion: det.emotion,
                emotion_chinese: det.emotion_chinese,
                confidence: det.confidence
            }));
        } else {
            // 如果没有检测到人脸，清空检测框（但保留上一次位置一段时间，避免闪烁）
            // 这里不清空，让检测框保持显示，直到有新结果
        }
        
        // 注意：drawDetectionsOnCanvas() 会在 startDetectionLoop() 中持续调用
        // 这里不需要手动调用，让持续绘制循环自动更新
        
        // 更新统计数据
        if (result.emotions && result.emotions.length > 0) {
            result.emotions.forEach(emotion => {
                if (this.emotionStats.hasOwnProperty(emotion.emotion)) {
                    this.emotionStats[emotion.emotion]++;
                }
            });
        } else {
            // 如果没有检测到具体表情，增加主要表情计数
            if (this.emotionStats.hasOwnProperty(dominantEmotion)) {
                this.emotionStats[dominantEmotion]++;
            }
        }
        
        // 记录历史数据
        this.emotionHistory.push({
            timestamp: timestamp,
            emotion: dominantEmotion,
            confidence: result.confidence,
            emotions: result.emotions || [],
            face_count: result.face_count || 0
        });
        
        // 限制历史记录数量
        if (this.emotionHistory.length > this.config.maxDetections) {
            this.emotionHistory.shift();
        }
        
        // 更新统计显示
        this.updateStatsDisplay();
        
        // 调用回调函数
        if (this.onEmotionDetected) {
            this.onEmotionDetected({
                emotion: dominantEmotion,
                confidence: result.confidence,
                timestamp: timestamp,
                result: result
            });
        }
    }
    
    drawDetectionsOnCanvas() {
        /**
         * 在Canvas上实时绘制检测框和表情标签（类似face_emotion.py的效果）
         */
        if (!this.overlayContext || !this.overlayCanvas) {
            return;
        }
        
        // 清空Canvas
        this.overlayContext.clearRect(0, 0, this.overlayCanvas.width, this.overlayCanvas.height);
        
        // 如果没有检测结果，不绘制
        if (!this.currentDetections || this.currentDetections.length === 0) {
            return;
        }
        
        // 获取视频实际尺寸（用于坐标缩放）
        const videoWidth = this.videoElement.videoWidth || this.config.videoWidth;
        const videoHeight = this.videoElement.videoHeight || this.config.videoHeight;
        const canvasWidth = this.overlayCanvas.width;
        const canvasHeight = this.overlayCanvas.height;
        
        // 计算缩放比例
        const scaleX = canvasWidth / videoWidth;
        const scaleY = canvasHeight / videoHeight;
        
        // 绘制每个检测框
        this.currentDetections.forEach(detection => {
            const box = detection.box;
            if (!box || box.length < 4) return;
            
            const [x_min, y_min, x_max, y_max] = box;
            
            // 缩放坐标
            const x1 = x_min * scaleX;
            const y1 = y_min * scaleY;
            const x2 = x_max * scaleX;
            const y2 = y_max * scaleY;
            
            // 绘制检测框（绿色，与face_emotion.py一致）
            this.overlayContext.strokeStyle = '#00FF00'; // 绿色
            this.overlayContext.lineWidth = 2;
            this.overlayContext.strokeRect(x1, y1, x2 - x1, y2 - y1);
            
            // 绘制表情标签
            const emotionLabel = detection.emotion_chinese || detection.emotion || 'Unknown';
            const confidence = detection.confidence || detection.emotion_conf || 0;
            const label = `${emotionLabel}:${(confidence * 100).toFixed(0)}%`;
            const fontSize = Math.max(12, canvasWidth / 30);
            
            // 设置文字样式
            this.overlayContext.font = `${fontSize}px Arial`;
            this.overlayContext.fillStyle = '#FFFFFF';
            this.overlayContext.strokeStyle = '#000000';
            this.overlayContext.lineWidth = 2;
            
            // 计算文字位置（在框的上方或内部）
            const textY = y1 - 5 > fontSize ? y1 - 5 : y1 + fontSize + 5;
            
            // 绘制文字（带描边，提高可读性）
            this.overlayContext.strokeText(label, x1, textY);
            this.overlayContext.fillText(label, x1, textY);
        });
    }
    
    updateStatsDisplay() {
        const totalDetections = Object.values(this.emotionStats).reduce((a, b) => a + b, 0);
        document.getElementById('detection-count').textContent = totalDetections;
        
        const statsGrid = document.getElementById('emotion-stats-grid');
        statsGrid.innerHTML = '';
        
        Object.entries(this.emotionStats).forEach(([emotion, count]) => {
            const percentage = totalDetections > 0 ? (count / totalDetections * 100) : 0;
            const chineseName = this.emotionChinese[emotion];
            
            const statItem = document.createElement('div');
            statItem.className = 'emotion-stat-item';
            statItem.innerHTML = `
                <div class="stat-label">${chineseName}</div>
                <div class="stat-bar">
                    <div class="stat-fill" style="width: ${percentage}%"></div>
                </div>
                <div class="stat-value">${count} (${percentage.toFixed(1)}%)</div>
            `;
            
            statsGrid.appendChild(statItem);
        });
    }
    
    resetStatistics() {
        this.emotionHistory = [];
        this.emotionStats = {
            angry: 0,
            disgust: 0,
            fear: 0,
            happy: 0,
            neutral: 0,
            sad: 0,
            surprised: 0
        };
        
        this.updateStatsDisplay();
        
        // 重置当前表情显示
        document.getElementById('current-emotion-value').textContent = '-';
        document.getElementById('confidence-value').textContent = '0%';
        
        // 调用服务器重置
        fetch('/emotion/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        }).catch(error => {
            console.error('服务器统计重置失败:', error);
        });
    }
    
    updateStatus(text, type = 'info') {
        const statusDot = document.getElementById('emotion-status-dot');
        const statusText = document.getElementById('emotion-status-text');
        
        statusText.textContent = text;
        statusDot.className = `status-dot status-${type}`;
    }
    
    handleError(message) {
        this.updateStatus('错误: ' + message, 'error');
        
        if (this.onError) {
            this.onError(message);
        }
    }
    
    getEmotionSummary() {
        const totalDetections = Object.values(this.emotionStats).reduce((a, b) => a + b, 0);
        const percentages = {};
        
        Object.entries(this.emotionStats).forEach(([emotion, count]) => {
            percentages[emotion] = totalDetections > 0 ? (count / totalDetections * 100) : 0;
        });
        
        // 找出主要表情
        const dominantEmotion = Object.entries(percentages)
            .reduce((a, b) => percentages[a[0]] > percentages[b[0]] ? a : b)[0];
        
        return {
            total_detections: totalDetections,
            emotion_percentages: percentages,
            dominant_emotion: dominantEmotion,
            emotion_history: this.emotionHistory,
            chinese_names: this.emotionChinese
        };
    }
    
    destroy() {
        this.stopDetection();
        
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
        }
        
        if (this.detectionInterval) {
            clearInterval(this.detectionInterval);
        }
    }
}

// 全局样式
const emotionCSS = `
<style>
.emotion-recognition-widget {
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    overflow: hidden;
    margin-bottom: 1rem;
}

.emotion-status-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}

.status-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
}

.status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ccc;
}

.status-dot.status-success { background: #10b981; }
.status-dot.status-active { background: #f59e0b; animation: pulse 2s infinite; }
.status-dot.status-error { background: #ef4444; }
.status-dot.status-stopped { background: #6b7280; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.control-buttons {
    display: flex;
    gap: 8px;
}

.emotion-content {
    padding: 16px;
}

.emotion-video-section {
    margin-bottom: 20px;
}

.emotion-video-section.hidden {
    display: none;
}

.video-container {
    position: relative;
    display: inline-block;
    border-radius: 8px;
    overflow: hidden;
    background: #f3f4f6;
}

#emotion-video {
    display: block;
    border-radius: 8px;
}

.detection-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(transparent, rgba(0,0,0,0.7));
    color: white;
    padding: 8px 12px;
}

.current-emotion {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
}

.emotion-label {
    opacity: 0.8;
}

.emotion-value {
    font-weight: bold;
    font-size: 16px;
}

.confidence-value {
    opacity: 0.8;
    font-size: 12px;
}

.emotion-stats-section {
    border-top: 1px solid #e5e7eb;
    padding-top: 16px;
}

.stats-title {
    margin-bottom: 12px;
    color: #374151;
    font-weight: 600;
}

.emotion-stats-grid {
    display: grid;
    gap: 8px;
}

.emotion-stat-item {
    display: grid;
    grid-template-columns: 80px 1fr 80px;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
}

.stat-label {
    font-size: 13px;
    color: #6b7280;
    font-weight: 500;
}

.stat-bar {
    height: 6px;
    background: #e5e7eb;
    border-radius: 3px;
    overflow: hidden;
}

.stat-fill {
    height: 100%;
    background: linear-gradient(90deg, #3b82f6, #8b5cf6);
    transition: width 0.3s ease;
}

.stat-value {
    font-size: 12px;
    color: #6b7280;
    text-align: right;
}

.btn {
    padding: 6px 12px;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.btn-primary {
    background: #3b82f6;
    color: white;
}

.btn-primary:hover:not(:disabled) {
    background: #2563eb;
}

.btn-secondary {
    background: #6b7280;
    color: white;
}

.btn-secondary:hover:not(:disabled) {
    background: #4b5563;
}

.btn-outline-secondary {
    background: transparent;
    color: #6b7280;
    border: 1px solid #d1d5db;
}

.btn-outline-secondary:hover:not(:disabled) {
    background: #f9fafb;
}

.btn-sm {
    padding: 4px 8px;
    font-size: 11px;
}
</style>
`;

// 注入样式
if (!document.getElementById('emotion-recognition-styles')) {
    const styleElement = document.createElement('div');
    styleElement.id = 'emotion-recognition-styles';
    styleElement.innerHTML = emotionCSS;
    document.head.appendChild(styleElement);
}
