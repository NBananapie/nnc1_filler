# nnc1_web/backend/ocr_service.py
import urllib.request
import urllib.parse
import urllib.error
import time
import json
import base64
import ssl
import io
from PIL import Image, ImageOps

def compress_image_if_needed(image_bytes: bytes, max_size_kb: int = 1500, max_dim: int = 2000) -> bytes:
    """
    如果图片大小超过 max_size_kb 或分辨率长边超过 max_dim，进行自动等比例缩小与 JPEG 压缩，
    降低上传带宽消耗，防范阿里云端由于图片太大处理超时或内存溢出导致 500 报错。
    """
    try:
        # 如果文件大小小于限制，且长宽也都在合理范围内，则跳过压缩以保持最高精度
        if len(image_bytes) < max_size_kb * 1024:
            with Image.open(io.BytesIO(image_bytes)) as img:
                w, h = img.size
                if w <= max_dim and h <= max_dim:
                    return image_bytes
                    
        with Image.open(io.BytesIO(image_bytes)) as img:
            # 根据 EXIF 旋转信息把图片转正
            try:
                img = ImageOps.exif_transpose(img)
            except:
                pass
                
            w, h = img.size
            if w > max_dim or h > max_dim:
                if w > h:
                    new_w = max_dim
                    new_h = int(h * (max_dim / w))
                else:
                    new_h = max_dim
                    new_w = int(w * (max_dim / h))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
            # 压缩为 JPEG 字节流
            out_io = io.BytesIO()
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(out_io, format="JPEG", quality=85)
            compressed_bytes = out_io.getvalue()
            
            # 只有压缩后确实变小了才返回压缩包，否则返回原图
            if len(compressed_bytes) < len(image_bytes):
                return compressed_bytes
            return image_bytes
    except Exception as e:
        print(f"[Warning] Image compression failed, fallback to original: {e}")
        return image_bytes

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
        # 捕获并解析详细错误流（如阿里云网关报错头与错误内容）
        err_details = ""
        err_msg = str(e)
        
        # 提取阿里云 API 网关 headers 错误（如 A403QD - 欠费/频次超限，A401AC - AppCode 不存在）
        if hasattr(e, "headers") and e.headers:
            ca_err_msg = e.headers.get("X-Ca-Error-Message") or e.headers.get("x-ca-error-message")
            ca_err_code = e.headers.get("X-Ca-Error-Code") or e.headers.get("x-ca-error-code")
            if ca_err_msg or ca_err_code:
                err_msg = f"{err_msg} (Aliyun Gateway: {ca_err_code or ''} - {ca_err_msg or ''})"
                
        if hasattr(e, "read"):
            try:
                err_bytes = e.read()
                # 尝试用 UTF-8 解码，如果失败试用 GBK 解码（阿里云某些报错使用 GBK）
                try:
                    err_details = err_bytes.decode("utf-8")
                except:
                    err_details = err_bytes.decode("gbk", errors="ignore")
                    
                # 尝试解析 JSON 错误体 (获取 errorCode 和 errorMsg)
                try:
                    body_json = json.loads(err_details)
                    if "errorMsg" in body_json:
                        err_msg = f"{err_msg} [API Detail: {body_json.get('errorMsg')}]"
                except:
                    pass
            except:
                pass
        return {"success": False, "error": f"OCR API 请求失败: {err_msg}", "details": err_details}
