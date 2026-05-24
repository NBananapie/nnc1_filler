# nnc1_web/backend/fill_service.py
import os
import sys
import shutil
import zipfile
import tempfile
from pathlib import Path

# 自包含云原生局部导入，彻底杜绝外部绝对路径依赖
from backend.fill_nnc1 import process_document_global
from backend.fill_nnc1_simple import generate_full_json

TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "NNC1_template.docx"

def pack_docx(source_dir: str, output_filename: str):
    """
    将解包目录打包为 .docx 文件
    """
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as docx:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                arcname = arcname.replace(os.sep, '/')
                docx.write(file_path, arcname)

def generate_nnc1_docx_bytes(simple_data: dict) -> bytes:
    """
    接收前端填写的简易版公司及董事数据，进行完整性补全与注入，返回生成的 .docx 文件的二进制字节流。
    
    Args:
        simple_data: 包含以下字段的 dict:
            - company_name_cn (公司中文名称)
            - company_name_en (公司英文名称)
            - business_nature (业务性质，默认 "進出口貿易")
            - business_code (业务编码，默认 "045")
            - director_name_cn (董事中文姓名)
            - director_name_en_pinyin (董事英文拼音姓名)
            - director_id_number (董事身份证号码)
            - director_id_address (董事通常住址)
            
    Returns:
        bytes: 生成的 .docx 二进制内容
    """
    # 1. 验证模版是否存在
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"找不到 NNC1 模版文件: {TEMPLATE_PATH}")
        
    # 2. 将简易数据扩展为全量结构化数据
    full_data = generate_full_json(simple_data)
    
    # 3. 创建项目内临时工作区 (避免使用全局 /tmp)
    workspace_scratch = Path(__file__).resolve().parent / "scratch_temp"
    workspace_scratch.mkdir(exist_ok=True, parents=True)
    
    # 使用 tempfile 在我们指定的 workspace_scratch 下创建独一无二的子目录
    with tempfile.TemporaryDirectory(dir=str(workspace_scratch)) as temp_dir:
        temp_unpack_dir = os.path.join(temp_dir, "unpacked")
        os.makedirs(temp_unpack_dir, exist_ok=True)
        
        # 解压模版 docx
        with zipfile.ZipFile(str(TEMPLATE_PATH), 'r') as z:
            z.extractall(temp_unpack_dir)
            
        doc_xml_path = os.path.join(temp_unpack_dir, 'word', 'document.xml')
        if not os.path.exists(doc_xml_path):
            raise FileNotFoundError("Word 模版中缺失 word/document.xml")
            
        # 读取主 XML
        with open(doc_xml_path, 'r', encoding='utf-8') as f:
            xml_str = f.read()
            
        # 移除非法字符，进行数据注入
        xml_str = xml_str.replace("\xa0", " ")
        new_xml = process_document_global(xml_str, full_data)
        
        # 写回主 XML
        with open(doc_xml_path, 'w', encoding='utf-8') as f:
            f.write(new_xml)
            
        # 重新打包
        output_file_path = os.path.join(temp_dir, "output.docx")
        pack_docx(temp_unpack_dir, output_file_path)
        
        # 读取字节流
        with open(output_file_path, 'rb') as f:
            docx_bytes = f.read()
            
    return docx_bytes

def generate_batch_zip_bytes(batch_data: list, file_mapping: dict) -> bytes:
    """
    接收前端批量填写的董事与公司数据列表，以及上传的身份证正反照映射。
    在工作区生成自描述目录结构，填充 NNC1 表单并拷贝重命名身份证，最后压缩为 ZIP 并返回其字节流。
    
    Args:
        batch_data: 包含多个简单董事/公司 dict 的列表
        file_mapping: 包含上传文件字节与原文件名的字典，格式如 {"front_0": {"bytes": b"...", "filename": "1.jpg"}}
        
    Returns:
        bytes: 压缩包的二进制内容
    """
    # 1. 验证模版是否存在
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"找不到 NNC1 模版文件: {TEMPLATE_PATH}")

    # 2. 创建临时工作区
    workspace_scratch = Path(__file__).resolve().parent / "scratch_temp"
    workspace_scratch.mkdir(exist_ok=True, parents=True)
    
    with tempfile.TemporaryDirectory(dir=str(workspace_scratch)) as temp_dir:
        # 批量输出文件夹根目录
        batch_output_dir = Path(temp_dir) / "nnc1_batch"
        batch_output_dir.mkdir(exist_ok=True)
        
        for idx, item in enumerate(batch_data, start=1):
            comp_cn = item.get("company_name_cn", "").strip()
            comp_en = item.get("company_name_en", "").strip()
            director_cn = item.get("director_name_cn", "").strip()
            
            # 自描述文件夹名称: "编号、公司中文名称" 或 "编号、公司英文名称"
            folder_name = f"{idx}、{comp_cn or comp_en}"
            company_folder = batch_output_dir / folder_name
            company_folder.mkdir(exist_ok=True)
            
            # A. 填充生成 NNC1 表单
            full_data = generate_full_json(item)
            temp_unpack_dir = company_folder / "temp_unpack"
            temp_unpack_dir.mkdir(exist_ok=True)
            
            # 解压模版
            with zipfile.ZipFile(str(TEMPLATE_PATH), 'r') as z:
                z.extractall(str(temp_unpack_dir))
                
            doc_xml_path = temp_unpack_dir / 'word' / 'document.xml'
            with open(str(doc_xml_path), 'r', encoding='utf-8') as f:
                xml_str = f.read()
                
            xml_str = xml_str.replace("\xa0", " ")
            new_xml = process_document_global(xml_str, full_data)
            
            with open(str(doc_xml_path), 'w', encoding='utf-8') as f:
                f.write(new_xml)
                
            # 打包成独立的 docx
            docx_filename = f"NNC1_{comp_cn or comp_en}.docx"
            docx_filepath = company_folder / docx_filename
            pack_docx(str(temp_unpack_dir), str(docx_filepath))
            
            # 清理临时解包目录
            shutil.rmtree(str(temp_unpack_dir))
            
            # B. 拷贝并重命名身份证正面照
            front_key = item.get("front_file_key")
            if front_key and front_key in file_mapping:
                file_info = file_mapping[front_key]
                filename = file_info["filename"]
                file_bytes = file_info["bytes"]
                ext = os.path.splitext(filename)[1] or ".jpg"
                dest_name = f"董事_{director_cn}_身份证_正面{ext}"
                with open(str(company_folder / dest_name), "wb") as f:
                    f.write(file_bytes)
                    
            # C. 拷贝并重命名身份证反面照
            back_key = item.get("back_file_key")
            if back_key and back_key in file_mapping:
                file_info = file_mapping[back_key]
                filename = file_info["filename"]
                file_bytes = file_info["bytes"]
                ext = os.path.splitext(filename)[1] or ".jpg"
                dest_name = f"董事_{director_cn}_身份证_反面{ext}"
                with open(str(company_folder / dest_name), "wb") as f:
                    f.write(file_bytes)
                    
        # 3. 将整个批量根目录打包成 ZIP
        zip_archive_base = Path(temp_dir) / "NNC1_Batch_Documents"
        shutil.make_archive(str(zip_archive_base), 'zip', str(batch_output_dir))
        
        # 4. 读取打包好的 ZIP 二进制字节
        zip_filepath = Path(temp_dir) / "NNC1_Batch_Documents.zip"
        with open(str(zip_filepath), "rb") as f:
            zip_bytes = f.read()
            
    return zip_bytes
