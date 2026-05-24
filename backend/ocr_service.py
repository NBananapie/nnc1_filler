# nnc1_web/backend/ocr_service.py
import urllib.request
import urllib.parse
import urllib.error
import time
import json
import base64
import ssl

def ocr_card_from_bytes(image_bytes: bytes) -> dict:
    """
    接收身份证图片的二进制字节流，调用阿里云混贴 OCR API，返回要素过滤后的结构化 dict。
    
    Args:
        image_bytes: 图片文件的二进制内容
        
    Returns:
        dict: 包含识别出的卡证类型和要素详情，若失败则抛出 Exception 或返回带 error 的 dict。
    """
    try:
        # 1. 转换为 Base64
        img_base64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # 2. 构造请求参数
        url = "https://multidcard.market.alicloudapi.com/ocrservice/mixedMultiIdcard"
        appcode = "de78c45beec34f6e8ea14140c48634d6"
        
        payload = json.dumps({"img": img_base64})
        
        req = urllib.request.Request(url, data=payload.encode("utf-8"), method="POST")
        req.add_header("Authorization", f"APPCODE {appcode}")
        req.add_header("Content-Type", "application/json; charset=UTF-8")
        req.add_header("Accept", "application/json")
        
        # 忽略 SSL 校验，彻底防止 TLS 握手故障
        ctx = ssl._create_unverified_context()
        
        # 3. 发送请求 (包含指数退避自动重试机制，抵抗 QPS 峰值限流)
        
        content = ""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=25) as response:
                    content = response.read().decode("utf-8")
                break  # 成功获取结果，跳出重试循环
            except urllib.error.HTTPError as he:
                # 针对 430 (Aliyun 限流) 或 429 (标准限流) 进行自动延迟重试
                if he.code in [430, 429] and attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))  # 依次等待 1s, 2s
                    continue
                raise he
            
        data = json.loads(content)
        extracted_results = []
        
        # 4. 解析结果要素
        if "subMsgs" in data:
            for msg in data["subMsgs"]:
                msg_type = msg.get("type", "身份证")
                result_info = msg.get("result", {})
                card_data = result_info.get("data", {})
                
                if card_data:
                    extracted_results.append({
                        "card_type": msg_type,
                        "elements": card_data
                    })
                    
        if extracted_results:
            return {"success": True, "data": extracted_results}
        else:
            # 回退机制，返回原始数据或给出提示
            return {"success": True, "data": [{"card_type": "未知", "elements": data}]}
            
    except Exception as e:
        # 捕获详细错误流
        err_details = ""
        if hasattr(e, "read"):
            try:
                err_details = e.read().decode("utf-8")
            except:
                pass
        return {"success": False, "error": f"OCR API 请求失败: {str(e)}", "details": err_details}
