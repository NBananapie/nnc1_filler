# nnc1_web/backend/ocr_service.py
import time
import json
import base64
import requests

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
        
        headers = {
            "Authorization": f"APPCODE {appcode}",
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json"
        }
        
        payload = {"img": img_base64}
        
        # 3. 发送请求 (包含指数退避自动重试机制，同时针对限流和网络超时进行重试)
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                # 使用 requests，设置 connect=15s, read/write=60s 的超时阈值，比 urllib 更稳健地发送大文件
                response = requests.post(url, json=payload, headers=headers, timeout=(15, 60))
                
                # 针对 430 (Aliyun 限流) 或 429 (标准限流) 进行自动延迟重试
                if response.status_code in [429, 430] and attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))  # 依次等待 1s, 2s
                    continue
                    
                response.raise_for_status()
                break  # 成功获取结果，跳出重试循环
            except requests.exceptions.RequestException as re:
                # 针对网络超时、写超时或连接断开进行自动重试
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise re
                
        if response is None:
            raise Exception("未收到响应")
            
        data = response.json()
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
            return {"success": True, "data": [{"card_type": "未知", "elements": data}]}
            
    except Exception as e:
        err_msg = str(e)
        err_details = ""
        
        # 提取详细报错（包含阿里云 API 网关 headers 错误）
        if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
            headers = e.response.headers
            ca_err_msg = headers.get("X-Ca-Error-Message") or headers.get("x-ca-error-message")
            ca_err_code = headers.get("X-Ca-Error-Code") or headers.get("x-ca-error-code")
            if ca_err_msg or ca_err_code:
                err_msg = f"{err_msg} (Aliyun Gateway: {ca_err_code or ''} - {ca_err_msg or ''})"
                
            try:
                err_details = e.response.text
                body_json = e.response.json()
                if "errorMsg" in body_json:
                    err_msg = f"{err_msg} [API Detail: {body_json.get('errorMsg')}]"
            except:
                pass
        return {"success": False, "error": f"OCR API 请求失败: {err_msg}", "details": err_details}
