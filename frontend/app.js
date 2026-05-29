/* nnc1_web/frontend/app.js */

document.addEventListener("DOMContentLoaded", () => {
    // ==========================================
    // 1. 全局状态存储 (Batch State)
    // ==========================================
    let directors = []; // 存放所有董事对象的数组
    let activeDirectorId = null; // 当前展开的卡片ID
    let pairGroups = []; // 全局队列中存放的董事正反配对卡片组状态
    let isConverting = false; // 是否正在批量转换中
    let currentDraggingSourceGroupId = null; // 当前正在拖拽的反面照源组ID

    // ==========================================
    // 2. 获取 DOM 元素句柄 (双通道改版)
    // ==========================================
    const dropZoneFront = document.getElementById("dropZoneFront");
    const fileInputFront = document.getElementById("fileInputFront");
    const dropZoneBack = document.getElementById("dropZoneBack");
    const fileInputBack = document.getElementById("fileInputBack");
    const queueList = document.getElementById("queueList");
    const uploadQueueSection = document.getElementById("uploadQueueSection");
    const queueCountSpan = document.getElementById("queueCount");
    
    // ⚡ 批量转换控制按钮及就绪计数器
    const btnStartOcrBatch = document.getElementById("btnStartOcrBatch");
    const readyCountSpan = document.getElementById("readyCount");
    const toggleAutoOcr = document.getElementById("toggleAutoOcr");
    
    const directorsContainer = document.getElementById("directorsContainer");
    const emptyState = document.getElementById("emptyState");
    const btnAddDirector = document.getElementById("btnAddDirector");
    const btnSubmitBatch = document.getElementById("btnSubmitBatch");
    const btnText = btnSubmitBatch.querySelector(".btn-text");
    const btnLoading = btnSubmitBatch.querySelector(".btn-loading");
    
    const notificationBar = document.getElementById("notificationBar");
    const notificationText = document.getElementById("notificationText");

    // ==========================================
    // 3. 消息通知组件封装
    // ==========================================
    function showNotification(message, type = "info") {
        notificationBar.className = `notification-bar glass-card ${type}`;
        notificationText.textContent = message;
        notificationBar.classList.remove("hidden");
        
        // 6秒后自动淡出 (非错误状态)
        if (type !== "error") {
            setTimeout(() => {
                notificationBar.classList.add("hidden");
            }, 6000);
        }
    }

    function hideNotification() {
        notificationBar.classList.add("hidden");
    }

    // ==========================================
    // 4. 拖拽上传与批量文件分发逻辑 (双通道)
    // ==========================================
    
    // 注册拖拽高亮效果
    function bindDragEvents(zoneElement, dragClass) {
        ["dragenter", "dragover"].forEach(eventName => {
            zoneElement.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                zoneElement.classList.add(dragClass);
            }, false);
        });

        ["dragleave", "drop"].forEach(eventName => {
            zoneElement.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
                zoneElement.classList.remove(dragClass);
            }, false);
        });
    }

    bindDragEvents(dropZoneFront, "drag-over");
    bindDragEvents(dropZoneBack, "drag-over");

    // 正面照拖拽放置与选取
    dropZoneFront.addEventListener("drop", (e) => {
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) processMultipleFiles(files, "front");
    });
    fileInputFront.addEventListener("change", (e) => {
        const files = Array.from(fileInputFront.files);
        if (files.length > 0) processMultipleFiles(files, "front");
    });

    // 反面照拖拽放置与选取
    dropZoneBack.addEventListener("drop", (e) => {
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) processMultipleFiles(files, "back");
    });
    fileInputBack.addEventListener("change", (e) => {
        const files = Array.from(fileInputBack.files);
        if (files.length > 0) processMultipleFiles(files, "back");
    });

    // 智能解析文件名最长公共前缀
    function getFilePrefix(filename) {
        let name = filename.substring(0, filename.lastIndexOf('.')) || filename;
        // 去除 front/back, 正面/反面, _1, _2 等字符
        name = name.replace(/(_|-)?(front|back|正面|反面|主页|国徽|信息面|网格面|_1|_2|-1|-2)$/gi, "").trim();
        return name;
    }

    // 批量分发文件处理 (智能分流并模拟上传)
    function processMultipleFiles(files, side) {
        uploadQueueSection.classList.remove("hidden");
        
        files.forEach(file => {
            if (!file.type.startsWith("image/")) {
                showNotification(`跳过非图片文件: ${file.name}`, "warning");
                return;
            }
            
            const prefix = getFilePrefix(file.name);
            let matchedGroup = null;
            
            // A. 智能预配对：寻找前缀相同且对应卡槽为空的组
            for (let group of pairGroups) {
                if (group.prefix === prefix) {
                    if (side === "front" && !group.frontFile) {
                        matchedGroup = group;
                        break;
                    }
                    if (side === "back" && !group.backFile) {
                        matchedGroup = group;
                        break;
                    }
                }
            }
            
            // B. 兜底顺序补充：对于找不到前缀配对的，如果已有组的对应槽位空缺且该组也无前缀，则填补进去
            if (!matchedGroup) {
                for (let group of pairGroups) {
                    if (side === "front" && !group.frontFile && !group.prefix) {
                        matchedGroup = group;
                        group.prefix = prefix;
                        group.tempName = prefix || "未命名组";
                        break;
                    }
                    if (side === "back" && !group.backFile && !group.prefix) {
                        matchedGroup = group;
                        break;
                    }
                }
            }
            
            // C. 若依然没有匹配到，则创建全新的卡片组
            if (!matchedGroup) {
                const groupId = "pair_" + Date.now() + "_" + Math.random().toString(36).substring(2, 5);
                matchedGroup = {
                    id: groupId,
                    tempName: prefix || "未命名组",
                    prefix: prefix,
                    frontFile: null,
                    backFile: null,
                    frontProgress: 0,
                    backProgress: 0,
                    frontStatus: "none",
                    backStatus: "none",
                    status: "uploading",
                    error: null
                };
                pairGroups.push(matchedGroup);
            }
            
            // D. 装载 File 并设置上传状态
            if (side === "front") {
                matchedGroup.frontFile = file;
                matchedGroup.frontStatus = "uploading";
                matchedGroup.frontProgress = 0;
            } else {
                matchedGroup.backFile = file;
                matchedGroup.backStatus = "uploading";
                matchedGroup.backProgress = 0;
            }
            
            matchedGroup.status = "uploading";
            
            // E. 渲染/刷新队列 DOM 节点
            renderPairGroups();
            
            // F. 启动该单槽的平滑上传模拟
            simulateSlotUploadProgress(matchedGroup, side);
        });
        
        updateQueueCountsAndUI();
    }

    // 渲染或局部刷新整个预配对队列 DOM
    function renderPairGroups() {
        queueList.innerHTML = "";
        
        if (pairGroups.length === 0) {
            uploadQueueSection.classList.add("hidden");
            return;
        }
        
        pairGroups.forEach((group, idx) => {
            const cardEl = document.createElement("div");
            cardEl.className = `queue-item pair-group-card ${group.status === "converting" ? "active-converting" : ""}`;
            cardEl.id = group.id;
            
            const frontSrc = group.frontFile ? URL.createObjectURL(group.frontFile) : "";
            const backSrc = group.backFile ? URL.createObjectURL(group.backFile) : "";
            
            const frontSlotHTML = group.frontFile 
                ? `<div class="preview-slot slot-front has-file">
                       <img src="${frontSrc}" alt="正面">
                       <span class="preview-slot-label front-label">🪪 正面</span>
                   </div>`
                : `<div class="preview-slot slot-front">
                       <div class="preview-slot-empty">📥 缺正面</div>
                   </div>`;
                   
            // ⚡ 对有文件的反面照，挂载 draggable="true" 属性
            const backSlotHTML = group.backFile
                ? `<div class="preview-slot slot-back has-file" draggable="true" title="按住鼠标拖拽此反面照，吸附移动到其他组">
                       <img src="${backSrc}" alt="反面">
                       <span class="preview-slot-label back-label">💳 反面</span>
                   </div>`
                : `<div class="preview-slot slot-back" title="拖入或在此放置身份证反面照进行吸附">
                       <div class="preview-slot-empty">📥 缺反面</div>
                   </div>`;
            
            const isFirst = idx === 0;
            const isLast = idx === pairGroups.length - 1;
            const isSwapDisabled = isConverting || !group.backFile; 
            
            let statusText = "就绪待转换";
            let statusClass = "ready";
            let progressVal = 100;
            
            if (group.status === "uploading") {
                statusText = "文件加载中...";
                statusClass = "uploading";
                const frontP = group.frontFile ? group.frontProgress : 100;
                const backP = group.backFile ? group.backProgress : 100;
                progressVal = Math.floor((frontP + backP) / 2);
                if (progressVal < 100) {
                    statusText = `正在加载 ${progressVal}%...`;
                } else {
                    statusText = "已就绪";
                    statusClass = "ready";
                    group.status = "ready";
                }
            } else if (group.status === "converting") {
                statusText = "识别中...";
                statusClass = "converting";
                progressVal = 100;
            } else if (group.status === "success") {
                statusText = "解析成功";
                statusClass = "success";
                progressVal = 100;
            } else if (group.status === "failed") {
                statusText = group.error ? `失败: ${group.error}` : "识别失败";
                statusClass = "failed";
                progressVal = 100;
            }
            
            let barClass = "queue-item-progress-bar " + statusClass;
            
            cardEl.innerHTML = `
                <div class="pair-info-header">
                    <div class="pair-title">
                        <span class="pair-title-index">组 #${idx + 1}</span>
                        <span>${group.tempName}</span>
                    </div>
                    <div class="queue-item-status ${statusClass}" id="status_${group.id}">${statusText}</div>
                </div>
                
                <div class="pair-slots-row">
                    ${frontSlotHTML}
                    ${backSlotHTML}
                    
                    <div class="pair-adjust-controls">
                        <button type="button" class="btn-swap-arrow btn-swap-up" title="上移反面，与上一组互换配对" data-index="${idx}" ${isFirst || isSwapDisabled ? "disabled" : ""}>
                            ▲
                        </button>
                        <button type="button" class="btn-swap-arrow btn-swap-down" title="下移反面，与下一组互换配对" data-index="${idx}" ${isLast || isSwapDisabled ? "disabled" : ""}>
                            ▼
                        </button>
                    </div>
                </div>
                
                <div class="pair-progress-wrapper">
                    <div class="queue-item-progress-container">
                        <div class="${barClass}" id="bar_${group.id}" style="width: ${progressVal}%"></div>
                    </div>
                </div>
            `;
            
            // 🔼/🔽 手动微调互换事件
            const btnUp = cardEl.querySelector(".btn-swap-up");
            const btnDown = cardEl.querySelector(".btn-swap-down");
            
            if (btnUp) {
                btnUp.addEventListener("click", (e) => {
                    e.stopPropagation();
                    swapBackFiles(idx, idx - 1);
                });
            }
            if (btnDown) {
                btnDown.addEventListener("click", (e) => {
                    e.stopPropagation();
                    swapBackFiles(idx, idx + 1);
                });
            }
            
            // ⚡ 挂载 HTML5 鼠标拖拽高亮与自由吸附逻辑
            const slotBackEl = cardEl.querySelector(".slot-back");
            
            // A. 源端（如果包含图片，可被拖拽） - 触发拖拽开始
            if (group.backFile && slotBackEl) {
                slotBackEl.addEventListener("dragstart", (e) => {
                    e.dataTransfer.setData("text/plain", JSON.stringify({
                        sourceGroupId: group.id,
                        type: "backFile"
                    }));
                    slotBackEl.classList.add("dragging");
                    currentDraggingSourceGroupId = group.id; // 记录全局源ID
                    e.dataTransfer.effectAllowed = "move";
                });
                
                slotBackEl.addEventListener("dragend", () => {
                    slotBackEl.classList.remove("dragging");
                    currentDraggingSourceGroupId = null; // 清空全局源ID
                    // 彻底清除所有卡片组残留的吸附高亮类
                    document.querySelectorAll(".pair-group-card").forEach(el => {
                        el.classList.remove("drag-hover-card-absorb");
                    });
                });
            }
            
            // B. 目标端（整个卡片组作为拖拽放置目标，极其顺滑）
            cardEl.addEventListener("dragover", (e) => {
                e.preventDefault(); // 必需
                if (!isConverting && currentDraggingSourceGroupId && currentDraggingSourceGroupId !== group.id) {
                    cardEl.classList.add("drag-hover-card-absorb");
                    e.dataTransfer.dropEffect = "move";
                }
            });
            
            cardEl.addEventListener("dragleave", () => {
                cardEl.classList.remove("drag-hover-card-absorb");
            });
            
            cardEl.addEventListener("drop", (e) => {
                e.preventDefault();
                cardEl.classList.remove("drag-hover-card-absorb");
                
                if (isConverting) return;
                
                try {
                    const data = JSON.parse(e.dataTransfer.getData("text/plain"));
                    if (data.type === "backFile" && data.sourceGroupId) {
                        absorbBackFile(data.sourceGroupId, group.id);
                    }
                } catch (err) {
                    console.error("Snap absorb error:", err);
                }
            });
            
            queueList.appendChild(cardEl);
        });
    }

    // 拖拽吸附合并算法，并自动过滤清理空壳组 (垃圾回收 GC)
    function absorbBackFile(sourceId, targetId) {
        if (sourceId === targetId || isConverting) return;
        
        const source = pairGroups.find(g => g.id === sourceId);
        const target = pairGroups.find(g => g.id === targetId);
        
        if (!source || !target) return;
        if (!source.backFile) return; 
        
        // 1. 转移反面照片的所有属性
        target.backFile = source.backFile;
        target.backProgress = source.backProgress;
        target.backStatus = source.backStatus;
        
        // 2. 清空源组的反面照
        source.backFile = null;
        source.backProgress = 0;
        source.backStatus = "none";
        
        // 3. 智能判定：重新校对各自的状态
        [source, target].forEach(g => {
            if (g.frontStatus === "uploading" || g.backStatus === "uploading") {
                g.status = "uploading";
            } else {
                g.status = "ready";
            }
        });
        
        // 4. 【垃圾回收】：过滤清除所有既无正面又无反面的废弃空卡片组 (完美解决空壳行冗余)
        pairGroups = pairGroups.filter(g => g.frontFile || g.backFile);
        
        // 5. 刷新总体界面和计数
        renderPairGroups();
        updateQueueCountsAndUI();
        showNotification("🎯 身份证反面已成功吸附绑定到目标正面组！", "success");

        // ⚡ 检查如果配对完成且自动转换开关开启，则自动触发 OCR 转换与消失
        if (toggleAutoOcr && toggleAutoOcr.checked && target.frontFile && target.backFile && target.status === "ready") {
            runOcrForPairGroup(target);
        }
    }

    // 拼图微调：一键互换两组之间的反面文件及状态，并瞬间渲染
    function swapBackFiles(idx1, idx2) {
        if (isConverting) return;
        if (idx1 < 0 || idx1 >= pairGroups.length || idx2 < 0 || idx2 >= pairGroups.length) return;
        
        const g1 = pairGroups[idx1];
        const g2 = pairGroups[idx2];
        
        const tempBackFile = g1.backFile;
        const tempBackProgress = g1.backProgress;
        const tempBackStatus = g1.backStatus;
        
        g1.backFile = g2.backFile;
        g1.backProgress = g2.backProgress;
        g1.backStatus = g2.backStatus;
        
        g2.backFile = tempBackFile;
        g2.backProgress = tempBackProgress;
        g2.backStatus = tempBackStatus;
        
        [g1, g2].forEach(g => {
            if (g.frontStatus === "uploading" || g.backStatus === "uploading") {
                g.status = "uploading";
            } else {
                g.status = "ready";
            }
        });
        
        renderPairGroups();
        updateQueueCountsAndUI();
        showNotification("🔄 反面证件照位置互换配对成功！", "success");
    }

    // 瞬间加载就绪
    function simulateSlotUploadProgress(group, side) {
        if (side === "front") {
            group.frontProgress = 100;
            group.frontStatus = "ready";
        } else {
            group.backProgress = 100;
            group.backStatus = "ready";
        }
        
        const isFrontFinished = group.frontFile ? group.frontProgress === 100 : true;
        const isBackFinished = group.backFile ? group.backProgress === 100 : true;
        
        if (isFrontFinished && isBackFinished) {
            group.status = "ready";
        }
        
        renderPairGroups();
        updateQueueCountsAndUI();

        if (toggleAutoOcr && toggleAutoOcr.checked && group.frontFile && group.backFile && group.status === "ready") {
            // ⚡ 完美配对成功，且自动转换开关开启，自动开启 OCR 与消失机制
            runOcrForPairGroup(group);
        }
    }

    // 更新全局计数和转换按钮的可点击状态
    function updateQueueCountsAndUI() {
        const readyCount = pairGroups.filter(g => g.status === "ready").length;
        const failedCount = pairGroups.filter(g => g.status === "failed").length;
        const totalCount = pairGroups.length;
        
        queueCountSpan.textContent = totalCount;
        readyCountSpan.textContent = readyCount;
        
        const actionableCount = readyCount + failedCount;
        if (actionableCount > 0 && !isConverting) {
            btnStartOcrBatch.disabled = false;
        } else {
            btnStartOcrBatch.disabled = true;
        }
    }

    // 绑定批量转换按钮点击事件 (3 路并发转换)
    btnStartOcrBatch.addEventListener("click", async () => {
        const readyGroups = pairGroups.filter(g => g.status === "ready" || g.status === "failed");
        if (readyGroups.length === 0 || isConverting) return;
        
        isConverting = true;
        btnStartOcrBatch.disabled = true;
        
        const btnOcrText = btnStartOcrBatch.querySelector(".btn-ocr-text");
        const btnOcrLoading = btnStartOcrBatch.querySelector(".btn-ocr-loading");
        btnOcrText.classList.add("hidden");
        btnOcrLoading.classList.remove("hidden");
        
        showNotification("⚡ 开始分批并发 OCR 解析正面图片，反面自动匹配绑定...", "info");
        
        try {
            const CONCURRENT_LIMIT = 3;
            const taskQueue = [...readyGroups];
            
            const worker = async () => {
                while (taskQueue.length > 0) {
                    const group = taskQueue.shift();
                    await runOcrForPairGroup(group);
                }
            };
            
            const workers = [];
            const activeCount = Math.min(CONCURRENT_LIMIT, taskQueue.length);
            for (let i = 0; i < activeCount; i++) {
                workers.push(worker());
            }
            
            await Promise.all(workers);
            
            const successCount = pairGroups.filter(g => g.status === "success").length;
            const failedCount = pairGroups.filter(g => g.status === "failed").length;
            showNotification(`批量处理完毕！成功创建: ${successCount} 个董事, 失败: ${failedCount} 个。`, "success");
            
        } catch (error) {
            console.error("Batch OCR Execution error:", error);
            showNotification("批量转换过程中发生意外错误", "error");
        } finally {
            isConverting = false;
            btnOcrText.classList.remove("hidden");
            btnOcrLoading.classList.add("hidden");
            renderPairGroups(); 
            updateQueueCountsAndUI();
        }
    });

    // 独立且极致的卡片组 OCR 核心执行函数 (使用 XMLHttpRequest 追踪真实网络上传进度)
    async function runOcrForPairGroup(group) {
        const bar = document.getElementById(`bar_${group.id}`);
        const statusSpan = document.getElementById(`status_${group.id}`);
        const cardEl = document.getElementById(group.id);
        
        if (bar && statusSpan) {
            group.status = "converting";
            bar.className = "queue-item-progress-bar converting";
            bar.style.width = "0%";
            statusSpan.textContent = "正在上传 0%...";
            statusSpan.className = "queue-item-status converting";
        }
        if (cardEl) {
            cardEl.classList.add("active-converting");
        }
        updateQueueCountsAndUI();
        
        if (!group.frontFile) {
            group.status = "failed";
            group.error = "缺失身份证正面照，无法解析要素建卡";
            if (bar && statusSpan) {
                bar.className = "queue-item-progress-bar failed";
                statusSpan.textContent = "失败: 缺正面照";
                statusSpan.className = "queue-item-status failed";
            }
            if (cardEl) cardEl.classList.remove("active-converting");
            updateQueueCountsAndUI();
            return;
        }
        
        const formData = new FormData();
        formData.append("file", group.frontFile);
        
        const performOcrRequest = () => {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open("POST", "/api/ocr");
                
                // 监听真实上传进度，0% - 100% 映射到进度条的 0% - 80%
                xhr.upload.addEventListener("progress", (e) => {
                    if (e.lengthComputable) {
                        const percentComplete = Math.round((e.loaded / e.total) * 100);
                        const mappedPercent = Math.round(percentComplete * 0.8);
                        if (bar && statusSpan && group.status === "converting") {
                            bar.style.width = `${mappedPercent}%`;
                            statusSpan.textContent = `上传中 ${percentComplete}%...`;
                        }
                    }
                });
                
                let slowCrawlInterval = null;
                // 上传完毕后切换为“识别中...”，并在 80% - 95% 之间缓慢攀升以提供反馈
                xhr.upload.addEventListener("load", () => {
                    if (bar && statusSpan && group.status === "converting") {
                        bar.style.width = "80%";
                        statusSpan.textContent = "识别中...";
                        
                        let currentWidth = 80;
                        slowCrawlInterval = setInterval(() => {
                            if (currentWidth < 95) {
                                currentWidth += 1;
                                bar.style.width = `${currentWidth}%`;
                            } else {
                                clearInterval(slowCrawlInterval);
                            }
                        }, 400);
                    }
                });
                
                xhr.onload = () => {
                    if (slowCrawlInterval) clearInterval(slowCrawlInterval);
                    
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try {
                            const resData = JSON.parse(xhr.responseText);
                            resolve(resData);
                        } catch (err) {
                            reject(new Error("解析服务器响应失败"));
                        }
                    } else {
                        try {
                            const errData = JSON.parse(xhr.responseText);
                            reject(new Error(errData.detail || `请求失败 (${xhr.status})`));
                        } catch (e) {
                            reject(new Error(`服务响应异常 (${xhr.status})`));
                        }
                    }
                };
                
                xhr.onerror = () => {
                    if (slowCrawlInterval) clearInterval(slowCrawlInterval);
                    reject(new Error("网络连接失败"));
                };
                
                xhr.ontimeout = () => {
                    if (slowCrawlInterval) clearInterval(slowCrawlInterval);
                    reject(new Error("请求超时"));
                };
                
                xhr.send(formData);
            });
        };
        
        try {
            const resData = await performOcrRequest();
            
            if (resData.success && resData.data && resData.data.length > 0) {
                const elements = resData.data[0].elements;
                
                // 1. 正面创建董事卡片
                createNewDirectorFromOcr(elements, group.frontFile);
                
                // 2. 直接物理绑定当前 Group 的反面照 File
                const newDir = directors[directors.length - 1];
                if (newDir && group.backFile) {
                    newDir.backFile = group.backFile;
                    newDir.backUrl = URL.createObjectURL(group.backFile);
                }
                
                // 刷新右侧手风琴显示
                renderDirectors();
                
                group.status = "success";
                if (bar && statusSpan) {
                    bar.className = "queue-item-progress-bar success";
                    bar.style.width = "100%";
                    statusSpan.textContent = "解析成功";
                    statusSpan.className = "queue-item-status success";
                }
                
                // ⚡ 成功解析，触发淡出动画并在 550ms 后从队列彻底清空消失，极爽清爽 UX
                if (cardEl) {
                    cardEl.classList.add("fade-out");
                }
                setTimeout(() => {
                    pairGroups = pairGroups.filter(g => g.id !== group.id);
                    renderPairGroups();
                    updateQueueCountsAndUI();
                }, 550);
                
            } else {
                throw new Error(resData.error || "无法识别身份证正面要素");
            }
            
        } catch (error) {
            console.error(`OCR Error for ${group.frontFile.name}:`, error);
            group.status = "failed";
            group.error = error.message;
            
            if (bar && statusSpan) {
                bar.className = "queue-item-progress-bar failed";
                bar.style.width = "100%";
                statusSpan.textContent = `失败: ${error.message}`;
                statusSpan.className = "queue-item-status failed";
            }
            showNotification(`识别失败: ${group.frontFile.name}，原因: ${error.message}`, "error");
        } finally {
            if (cardEl) cardEl.classList.remove("active-converting");
            updateQueueCountsAndUI();
            
            // 为抵抗云端并发峰值压力，轻微休眠 500ms
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }

    // ==========================================
    // 6. 数据绑定逻辑 (正反关联)
    // ==========================================
    
    // 正面卡片构建
    function createNewDirectorFromOcr(elements, file) {
        const id = "dir_" + Date.now() + "_" + Math.random().toString(36).substring(2, 5);
        const name = elements["姓名"] || "";
        
        const newDirector = {
            id: id,
            director_name_cn: name,
            director_name_en_pinyin: convertChineseToPinyin(name),
            director_id_number: elements["身份证号码"] || elements["公民身份号码"] || "",
            director_id_address: elements["住址"] || "",
            company_name_cn: "",
            company_name_en: "",
            business_nature: "進出口貿易",
            business_code: "045",
            frontFile: file,
            frontUrl: URL.createObjectURL(file),
            backFile: null,
            backUrl: null
        };

        directors.push(newDirector);
        activeDirectorId = id; // 新卡片默认展开
        renderDirectors();
    }

    // 反面照片自动匹配
    function bindBackCardToDirector(file) {
        // 寻找倒数第一个没有反面照的董事
        let matched = false;
        for (let i = directors.length - 1; i >= 0; i--) {
            if (!directors[i].backFile) {
                directors[i].backFile = file;
                directors[i].backUrl = URL.createObjectURL(file);
                matched = true;
                activeDirectorId = directors[i].id; // 展开当前匹配的董事进行预览
                break;
            }
        }

        // 如果没有找到（即先上传了反面），则新建一个空白卡片并把反面挂上
        if (!matched) {
            const id = "dir_" + Date.now() + "_" + Math.random().toString(36).substring(2, 5);
            const newDirector = createBlankDirectorObject(id);
            newDirector.backFile = file;
            newDirector.backUrl = URL.createObjectURL(file);
            directors.push(newDirector);
            activeDirectorId = id;
        }
        renderDirectors();
    }

    function createBlankDirectorObject(id) {
        return {
            id: id,
            director_name_cn: "",
            director_name_en_pinyin: "",
            director_id_number: "",
            director_id_address: "",
            company_name_cn: "",
            company_name_en: "",
            business_nature: "進出口貿易",
            business_code: "045",
            frontFile: null,
            frontUrl: null,
            backFile: null,
            backUrl: null
        };
    }

    // ==========================================
    // 7. 手风琴卡片渲染与双向绑定机制 (Render & Sync)
    // ==========================================
    function renderDirectors() {
        // 1. 清理容器
        directorsContainer.innerHTML = "";

        if (directors.length === 0) {
            emptyState.classList.remove("hidden");
            btnSubmitBatch.disabled = true;
            return;
        }

        emptyState.classList.add("hidden");
        btnSubmitBatch.disabled = false;

        // 2. 循环绘制每个董事手风琴
        directors.forEach((dir, idx) => {
            const isExpanded = dir.id === activeDirectorId;
            const cardEl = document.createElement("div");
            cardEl.className = `accordion-item ${isExpanded ? "active" : ""}`;
            cardEl.id = dir.id;

            // 状态核对计算
            const isOcrReady = dir.director_name_cn && dir.director_id_number && dir.director_id_address;
            const isCompanyReady = dir.company_name_cn || dir.company_name_en;

            const ocrBadge = isOcrReady 
                ? `<span class="badge success">已识要素</span>` 
                : `<span class="badge warning">缺失要素</span>`;
                
            const compBadge = isCompanyReady 
                ? `<span class="badge success">已绑公司</span>` 
                : `<span class="badge pending">待绑公司</span>`;

            cardEl.innerHTML = `
                <!-- 卡片头部 (Header) -->
                <div class="accordion-header">
                    <div class="accordion-header-title">
                        <div class="accordion-avatar">${idx + 1}</div>
                        <div class="accordion-name-text">${dir.director_name_cn || "未命名董事"}</div>
                        <div class="accordion-badges">
                            ${ocrBadge}
                            ${compBadge}
                        </div>
                    </div>
                    <div class="accordion-controls">
                        <button type="button" class="btn-delete-card" title="删除当前卡片">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                <line x1="10" y1="11" x2="10" y2="17"></line>
                                <line x1="14" y1="11" x2="14" y2="17"></line>
                            </svg>
                        </button>
                        <span class="accordion-arrow">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="6 9 12 15 18 9"></polyline>
                            </svg>
                        </span>
                    </div>
                </div>

                <!-- 卡片展开体 (Content) -->
                <div class="accordion-content">
                    <div class="accordion-content-inner">
                        
                        <!-- A. 身份证正反面图片挂载槽 -->
                        <div class="id-slots-container">
                            
                            <!-- 正面槽位 -->
                            <div class="id-slot slot-front">
                                <div class="id-slot-title">📷 身份证正面照</div>
                                ${dir.frontUrl ? `
                                    <div class="id-slot-preview">
                                        <img src="${dir.frontUrl}" alt="正面照">
                                        <button type="button" class="btn-remove-slot-img btn-del-front">×</button>
                                    </div>
                                ` : `
                                    <div class="id-slot-content">正面照 <span>选择上传</span></div>
                                    <input type="file" accept="image/*" class="file-input-hidden input-slot-front">
                                `}
                            </div>

                            <!-- 反面槽位 -->
                            <div class="id-slot slot-back">
                                <div class="id-slot-title">📷 身份证反面照</div>
                                ${dir.backUrl ? `
                                    <div class="id-slot-preview">
                                        <img src="${dir.backUrl}" alt="反面照">
                                        <button type="button" class="btn-remove-slot-img btn-del-back">×</button>
                                    </div>
                                ` : `
                                    <div class="id-slot-content">反面照 <span>选择上传</span></div>
                                    <input type="file" accept="image/*" class="file-input-hidden input-slot-back">
                                `}
                            </div>
                        </div>

                        <!-- B. 表单详细填写区 -->
                        <div class="form-section">
                            <h3>👨‍💼 董事身份要素核准</h3>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>董事中文姓名</label>
                                    <input type="text" class="input-name-cn" value="${dir.director_name_cn}" placeholder="姓名" required>
                                </div>
                                <div class="form-group">
                                    <label>董事英文拼音</label>
                                    <input type="text" class="input-name-pinyin" value="${dir.director_name_en_pinyin}" placeholder="拼音姓名大写" required>
                                </div>
                                <div class="form-group full-width">
                                    <label>身份证号码</label>
                                    <input type="text" class="input-id-number" value="${dir.director_id_number}" placeholder="18位身份证号" required>
                                </div>
                                <div class="form-group full-width">
                                    <label>身份证住址</label>
                                    <input type="text" class="input-id-address" value="${dir.director_id_address}" placeholder="户籍住址全称" required>
                                </div>
                            </div>
                        </div>

                        <div class="form-section">
                            <h3>🏢 绑定拟成立公司</h3>
                            <div class="form-grid">
                                <div class="form-group">
                                    <label>拟成立中文名称</label>
                                    <input type="text" class="input-comp-cn" value="${dir.company_name_cn}" placeholder="须以“有限公司”结尾">
                                </div>
                                <div class="form-group">
                                    <label>拟成立英文名称</label>
                                    <input type="text" class="input-comp-en" value="${dir.company_name_en}" placeholder="须以“LIMITED”结尾">
                                </div>
                                <div class="form-group">
                                    <label>经营业务性质</label>
                                    <input type="text" class="input-nature" value="${dir.business_nature}" required>
                                </div>
                                <div class="form-group">
                                    <label>业务编码</label>
                                    <input type="text" class="input-code" value="${dir.business_code}" required>
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            `;

            // ==========================================
            // 8. 双向数据绑定与 DOM 监听
            // ==========================================
            
            // 展开折叠切换
            cardEl.querySelector(".accordion-header").addEventListener("click", (e) => {
                // 如果点击的是删除按钮，不进行折叠切换
                if (e.target.closest(".btn-delete-card")) return;
                
                if (isExpanded) {
                    activeDirectorId = null;
                } else {
                    activeDirectorId = dir.id;
                }
                renderDirectors();
            });

            // 删除董事卡片
            cardEl.querySelector(".btn-delete-card").addEventListener("click", () => {
                directors = directors.filter(d => d.id !== dir.id);
                if (activeDirectorId === dir.id) {
                    activeDirectorId = directors.length > 0 ? directors[directors.length - 1].id : null;
                }
                renderDirectors();
                showNotification("已成功移除董事卡片", "info");
            });

            // 实时同步表单输入到内存数组中
            const syncField = (inputClass, propertyName, formatFn = null) => {
                const inputEl = cardEl.querySelector(inputClass);
                if (inputEl) {
                    inputEl.addEventListener("input", (e) => {
                        let val = e.target.value;
                        if (formatFn) val = formatFn(val);
                        dir[propertyName] = val;
                        
                        // 动态更新头部姓名标题
                        if (propertyName === "director_name_cn") {
                            cardEl.querySelector(".accordion-name-text").textContent = val || "未命名董事";
                            
                            // 拼音联动
                            const pinyinEl = cardEl.querySelector(".input-name-pinyin");
                            if (pinyinEl && (!dir.director_name_en_pinyin || dir.director_name_en_pinyin.startsWith("PINYIN"))) {
                                const newPinyin = convertChineseToPinyin(val);
                                dir.director_name_en_pinyin = newPinyin;
                                pinyinEl.value = newPinyin;
                            }
                        }
                    });
                }
            };

            syncField(".input-name-cn", "director_name_cn");
            syncField(".input-name-pinyin", "director_name_en_pinyin", (v) => v.toUpperCase());
            syncField(".input-id-number", "director_id_number");
            syncField(".input-id-address", "director_id_address");
            syncField(".input-comp-cn", "company_name_cn");
            syncField(".input-comp-en", "company_name_en", (v) => v.toUpperCase());
            syncField(".input-nature", "business_nature");
            syncField(".input-code", "business_code");

            // C. 独立槽位图片上传/删除处理
            
            // 正面图片槽上传选取
            const inputSlotFront = cardEl.querySelector(".input-slot-front");
            if (inputSlotFront) {
                inputSlotFront.addEventListener("change", (e) => {
                    if (inputSlotFront.files.length > 0) {
                        const file = inputSlotFront.files[0];
                        dir.frontFile = file;
                        dir.frontUrl = URL.createObjectURL(file);
                        triggerOcrForSpecificSlot(file, dir.id, true);
                    }
                });
            }

            // 正面图片槽删除
            const btnDelFront = cardEl.querySelector(".btn-del-front");
            if (btnDelFront) {
                btnDelFront.addEventListener("click", () => {
                    dir.frontFile = null;
                    dir.frontUrl = null;
                    renderDirectors();
                });
            }

            // 反面图片槽上传选取
            const inputSlotBack = cardEl.querySelector(".input-slot-back");
            if (inputSlotBack) {
                inputSlotBack.addEventListener("change", (e) => {
                    if (inputSlotBack.files.length > 0) {
                        const file = inputSlotBack.files[0];
                        dir.backFile = file;
                        dir.backUrl = URL.createObjectURL(file);
                        renderDirectors();
                    }
                });
            }

            // 反面图片槽删除
            const btnDelBack = cardEl.querySelector(".btn-del-back");
            if (btnDelBack) {
                btnDelBack.addEventListener("click", () => {
                    dir.backFile = null;
                    dir.backUrl = null;
                    renderDirectors();
                });
            }

            directorsContainer.appendChild(cardEl);
        });
    }

    // 针对局部卡片槽位的即时 OCR (体验升级)
    async function triggerOcrForSpecificSlot(file, directorId, isFront) {
        showNotification("正在为您智能解析当前上传的身份证照片...", "info");
        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await fetch("/api/ocr", {
                method: "POST",
                body: formData
            });

            if (!response.ok) throw new Error("识别发生故障");
            const resData = await response.json();

            if (resData.success && resData.data && resData.data.length > 0) {
                const elements = resData.data[0].elements;
                const dir = directors.find(d => d.id === directorId);
                if (dir && isFront) {
                    dir.director_name_cn = elements["姓名"] || dir.director_name_cn;
                    dir.director_name_en_pinyin = convertChineseToPinyin(elements["姓名"] || dir.director_name_cn);
                    dir.director_id_number = elements["身份证号码"] || elements["公民身份号码"] || dir.director_id_number;
                    dir.director_id_address = elements["住址"] || dir.director_id_address;
                }
                renderDirectors();
                showNotification("身份证局部解析及反填成功！", "success");
            }
        } catch (error) {
            console.error("Specific OCR failed:", error);
        }
    }

    // ==========================================
    // 9. 汉字常用名转拼音辅助
    // ==========================================
    function convertChineseToPinyin(chineseName) {
        const commonSurnames = {
            '张': 'ZHANG', '章': 'ZHANG', '王': 'WANG', '李': 'LI', '赵': 'ZHAO', '刘': 'LIU', 
            '陈': 'CHEN', '杨': 'YANG', '黄': 'HUANG', '吴': 'WU', '周': 'ZHOU', '徐': 'XU', 
            '孙': 'SUN', '马': 'MA', '朱': 'ZHU', '胡': 'HU', '林': 'LIN', '郭': 'GUO', 
            '何': 'HE', '高': 'GAO', '罗': 'LUO', '郑': 'ZHENG', '梁': 'LIANG', '谢': 'XIE', 
            '宋': 'SONG', '唐': 'TANG', '许': 'XU', '邓': 'DENG', '韩': 'HAN', '冯': 'FENG', 
            '曹': 'CAO', '彭': 'PENG', '曾': 'ZENG', '肖': 'XIAO', '田': 'TIAN', '董': 'DONG', 
            '潘': 'PAN', '袁': 'YUAN', '于': 'YU', '蒋': 'JIANG', '蔡': 'CAI'
        };

        if (!chineseName) return "";
        const surnameChar = chineseName.charAt(0);
        const surnamePinyin = commonSurnames[surnameChar] || "PINYIN";
        return `${surnamePinyin} OTHER_NAMES`;
    }

    // 手动追加董事空白卡片
    btnAddDirector.addEventListener("click", () => {
        const id = "dir_" + Date.now() + "_" + Math.random().toString(36).substring(2, 5);
        const newDir = createBlankDirectorObject(id);
        directors.push(newDir);
        activeDirectorId = id;
        renderDirectors();
        showNotification("已手动新增空白卡片，请在卡片内上传照片或填写信息", "info");
    });

    // ==========================================
    // 10. 表单批量打包与自描述归档 ZIP 一键下载
    // ==========================================
    btnSubmitBatch.addEventListener("click", async () => {
        if (directors.length === 0) return;

        // 1. 数据完整性前置检验
        let invalidCount = 0;
        let invalidItem = null;

        for (let i = 0; i < directors.length; i++) {
            const dir = directors[i];
            const hasInfo = dir.director_name_cn && dir.director_id_number && dir.director_id_address;
            const hasCompany = dir.company_name_cn || dir.company_name_en;
            
            if (!hasInfo || !hasCompany) {
                invalidCount++;
                if (!invalidItem) invalidItem = dir;
            }
        }

        if (invalidCount > 0) {
            activeDirectorId = invalidItem.id; // 展开有问题的卡片以给予视觉指引
            renderDirectors();
            showNotification(`有 ${invalidCount} 张董事卡片要素缺失或未绑定公司，请补全后再次生成！`, "error");
            return;
        }

        // 2. 状态切换
        btnSubmitBatch.disabled = true;
        btnText.classList.add("hidden");
        btnLoading.classList.remove("hidden");
        hideNotification();

        // 3. 构建多表单批量提交包 (FormData)
        const formData = new FormData();
        const batchConfigList = [];

        directors.forEach((dir, idx) => {
            const frontKey = `front_${idx}`;
            const backKey = `back_${idx}`;

            // 装载文本配置
            batchConfigList.push({
                company_name_cn: dir.company_name_cn.trim(),
                company_name_en: dir.company_name_en.trim(),
                business_nature: dir.business_nature,
                business_code: dir.business_code,
                director_name_cn: dir.director_name_cn,
                director_name_en_pinyin: dir.director_name_en_pinyin.replace(/\(.*\)/g, "").trim(),
                director_id_number: dir.director_id_number,
                director_id_address: dir.director_id_address,
                front_file_key: dir.frontFile ? frontKey : "",
                back_file_key: dir.backFile ? backKey : ""
            });

            // 装载二进制文件
            if (dir.frontFile) {
                formData.append(frontKey, dir.frontFile);
            }
            if (dir.backFile) {
                formData.append(backKey, dir.backFile);
            }
        });

        // 压入 JSON 数组配置
        formData.append("batch_config", JSON.stringify(batchConfigList));

        // 4. 触发后端打包下载
        try {
            const response = await fetch("/api/generate-batch", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                const errJson = await response.json();
                throw new Error(errJson.detail || "批量打包失败");
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);

            const a = document.createElement("a");
            a.href = url;
            a.download = "NNC1_Batch_Documents.zip";
            document.body.appendChild(a);
            a.click();

            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            showNotification("🎉 NNC1 批量自描述压缩包已生成并启动下载！", "success");

        } catch (error) {
            console.error("Batch Generate Error:", error);
            showNotification(error.message, "error");
        } finally {
            // 恢复按钮状态
            btnSubmitBatch.disabled = false;
            btnText.classList.remove("hidden");
            btnLoading.classList.add("hidden");
        }
    });

    // ==========================================
    // 11. 全局图片预览灯箱交互逻辑 (Lightbox Modal)
    // ==========================================
    const imagePreviewModal = document.getElementById("imagePreviewModal");
    const modalPreviewImg = document.getElementById("modalPreviewImg");
    const modalImageCaption = document.getElementById("modalImageCaption");
    const modalCloseBtn = document.getElementById("modalCloseBtn");
    
    // 打开预览灯箱
    function openImagePreview(src, captionText) {
        if (!imagePreviewModal || !modalPreviewImg || !modalImageCaption) return;
        modalPreviewImg.src = src;
        modalImageCaption.textContent = captionText || "证件照预览";
        imagePreviewModal.classList.remove("hidden");
    }
    
    // 关闭预览灯箱
    function closeImagePreview() {
        if (!imagePreviewModal) return;
        imagePreviewModal.classList.add("hidden");
        if (modalPreviewImg) {
            // 延迟清空 src 以免淡出时闪烁
            setTimeout(() => {
                if (imagePreviewModal.classList.contains("hidden")) {
                    modalPreviewImg.src = "";
                }
            }, 300);
        }
    }
    
    // 点击关闭按钮关闭
    if (modalCloseBtn) {
        modalCloseBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            closeImagePreview();
        });
    }
    
    // 点击背景空白处关闭
    if (imagePreviewModal) {
        imagePreviewModal.addEventListener("click", (e) => {
            if (e.target === imagePreviewModal) {
                closeImagePreview();
            }
        });
    }
    
    // 监听键盘 Esc 键关闭
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" || e.key === "Esc") {
            closeImagePreview();
        }
    });
    
    // 使用事件代理拦截所有预览图片的点击
    document.addEventListener("click", (e) => {
        // 1. 左侧预配对队列里的图片点击
        const queueImg = e.target.closest(".preview-slot.has-file img");
        if (queueImg) {
            e.stopPropagation();
            const cardEl = queueImg.closest(".pair-group-card");
            const titleEl = cardEl ? cardEl.querySelector(".pair-title") : null;
            let groupName = "证件照预览";
            if (titleEl) {
                groupName = titleEl.innerText.replace(/\s+/g, " ").trim();
            }
            const isFront = queueImg.closest(".preview-slot").classList.contains("slot-front");
            const sideText = isFront ? "正面照 (信息面)" : "反面照 (国徽面)";
            openImagePreview(queueImg.src, `${groupName} - ${sideText}`);
            return;
        }
        
        // 2. 右侧已生成董事折叠卡片里的图片点击
        const accordionImg = e.target.closest(".id-slot-preview img");
        if (accordionImg) {
            e.stopPropagation();
            const accordionItem = accordionImg.closest(".accordion-item");
            const nameEl = accordionItem ? accordionItem.querySelector(".accordion-name-text") : null;
            let directorName = "董事证件照";
            if (nameEl) {
                directorName = nameEl.textContent.trim();
            }
            const isFront = accordionImg.closest(".id-slot").classList.contains("slot-front");
            const sideText = isFront ? "正面照" : "反面照";
            openImagePreview(accordionImg.src, `${directorName} - ${sideText}`);
            return;
        }
    });
});
