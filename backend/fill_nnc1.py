#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NNC1 Auto-Filler v3: 重构优化版
支持: 全局边界查找隔离、提交人信息、中国大陆身份证、陈述书签署、底栏出生日期
"""
import sys, os, json, re, copy


def strip_tags(xml_str):
    return re.sub(r'<[^>]+>', '', xml_str)


def inject_data_into_cell(tc_xml, data_text, color=None):
    """将 data_text 注入 <w:tc>，保留 tcPr/pPr 格式。"""
    if not data_text:
        return tc_xml
    tcpr_m = re.search(r'<w:tcPr\b.*?>.*?</w:tcPr>', tc_xml, re.DOTALL)
    tcpr = tcpr_m.group(0) if tcpr_m else ""
    p_m = re.search(r'<w:p\b.*?>', tc_xml, re.DOTALL)
    p_start = p_m.group(0) if p_m else "<w:p>"
    ppr_m = re.search(r'<w:pPr\b.*?>.*?</w:pPr>', tc_xml, re.DOTALL)
    ppr = ppr_m.group(0) if ppr_m else ""
    color_tag = f'<w:color w:val="{color}"/>' if color else ""
    run = (f'<w:r><w:rPr>{color_tag}<w:rFonts w:hint="eastAsia"/>'
           f'<w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
           f'<w:t>{data_text}</w:t></w:r>')
    return f'<w:tc>{tcpr}{p_start}{ppr}{run}</w:p></w:tc>'


# ---------------------------------------------------------------------------
# 数据预处理：兼容单数/复数 JSON 格式
# ---------------------------------------------------------------------------
def normalize_data(data):
    """将旧的单数字段转换为数组格式，确保向后兼容并支持大陆身份证。"""
    # share_capital: dict -> list
    sc = data.get("share_capital")
    if isinstance(sc, dict):
        data["share_capital"] = [sc]
    elif not sc:
        data["share_capital"] = []

    # founder -> founders
    if "founder" in data and "founders" not in data:
        data["founders"] = [data.pop("founder")]
    if "founders" not in data:
        data["founders"] = []

    for f in data.get("founders", []):
        if "shares" not in f and "shares_class" in f:
            f["shares"] = [{
                "class": f.get("shares_class"),
                "number": f.get("shares_number"),
                "currency": f.get("currency", "港元"),
                "amount": f.get("shares_amount")
            }]

    # director -> directors
    if "director" in data and "directors" not in data:
        data["directors"] = [data.pop("director")]
    if "directors" not in data:
        data["directors"] = []

    # pi_nnc1: 如果没有显式提供，从 directors 中自动生成
    if "pi_nnc1" not in data:
        data["pi_nnc1"] = []
        for d in data["directors"]:
            if d.get("type") == "natural_person":
                id_type = d.get("id_type", "hkid")
                if d.get("passport_full") or d.get("passport_partial"):
                    id_type = "passport"
                elif d.get("id_type") == "identity_card" or d.get("id_name") == "中國身份證號碼":
                    id_type = "identity_card"
                
                data["pi_nnc1"].append({
                    "capacity": "director",
                    "name_cn": d.get("name_cn", ""),
                    "surname_en": d.get("surname_en", ""),
                    "other_names_en": d.get("other_names_en", ""),
                    "id_type": id_type,
                    "hkid_full": d.get("hkid_full", ""),
                    "id_full": d.get("id_full", d.get("hkid_full", "")),
                    "passport_country": d.get("passport_country", ""),
                    "passport_full": d.get("passport_full", ""),
                    "usual_residential_address": d.get("usual_residential_address", d.get("address")),
                })

    # 补足 pi_nnc1 到至少 3 项，以便固定输出 3 页 PI-NNC1
    while len(data["pi_nnc1"]) < 3:
        data["pi_nnc1"].append({
            "capacity": "secretary",  # 默认勾选公司秘书
            "name_cn": "",
            "surname_en": "",
            "other_names_en": "",
            "id_type": "",
            "hkid_full": "",
            "id_full": "",
            "passport_country": "",
            "passport_full": "",
            "usual_residential_address": "",
        })
    return data



# ---------------------------------------------------------------------------
# 核心处理逻辑
# ---------------------------------------------------------------------------
def process_document_global(xml_str, data):
    data = normalize_data(data)

    company = data.get('company', {})
    reg_office = data.get('registered_office', {})
    presenter = data.get('presenter', {})
    contact = data.get('contact', {})
    share_caps = data.get('share_capital', [])
    share_rights = data.get('share_rights', [])
    founders = data.get('founders', [])
    secretary = data.get('secretary', {})
    directors = data.get('directors', [])
    pi_pages = data.get('pi_nnc1', [])
    statement = data.get('statement', {})

    tc_pat = re.compile(r'<w:tc\b.*?</w:tc>', re.DOTALL)
    matches = list(tc_pat.finditer(xml_str))
    cells = [m.group(0) for m in matches]

    def clean(cell_xml):
        return strip_tags(cell_xml).replace("\xa0", "").replace("\n", "").replace("\r", "")

    def fci(label, start=0, end=None):
        """find_cell_index"""
        cl = label.replace(" ", "")
        if end is None: end = len(cells)
        for i in range(start, end):
            c_clean = clean(cells[i]).replace(" ", "")
            # 避开可能冲突的表头信息以防误匹配
            if "ClassofShares" in c_clean or "e.g.Ordinary" in c_clean:
                if "普通股" in cl or "Ordinary" in cl:
                    continue
            if cl in c_clean:
                return i
        return -1

    def inject(label, text, start=0, end=None, color=None):
        if not text: return start
        idx = fci(label, start, end)
        if idx != -1 and idx + 1 < len(cells):
            cells[idx + 1] = inject_data_into_cell(cells[idx + 1], str(text), color=color)
            return idx + 1
        return start

    def inject_addr(addr, start, end,
                    flat="室／樓／座等", bldg="大廈Building",
                    street="街道／屋苑／地段／村等",
                    district="區District", region="地區Region", color=None):
        if not addr: return
        if isinstance(addr, str):
            inject(flat, addr, start, end, color=color)
            return
        inject(flat, addr.get("flat_floor_block"), start, end, color=color)
        inject(bldg, addr.get("building"), start, end, color=color)
        inject(street, addr.get("street"), start, end, color=color)
        inject(district, addr.get("district"), start, end, color=color)
        inject(region, addr.get("region"), start, end, color=color)

    # === 地址标签常量 ===
    ADDR_INTL = dict(flat="室／樓／座等", bldg="大廈Building",
                     street="街道／屋苑／地段／村等",
                     district="區／市／省／州／郵遞區號等",
                     region="國家／地區Country／Region")
    ADDR_HK = dict(flat="室／樓／座等", bldg="大廈Building",
                   street="街道／屋苑／地段／村等",
                   district="區District", region="地區Region")

    # ===================================================================
    # 0. 划分各组件的边界
    # ===================================================================
    s_pres = fci("提交人資料")
    s_pres_end = s_pres + 45 if s_pres != -1 else 100
    
    s_reg = fci("3公司在香港的註冊辦事處")
    s_reg_end = fci("5公司組成時的股本", s_reg if s_reg != -1 else 0)
    if s_reg_end == -1:
        s_reg_end = len(cells)

    s_share = fci("5公司組成時的股本")
    s_share_end = fci("6創辦成員FounderMembers", s_share if s_share != -1 else 0)
    if s_share_end == -1:
         s_share_end = len(cells)

    s_founder = fci("6創辦成員FounderMembers")
    s_founder_end = fci("7首任公司秘書FirstCompanySecretary", s_founder if s_founder != -1 else 0)
    if s_founder_end == -1:
        s_founder_end = len(cells)

    s_sec = fci("7首任公司秘書FirstCompanySecretary")
    s_sec_end = fci("8首任董事FirstDirectors", s_sec if s_sec != -1 else 0)
    if s_sec_end == -1:
        s_sec_end = len(cells)

    s_dir = fci("8首任董事FirstDirectors")
    s_dir_end = fci("9創辦成員陳述書", s_dir if s_dir != -1 else 0)
    if s_dir_end == -1:
        s_dir_end = len(cells)

    s_stmt = fci("9創辦成員陳述書")
    s_stmt_end = fci("受保護資料", s_stmt if s_stmt != -1 else 0)
    if s_stmt_end == -1:
        s_stmt_end = len(cells)

    # ===================================================================
    # 1. 全局公司信息（限制在 s_pres 之前）
    # ===================================================================
    inject("建議採用的公司英文名稱", company.get("name_en"), 0, s_pres, color="FF0000")
    inject("建議採用的公司中文名稱", company.get("name_cn"), 0, s_pres, color="FF0000")
    
    # 2公司類別打勾
    if company.get("type") == "private":
        type_idx = fci("私人Private", 0, s_pres)
        if type_idx != -1:
            cells[type_idx + 1] = inject_data_into_cell(cells[type_idx + 1], "✔", color="FF0000")
    
    # 擬經營业务性質精确偏移量注入，避免使用標籤匹配導致的錯位
    s_biz = fci("擬經營業務性質", 0, s_pres)
    if s_biz != -1:
        if company.get("business_code"):
            cells[s_biz + 4] = inject_data_into_cell(cells[s_biz + 4], company.get("business_code"), color="FF0000")
        if company.get("business_nature"):
            cells[s_biz + 6] = inject_data_into_cell(cells[s_biz + 6], company.get("business_nature"), color="FF0000")

    # ===================================================================
    # 2. 提交人资料 (presenter)
    # ===================================================================
    if s_pres != -1 and presenter:
        inject("中文姓名／名稱NameinChinese", presenter.get("name_cn"), s_pres, s_pres_end)
        inject("英文姓名／名稱NameinEnglish", presenter.get("name_en"), s_pres, s_pres_end)
        inject("地址Address", presenter.get("address"), s_pres, s_pres_end)
        inject("電話Tel", presenter.get("phone"), s_pres, s_pres_end)
        inject("電郵Email", presenter.get("email"), s_pres, s_pres_end)

    # ===================================================================
    # 3. 注册地址 & 公司联络资料 (限制在 s_reg 到 s_reg_end)
    # ===================================================================
    if s_reg != -1:
        inject("室／樓／座等", reg_office.get("flat_floor_block"), s_reg, s_reg_end, color="FF0000")
        inject("大廈Building", reg_office.get("building"), s_reg, s_reg_end, color="FF0000")
        inject("街道／屋苑／地段／村等", reg_office.get("street"), s_reg, s_reg_end, color="FF0000")
        inject("區District", reg_office.get("district"), s_reg, s_reg_end, color="FF0000")
        inject("地區Region", reg_office.get("region"), s_reg, s_reg_end, color="FF0000")
        inject("電郵地址", contact.get("email"), s_reg, s_reg_end)
        
        phone_idx = fci("香港聯絡電話號碼", s_reg, s_reg_end)
        if phone_idx != -1:
            phone_val = contact.get("phone", "")
            if " " in phone_val:
                cc, num = phone_val.split(" ", 1)
                cells[phone_idx + 1] = inject_data_into_cell(cells[phone_idx + 1], cc)
                cells[phone_idx + 2] = inject_data_into_cell(cells[phone_idx + 2], num)
            else:
                cells[phone_idx + 1] = inject_data_into_cell(cells[phone_idx + 1], "+852")
                cells[phone_idx + 2] = inject_data_into_cell(cells[phone_idx + 2], phone_val)

    # ===================================================================
    # 5. 股本详情 (限制在 s_share 到 s_share_end)
    # ===================================================================
    if s_share != -1:
        sh_idx = fci("股份的類別", s_share, s_share_end)
        if sh_idx != -1:
            base = sh_idx + 12  # skip header(6) + sub-header(6)
            for row_i, sc in enumerate(share_caps[:3]):
                row_start = base + row_i * 6
                vals = [sc.get("class"), sc.get("total_shares"), sc.get("currency"),
                        sc.get("total_amount"), sc.get("paid_up"), sc.get("unpaid")]
                for col, v in enumerate(vals):
                    if v is not None and row_start + col < s_share_end:
                        cells[row_start + col] = inject_data_into_cell(cells[row_start + col], str(v))

            # 總值Total 行合计
            tot_idx = fci("總值Total", s_share, s_share_end)
            if tot_idx != -1:
                total_shares_sum = sum(int(sc.get("total_shares", 0)) for sc in share_caps)
                currency = share_caps[0].get("currency", "港元")
                total_amount_sum = sum(int(sc.get("total_amount", 0)) for sc in share_caps)
                paid_up_sum = sum(int(sc.get("paid_up", 0)) for sc in share_caps)
                unpaid_sum = sum(int(sc.get("unpaid", 0)) for sc in share_caps)
                
                cells[tot_idx + 1] = inject_data_into_cell(cells[tot_idx + 1], str(total_shares_sum))
                cells[tot_idx + 2] = inject_data_into_cell(cells[tot_idx + 2], currency)
                cells[tot_idx + 3] = inject_data_into_cell(cells[tot_idx + 3], str(total_amount_sum))
                cells[tot_idx + 4] = inject_data_into_cell(cells[tot_idx + 4], str(paid_up_sum))
                cells[tot_idx + 5] = inject_data_into_cell(cells[tot_idx + 5], str(unpaid_sum))

        # 5A. 股份权利详情
        if share_rights:
            s5a_idx = fci("5A股份所附帶的權利的詳情", s_share, s_share_end)
            if s5a_idx != -1:
                s5a_class_hdr = fci("股份的類別", s5a_idx, s_share_end)
                if s5a_class_hdr != -1:
                    for row_i, sr in enumerate(share_rights[:2]):
                        class_cell = s5a_class_hdr + 2 + row_i * 2
                        desc_cell = class_cell + 1
                        if class_cell < s_share_end:
                            cells[class_cell] = inject_data_into_cell(cells[class_cell], sr.get("class", ""))
                        if desc_cell < s_share_end:
                            cells[desc_cell] = inject_data_into_cell(cells[desc_cell], sr.get("description", ""))

    # ===================================================================
    # 6. 创办成员 (限制在 s_founder 到 s_founder_end)
    # ===================================================================
    if s_founder != -1 and founders:
        f1 = founders[0]
        f_color = "FF0000" if f1.get("type") == "natural_person" else None
        
        if f1.get("type") == "natural_person":
            inject("中文姓名／名稱NameinChinese", f1.get("name_cn"), s_founder, s_founder_end, color=f_color)
            inject("姓氏Surname", f1.get("surname_en"), s_founder, s_founder_end, color=f_color)
            inject("名字OtherNames", f1.get("other_names_en"), s_founder, s_founder_end, color=f_color)
        else:
            inject("中文姓名／名稱NameinChinese", f1.get("name_cn"), s_founder, s_founder_end)
            inject("英文名稱NameinEnglish", f1.get("name_en"), s_founder, s_founder_end)
        inject_addr(f1.get("address"), s_founder, s_founder_end, color=f_color, **ADDR_INTL)
        
        # 认购股本
        if f1.get("shares"):
            sh1 = f1["shares"][0]
            sub_cap_idx = fci("認購的股本", s_founder, s_founder_end)
            if sub_cap_idx != -1:
                cells[sub_cap_idx + 9] = inject_data_into_cell(cells[sub_cap_idx + 9], sh1.get("class", ""), color=f_color)
                cells[sub_cap_idx + 10] = inject_data_into_cell(cells[sub_cap_idx + 10], str(sh1.get("number", "")), color=f_color)
                cells[sub_cap_idx + 11] = inject_data_into_cell(cells[sub_cap_idx + 11], sh1.get("currency", ""), color=f_color)
                cells[sub_cap_idx + 12] = inject_data_into_cell(cells[sub_cap_idx + 12], str(sh1.get("amount", "")), color=f_color)

        # 創辦成員總值合计
        f_tot_idx = fci("總值Total", s_founder, s_founder_end)
        if f_tot_idx != -1 and f1.get("shares"):
            total_num = sum(int(sh.get("number", 0)) for sh in f1.get("shares"))
            total_amt = sum(int(sh.get("amount", 0)) for sh in f1.get("shares"))
            currency = f1["shares"][0].get("currency", "港元")
            cells[f_tot_idx + 1] = inject_data_into_cell(cells[f_tot_idx + 1], str(total_num), color=f_color)
            cells[f_tot_idx + 7] = inject_data_into_cell(cells[f_tot_idx + 7], currency, color=f_color)
            cells[f_tot_idx + 8] = inject_data_into_cell(cells[f_tot_idx + 8], str(total_amt), color=f_color)

    # 续页A: 第2个创办成员
    csA = fci("續頁AContinuationSheetA")
    csB = fci("續頁BContinuationSheetB")
    if csB == -1:
        csB = fci("續頁B", csA if csA != -1 else 0)

    if csA != -1 and len(founders) > 1:
        f2 = founders[1]
        csA_end = csB if csB != -1 else (csA + 200)
        if f2.get("type") == "natural_person":
            inject("中文姓名／名稱NameinChinese", f2.get("name_cn"), csA, csA_end)
            inject("姓氏Surname", f2.get("surname_en"), csA, csA_end)
            inject("名字OtherNames", f2.get("other_names_en"), csA, csA_end)
        else:
            inject("英文名稱NameinEnglish", f2.get("name_en"), csA, csA_end)
        inject_addr(f2.get("address"), csA, csA_end, **ADDR_INTL)
        if f2.get("shares"):
            sh_hdr_a = fci("股份的類別", csA, csA_end)
            if sh_hdr_a != -1:
                for row_i, sh in enumerate(f2["shares"][:2]):
                    row_base = sh_hdr_a + 4 + row_i * 4
                    vals = [sh.get("class"), sh.get("number"), sh.get("currency"), sh.get("amount")]
                    for col, v in enumerate(vals):
                        if v and row_base + col < csA_end:
                            cells[row_base + col] = inject_data_into_cell(cells[row_base + col], str(v))

    # ===================================================================
    # 7. 首任公司秘书 (限制在 s_sec 到 s_sec_end)
    # ===================================================================
    if s_sec != -1 and secretary:
        sec_type = secretary.get("type", "natural_person")
        if sec_type == "natural_person":
            # 7A 自然人秘书
            inject("中文姓名NameinChinese", secretary.get("name_cn"), s_sec, s_sec_end)
            inject("姓氏Surname", secretary.get("surname_en"), s_sec, s_sec_end)
            inject("名字OtherNames", secretary.get("other_names_en"), s_sec, s_sec_end)
            inject_addr(secretary.get("address"), s_sec, s_sec_end, **ADDR_HK)
            inject("電郵地址", secretary.get("email"), s_sec, s_sec_end)
            inject("香港身分證部分號碼", secretary.get("hkid_partial"), s_sec, s_sec_end)
        else:
            # 7B 法人团体秘书
            s7b = fci("公司秘書(法人團體)", s_sec, s_sec_end)
            if s7b != -1:
                inject("中文名稱NameinChinese", secretary.get("name_cn"), s7b, s_sec_end)
                inject("英文名稱NameinEnglish", secretary.get("name_en"), s7b, s_sec_end)
                inject_addr(secretary.get("address"), s7b, s_sec_end, **ADDR_HK)
                inject("電郵地址EmailAddress", secretary.get("email"), s7b, s_sec_end)
                inject("商業登記號碼BusinessRegistrationNumber", secretary.get("business_registration_number"), s7b, s_sec_end)
                if secretary.get("tcsp_licence"):
                    inject("牌照編號LicenceNo", secretary["tcsp_licence"], s7b, s_sec_end)

    # ===================================================================
    # 8. 首任董事 (限制在 s_dir 到 s_dir_end)
    # ===================================================================
    if s_dir != -1:
        np_dirs = [d for d in directors if d.get("type") == "natural_person"]
        bc_dirs = [d for d in directors if d.get("type") == "body_corporate"]

        # 8A: 第1个自然人董事
        if np_dirs:
            d1 = np_dirs[0]
            s8b = fci("董事(法人團體)Director(BodyCorporate)", s_dir, s_dir_end)
            s8a_end = s8b if s8b != -1 else s_dir_end
            
            d_color = "FF0000"
            inject("中文姓名NameinChinese", d1.get("name_cn"), s_dir, s8a_end, color=d_color)
            inject("姓氏Surname", d1.get("surname_en"), s_dir, s8a_end, color=d_color)
            inject("名字OtherNames", d1.get("other_names_en"), s_dir, s8a_end, color=d_color)
            inject_addr(d1.get("address"), s_dir, s8a_end, color=d_color, **ADDR_INTL)
            inject("電郵地址EmailAddress", d1.get("email"), s_dir, s8a_end, color=d_color)
            
            # 身份证件注入
            if d1.get("hkid_partial"):
                inject("香港身分證部分號碼", d1["hkid_partial"], s_dir, s8a_end, color=d_color)
            elif d1.get("id_type") == "identity_card" or d1.get("id_name") == "中國身份證號碼":
                # 大陆中国身份证
                id_idx = fci("身分識別", s_dir, s8a_end)
                if id_idx != -1:
                    id_text = f"身分識別Identification                            中國身份證號碼：{d1.get('id_full')}"
                    cells[id_idx] = inject_data_into_cell(cells[id_idx], id_text, color=d_color)
            elif d1.get("passport_country") or d1.get("passport_partial"):
                inject("簽發國家／地區IssuingCountry", d1.get("passport_country", "中國"), s_dir, s8a_end, color=d_color)
                inject("部分號碼PartialNumber", d1.get("passport_partial"), s_dir, s8a_end, color=d_color)

            # 同意书打勾与签署 (Issue 4)
            consent_idx = fci("出任董事職位同意書", s_dir, s8a_end)
            if consent_idx != -1:
                cells[consent_idx + 2] = inject_data_into_cell(cells[consent_idx + 2], "✔", color=d_color)
                
            sig_dir_idx = fci("簽署Signed", s_dir, s8a_end)
            if sig_dir_idx != -1:
                cells[sig_dir_idx + 2] = inject_data_into_cell(cells[sig_dir_idx + 2], d1.get("name_cn", ""), color=d_color)

        # 8B: 第1个法人团体董事
        if bc_dirs:
            db1 = bc_dirs[0]
            s8b = fci("董事(法人團體)Director(BodyCorporate)", s_dir, s_dir_end)
            if s8b != -1:
                inject("中文名稱NameinChinese", db1.get("name_cn"), s8b, s_dir_end)
                inject("英文名稱NameinEnglish", db1.get("name_en"), s8b, s_dir_end)
                inject_addr(db1.get("address"), s8b, s_dir_end, **ADDR_INTL)

    # 续页D: 第2个自然人董事
    csD = fci("續頁DContinuationSheetD")
    csE = fci("續頁EContinuationSheetE")
    if csD != -1 and len(np_dirs) > 1:
        d2 = np_dirs[1]
        csD_end = csE if csE != -1 else (csD + 200)
        inject("中文姓名NameinChinese", d2.get("name_cn"), csD, csD_end)
        inject("姓氏Surname", d2.get("surname_en"), csD, csD_end)
        inject("名字OtherNames", d2.get("other_names_en"), csD, csD_end)
        inject_addr(d2.get("address"), csD, csD_end, **ADDR_INTL)
        inject("電郵地址EmailAddress", d2.get("email"), csD, csD_end)
        
        if d2.get("hkid_partial"):
            inject("香港身分證部分號碼", d2["hkid_partial"], csD, csD_end)
        elif d2.get("id_type") == "identity_card" or d2.get("id_name") == "中國身份證號碼":
            id_idx = fci("身分識別", csD, csD_end)
            if id_idx != -1:
                id_text = f"身分識別Identification                            中國身份證號碼：{d2.get('id_full')}"
                cells[id_idx] = inject_data_into_cell(cells[id_idx], id_text)
        elif d2.get("passport_country") or d2.get("passport_partial"):
            inject("簽發國家／地區IssuingCountry", d2.get("passport_country", "中國"), csD, csD_end)
            inject("部分號碼PartialNumber", d2.get("passport_partial"), csD, csD_end)

    # 续页E: 额外法人团体董事 (第2个起)
    if csE != -1 and len(bc_dirs) > 1:
        db2 = bc_dirs[1]
        pi_start_marker = fci("受保護資料")
        csE_end = pi_start_marker if pi_start_marker != -1 else (csE + 200)
        inject("英文名稱NameinEnglish", db2.get("name_en"), csE, csE_end)
        inject_addr(db2.get("address"), csE, csE_end, **ADDR_INTL)

    # ===================================================================
    # 9. 陈述书、签署、签署日期与底部的出生日期 (限制在 s_stmt 到 s_stmt_end)
    # ===================================================================
    if s_stmt != -1 and statement:
        sig_idx = fci("簽署Signed", s_stmt, s_stmt_end)
        if sig_idx != -1 and sig_idx + 1 < len(cells):
            cells[sig_idx + 1] = inject_data_into_cell(cells[sig_idx + 1], statement.get("signed_name", ""), color="FF0000")
            
        date_idx = fci("日期Date", s_stmt, s_stmt_end)
        if date_idx != -1 and date_idx + 1 < len(cells):
            cells[date_idx + 1] = inject_data_into_cell(cells[date_idx + 1], statement.get("date", ""), color="FF0000")

        name_idx = fci("姓名Name", s_stmt, s_stmt_end)
        if name_idx != -1 and name_idx + 1 < len(cells):
            cells[name_idx + 1] = inject_data_into_cell(cells[name_idx + 1], statement.get("signed_name", ""), color="FF0000")
            
        # 寻找陈述书签署日期单元格（签署日期格式为 DD/MM/YYYY，横线下为日/月/年）
        birth_idx = -1
        for i in range(s_stmt, s_stmt_end):
            c_txt = clean(cells[i])
            if "日" in c_txt and "月" in c_txt and "年" in c_txt and "/" in c_txt:
                birth_idx = i
                break
                
        if birth_idx != -1:
            stmt_date = statement.get("date", "")
            if stmt_date:
                parts = stmt_date.split("/")
                if len(parts) == 3:
                    b_formatted = f"日 {parts[0]}  /  月 {parts[1]}  /  年 {parts[2]}"
                    cells[birth_idx] = inject_data_into_cell(cells[birth_idx], b_formatted, color="FF0000")

        # 填报续页数 (Issue 5)
        sheet_counts_idx = fci("本表格包括下列續頁", s_stmt, s_stmt_end)
        if sheet_counts_idx != -1:
            csA = fci("續頁AContinuationSheetA")
            csD = fci("續頁DContinuationSheetD")
            cnt_a = "1" if csA != -1 else ""
            cnt_d = "1" if csD != -1 else ""
            cnt_pi = str(len(pi_pages)) if len(pi_pages) > 0 else "1"
            if cnt_a:
                cells[sheet_counts_idx + 8] = inject_data_into_cell(cells[sheet_counts_idx + 8], cnt_a, color="FF0000")
            if cnt_d:
                cells[sheet_counts_idx + 11] = inject_data_into_cell(cells[sheet_counts_idx + 11], cnt_d, color="FF0000")
            if cnt_pi:
                cells[sheet_counts_idx + 17] = inject_data_into_cell(cells[sheet_counts_idx + 17], cnt_pi, color="FF0000")

    # ===================================================================
    # PI-NNC1 受保护资料页
    # ===================================================================
    # 定位第一页 PI-NNC1 页面的真正起始点（即倒数第 18 个表格的第一个 cell，对应新模板中 3 个原生 PI 页的第一页）
    pi_start = -1
    tbl_pat = re.compile(r'<w:tbl\b.*?</w:tbl>', re.DOTALL)
    tbl_matches_after = list(tbl_pat.finditer(xml_str))
    if len(tbl_matches_after) >= 18:
        pi_first_tbl_start = tbl_matches_after[-18].start()
        for ci, m in enumerate(matches):
            if m.start() >= pi_first_tbl_start:
                pi_start = ci
                break
    
    # 填充建议采用的公司名称 header (Issue 7) - 放在所有 PI-NNC1 的头部
    full_comp_name = (company.get("name_en", "") + company.get("name_cn", "")).strip()
    if full_comp_name:
        for i in range(len(cells)):
            if clean(cells[i]).replace(" ", "") == "PI-NNC1":
                if i + 3 < len(cells):
                    cells[i + 3] = inject_data_into_cell(cells[i + 3], full_comp_name, color="FF0000")

    if pi_start != -1 and pi_pages:
        pi_end = len(cells)
        p1 = pi_pages[0]

        # 注入身份打勾 (director/company_secretary)
        capacity = p1.get("capacity", "")
        if capacity == "director":
            dir_idx = fci("董事Director", pi_start, pi_end)
            if dir_idx != -1 and dir_idx - 1 >= 0:
                cells[dir_idx - 1] = inject_data_into_cell(cells[dir_idx - 1], "✔", color="FF0000")
        elif capacity == "company_secretary" or capacity == "secretary":
            sec_idx = fci("公司秘書CompanySecretary", pi_start, pi_end)
            if sec_idx != -1 and sec_idx - 1 >= 0:
                cells[sec_idx - 1] = inject_data_into_cell(cells[sec_idx - 1], "✔", color="FF0000")

        # 中文姓名特殊偏移
        cn_idx = fci("中文姓名NameinChinese", pi_start, pi_end)
        if cn_idx != -1 and cn_idx + 2 < len(cells):
            cells[cn_idx + 2] = inject_data_into_cell(cells[cn_idx + 2], p1.get("name_cn", ""), color="FF0000")
        inject("姓氏Surname", p1.get("surname_en"), pi_start, pi_end, color="FF0000")
        inject("名字OtherNames", p1.get("other_names_en"), pi_start, pi_end, color="FF0000")

        if p1.get("id_type") == "hkid":
            inject("香港身分證(完整號碼)", p1.get("hkid_full"), pi_start, pi_end, color="FF0000")
        elif p1.get("id_type") == "identity_card":
            id_idx = fci("身分識別", pi_start, pi_end)
            if id_idx != -1:
                id_text = f"身分識別Identification                     中國身份證號碼：{p1.get('id_full')}"
                cells[id_idx] = inject_data_into_cell(cells[id_idx], id_text, color="FF0000")
        else:
            inject("簽發國家／地區IssuingCountry", p1.get("passport_country", "中國"), pi_start, pi_end, color="FF0000")
            inject("完整號碼FullNumber", p1.get("passport_full"), pi_start, pi_end, color="FF0000")

        # 董事通常住址
        ura = fci("董事的通常住址", pi_start, pi_end)
        if ura == -1:
             ura = fci("董事的通", pi_start, pi_end)
        if ura != -1:
            inject_addr(p1.get("usual_residential_address"), ura, pi_end, color="FF0000", **ADDR_INTL)

    # ===================================================================
    # 组装主 XML 并直接返回
    # ===================================================================
    new_xml = ""
    last_end = 0
    for i, match in enumerate(matches):
        new_xml += xml_str[last_end:match.start()]
        new_xml += cells[i]
        last_end = match.end()
    new_xml += xml_str[last_end:]

    return new_xml


def main():
    if len(sys.argv) < 3:
        print("Usage: python fill_nnc1.py <data.json> <unpacked_docx_dir>")
        sys.exit(1)
    data_path = sys.argv[1]
    unpacked_dir = sys.argv[2]
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    doc_xml = os.path.join(unpacked_dir, 'word', 'document.xml')
    if not os.path.exists(doc_xml):
        print(f"Error: {doc_xml} not found.")
        sys.exit(1)
    with open(doc_xml, 'r', encoding='utf-8') as f:
        xml_str = f.read()
    new_xml = process_document_global(xml_str, data)
    with open(doc_xml, 'w', encoding='utf-8') as f:
        f.write(new_xml)
    print("document.xml updated successfully.")


if __name__ == "__main__":
    main()
