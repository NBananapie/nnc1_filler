#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NNC1 Auto-Filler Simple Version: 简化版自动填表引擎
用户仅需提供基本身份与公司名称，其余秘书地址、股权结构、总值合计等细节均自动归一化与固定填充。
"""
import sys
import os
import json
import re
from datetime import datetime

# 导入核心的 process_document_global 函数
try:
    from backend.fill_nnc1 import process_document_global
except ImportError:
    try:
        from fill_nnc1 import process_document_global
    except ImportError:
        # 兼容直接从 nnc1-simple 路径运行
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "nnc1-filler", "scripts")))
        sys.path.append(r"D:\AI-project\Projects\kingzhong5skills\nnc1-filler\scripts")
        from fill_nnc1 import process_document_global


def parse_china_id_address(addr_str):
    """
    智能解析中国大陆身份证地址。
    例如: "廣東省湛江市坡頭區南三鎮湖村242號" -> 
    {
        "flat_floor_block": "242號",
        "building": "",
        "street": "坡頭區南三鎮湖村",
        "district": "廣東省湛江市",
        "region": "中國"
    }
    """
    addr_str = addr_str.strip()
    region = "中國"
    district = ""
    street = ""
    flat = ""
    building = ""
    
    # 提取省份与城市/县区 (District)
    prov_m = re.match(r'^([^省市]+省|[^自治區]+自治區|北京|上海|天津|重慶)', addr_str)
    if prov_m:
        prov = prov_m.group(1)
        rest = addr_str[len(prov):]
        # 匹配城市
        city_m = re.match(r'^([^市縣區]+[市州地區盟])', rest)
        if city_m:
            city = city_m.group(1)
            district = prov + city
            rest = rest[len(city):]
        else:
            # 匹配县区
            county_m = re.match(r'^([^縣區市]+[縣區市])', rest)
            if county_m:
                county = county_m.group(1)
                district = prov + county
                rest = rest[len(county):]
            else:
                district = prov
                rest = rest
    else:
        district = ""
        rest = addr_str
        
    # 提取门牌号/房号 (Flat/Floor/Block)
    num_m = re.search(r'(\d+號|\d+室|\d+樓|頂樓\d+號|頂樓\d+室)?$', rest)
    if num_m and num_m.group(1):
        flat = num_m.group(1)
        street = rest[:-len(flat)].strip()
    else:
        num_m2 = re.search(r'([^號樓室]+[號樓室])$', rest)
        if num_m2:
            flat = num_m2.group(1)
            street = rest[:-len(flat)].strip()
        else:
            street = rest
            flat = ""
            
    return {
        "flat_floor_block": flat,
        "building": building,
        "street": street,
        "district": district,
        "region": region
    }


def generate_full_json(simple_data):
    """
    从简单版 JSON 扩展为全量填充 NNC1 所需的数据格式。
    """
    # 提取身份证信息
    id_num = simple_data.get("director_id_number", "").strip()
    birth_date = ""
    if len(id_num) == 18:
        # 18位身份证号：从第7位到14位为出生日期 YYYYMMDD
        birth_str = id_num[6:14]
        try:
            birth_date = f"{birth_str[0:4]}-{birth_str[4:6]}-{birth_str[6:8]}"
        except IndexError:
            pass
            
    # 解析身份证地址为通常住址
    raw_addr = simple_data.get("director_id_address", "")
    if isinstance(raw_addr, dict):
        parsed_addr = raw_addr
    else:
        parsed_addr = parse_china_id_address(raw_addr)
    
    # 拆分拼音英文名
    pinyin_name = simple_data.get("director_name_en_pinyin", "").strip().upper()
    surname = ""
    other_names = ""
    if pinyin_name:
        parts = pinyin_name.split()
        if len(parts) >= 1:
            surname = parts[0]
            other_names = " ".join(parts[1:])
            
    current_date = datetime.now().strftime("%d/%m/%Y")
    
    # 固定的商业秘书、提交人、注册地址、股权详情
    full_data = {
        "company": {
            "name_en": simple_data.get("company_name_en", ""),
            "name_cn": simple_data.get("company_name_cn", "") or "",
            "type": "private",
            "business_nature": simple_data.get("business_nature", "進出口貿易"),
            "business_code": simple_data.get("business_code", "045")
        },
        "registered_office": {
            "flat_floor_block": "二期8樓D07室",
            "building": "啟德工廠大廈",
            "street": "景福街99號",
            "district": "新蒲崗",
            "region": "香港"
        },
        "presenter": {
            "name_cn": "金中（香港）商務集團有限公司",
            "name_en": "HK JINZHONG BUSINESS GROUP LIMITED",
            "address": "7樓721A室,星光行,梳士巴利道3號,尖沙咀,香港",
            "phone": "61588111",
            "email": "service@crf.hk"
        },
        "contact": {
            "email": "service@crf.hk",
            "phone": "+852 61588111"
        },
        "share_capital": {
            "class": "普通股",
            "total_shares": 10000,
            "currency": "港元",
            "total_amount": 10000,
            "paid_up": 10000,
            "unpaid": 0
        },
        "founders": [
            {
                "type": "natural_person",
                "name_cn": simple_data.get("director_name_cn", ""),
                "surname_en": surname,
                "other_names_en": other_names,
                "address": parsed_addr,
                "shares_class": "普通股",
                "shares_number": 10000,
                "shares_amount": 10000,
                "hkid_partial": "",
                "hkid_full": ""
            }
        ],
        "secretary": {
            "type": "body_corporate",
            "name_cn": "金中（香港）商務集團有限公司",
            "name_en": "HK JINZHONG BUSINESS GROUP LIMITED",
            "address": {
                "flat_floor_block": "7樓721A室",
                "building": "星光行",
                "street": "梳士巴利道3號",
                "district": "尖沙咀",
                "region": "香港"
            },
            "email": "service@crf.hk",
            "business_registration_number": "71580904",
            "tcsp_licence": "TC007239"
        },
        "directors": [
            {
                "type": "natural_person",
                "name_cn": simple_data.get("director_name_cn", ""),
                "surname_en": surname,
                "other_names_en": other_names,
                "address": {
                    "flat_floor_block": "二期8樓D07室",
                    "building": "啟德工廠大廈",
                    "street": "景福街99號",
                    "district": "新蒲崗",
                    "region": "香港"
                },
                "email": "service@crf.hk" if simple_data.get("company_name_en") == "ULIP GROUP LIMITED" else "",
                "hkid_partial": "",
                "id_type": "identity_card",
                "id_name": "中國身份證號碼",
                "id_full": id_num,
                "usual_residential_address": parsed_addr
            }
        ],
        "statement": {
            "signed_name": simple_data.get("director_name_cn", ""),
            "date": current_date,
            "birth_date": birth_date
        }
    }
    
    return full_data



def main():
    if len(sys.argv) < 3:
        print("Usage: python fill_nnc1_simple.py <simple_data.json> <unpacked_docx_dir>")
        sys.exit(1)
        
    simple_json_path = sys.argv[1]
    unpacked_dir = sys.argv[2]
    
    if not os.path.exists(simple_json_path):
        print(f"Error: {simple_json_path} not found.")
        sys.exit(1)
        
    doc_xml = os.path.join(unpacked_dir, 'word', 'document.xml')
    if not os.path.exists(doc_xml):
        print(f"Error: {doc_xml} not found.")
        sys.exit(1)
        
    with open(simple_json_path, 'r', encoding='utf-8') as f:
        simple_data = json.load(f)
        
    # 自动扩展成完整版的 JSON
    full_data = generate_full_json(simple_data)
    
    # 打印部分调试信息
    print(f"=== 自动填充扩展 ===")
    print(f"公司中文: {full_data['company']['name_cn']}")
    print(f"董事姓名: {full_data['directors'][0]['name_cn']} ({full_data['directors'][0]['surname_en']} {full_data['directors'][0]['other_names_en']})")
    print(f"生日日期: {full_data['statement']['birth_date']}")
    print(f"解析地址: {json.dumps(full_data['founders'][0]['address'], ensure_ascii=False)}")
    print(f"====================")
    
    with open(doc_xml, 'r', encoding='utf-8') as f:
        xml_str = f.read()
        
    # 调用 fill_nnc1 核心处理引擎
    new_xml = process_document_global(xml_str, full_data)
    
    with open(doc_xml, 'w', encoding='utf-8') as f:
        f.write(new_xml)
        
    print("document.xml updated successfully via Simple Filler.")


if __name__ == "__main__":
    main()
