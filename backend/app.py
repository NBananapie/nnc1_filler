# nnc1_web/backend/app.py
import os
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.ocr_service import ocr_card_from_bytes
from backend.fill_service import generate_nnc1_docx_bytes, generate_batch_zip_bytes

app = FastAPI(
    title="NNC1 Web 极简全自动填表系统 API",
    description="提供高精度身份证 OCR 提取与一键批量打包生成 NNC1.docx 表单并归档的能力。",
    version="1.1.0"
)

# 1. 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 单个生成请求数据模型
class NNC1GenerateRequest(BaseModel):
    company_name_cn: str = Field(..., description="拟成立公司中文名称")
    company_name_en: str = Field(..., description="拟成立公司英文名称")
    business_nature: str = Field("進出口貿易", description="业务性质")
    business_code: str = Field("045", description="业务编码")
    director_name_cn: str = Field(..., description="董事中文姓名")
    director_name_en_pinyin: str = Field(..., description="董事拼音/英文姓名")
    director_id_number: str = Field(..., description="董事身份证号码")
    director_id_address: str = Field(..., description="董事通常居住地址")

# 3. 核心 API 端点：OCR 解析
@app.post("/api/ocr")
async def api_ocr(file: UploadFile = File(...)):
    """
    上传一张董事的身份证图片，提取出其中的文字并格式化返回要素。
    """
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".bmp"]:
        raise HTTPException(status_code=400, detail="只允许上传 JPG/PNG/BMP 等常见格式的图片")
        
    try:
        content = await file.read()
        res = ocr_card_from_bytes(content)
        
        if not res.get("success"):
            raise HTTPException(status_code=500, detail=res.get("error"))
            
        return res
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR 引擎内部发生异常: {str(e)}")

# 4. 单件生成下载 API
@app.post("/api/generate")
async def api_generate(req_data: NNC1GenerateRequest):
    """
    提交审核对齐后的结构化数据，返回生成的 NNC1 Word 字节流进行前端下载。
    """
    try:
        docx_bytes = generate_nnc1_docx_bytes(req_data.model_dump())
        comp_name = req_data.company_name_cn or req_data.company_name_en
        filename = f"NNC1_{comp_name}.docx"
        
        from urllib.parse import quote
        safe_filename = quote(filename)
        
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=500, detail=str(fnf))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档填充器运行失败: {str(e)}")

# 5. 核心升级 API 端点：批量生成并打包 ZIP
@app.post("/api/generate-batch")
async def api_generate_batch(request: Request):
    """
    接收批量董事表单配置与上传的身份证正反图片文件，
    输出重命名归类打包好的 ZIP 归档字节流。
    """
    try:
        # 解析多表单 Multipart 数据
        form_data = await request.form()
        
        print("\n=== [SAFE DEBUG] api_generate_batch ===")
        print(f"  Form fields present: {list(form_data.keys())}")
        
        # A. 提取批量 JSON 配置
        batch_config_str = form_data.get("batch_config")
        if not batch_config_str:
            raise HTTPException(status_code=400, detail="缺失 batch_config 批量配置 JSON 数据")
            
        # 安全打印配置 (滤除 Emoji/中文，避免 gbk 崩溃)
        safe_config_print = str(batch_config_str).encode('ascii', 'ignore').decode('ascii')
        print(f"  batch_config_str: {safe_config_print[:300]}")
            
        try:
            batch_data = json.loads(str(batch_config_str))
        except Exception as je:
            raise HTTPException(status_code=400, detail=f"解析批量配置 JSON 失败: {str(je)}")
            
        if not isinstance(batch_data, list):
            raise HTTPException(status_code=400, detail="批量配置数据必须是一个 JSON 数组列表")
            
        # B. 提取所有挂载的文件，构建名称/字节流映射
        file_mapping = {}
        for key, value in form_data.items():
            val_type = type(value).__name__
            val_filename = getattr(value, "filename", "")
            
            # 使用健壮的类型名称和 hasattr 检测，兼容所有 FastAPI/Starlette 版本
            if (val_type == "UploadFile" or hasattr(value, "file")) and val_filename:
                print(f"  [Batch Package] Processing file key: {key}, filename: {val_filename}")
                file_bytes = await value.read()
                file_mapping[key] = {
                    "filename": val_filename,
                    "bytes": file_bytes
                }
                
        # C. 驱动服务层，打包生成 ZIP
        zip_bytes = generate_batch_zip_bytes(batch_data, file_mapping)
        
        filename = "NNC1_Batch_Documents.zip"
        from urllib.parse import quote
        safe_filename = quote(filename)
        
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量打包失败: {str(e)}")

# 6. 挂载静态前端资源
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {"status": "success", "message": "FastAPI API 服务已就绪。前端资源未挂载。"}
