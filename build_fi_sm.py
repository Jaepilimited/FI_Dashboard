# -*- coding: utf-8 -*-
"""직접비/간접비 원본 → BigQuery raw 테이블 업로드 → BQ 쿼리로 FI_SM 생성

흐름:
  1) 직접비 N월.xlsx → Sales_Integration.FI_Direct_Cost   (원본 컬럼 그대로 + Year_Month)
  2) 간접비 N월.xlsx → Sales_Integration.FI_Indirect_Cost (원본 컬럼 그대로 + Year_Month)
  3) FI_Matching.xlsx 1/2번탭 → FI_Matching1 / FI_Matching2
  4) fi_sm_query.sql (CREATE OR REPLACE TABLE) 실행 → FI_SM
     → 이후에는 BQ 콘솔에서 fi_sm_query.sql만 다시 실행해도 FI_SM 재생성 가능

실행: python build_fi_sm.py            # 업로드 + 쿼리 실행 + 검증
      python build_fi_sm.py --dry-run  # 로컬 빌드/검증만 (BQ 접근 없음)

새 달 추가: MONTHS에 월 추가 후 재실행 (TOTAL 행과 합계 대조 검증 자동 수행)
"""
import os
import sys
import warnings
import pandas as pd

warnings.filterwarnings('ignore')

MONTHS = [1, 2, 3, 4, 5]
YEAR = 2026
DATASET = 'skin1004-319714.Sales_Integration'

FI_SM_SQL = f"""
CREATE OR REPLACE TABLE `{DATASET}.FI_SM` AS
WITH unified AS (
  -- 직접비: 자기 코스트센터를 Sending_Cost_Center로 → Indirect_Cost_Class='직접' 매핑
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    Cost_Center AS Sending_Cost_Center,
    Cost_Account,
    Amount,
    Year_Month
  FROM `{DATASET}.FI_Direct_Cost`

  UNION ALL

  -- 판매간접: 받는 코스트센터→Department, 배부받은금액→Amount
  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `{DATASET}.FI_Indirect_Cost`

  UNION ALL

  -- 전사공통비: 받는 코스트센터→Department, 배부받은금액→Amount (판매간접과 동일 패턴)
  SELECT
    '전사공통비' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `{DATASET}.FI_Common_Cost`

)
SELECT
  t.Cost_Center_Class,
  t.Department,
  t.Sending_Cost_Center,
  t.Cost_Account,
  t.Amount,
  t.Year_Month,
  IFNULL(m2.Account_Name, t.Cost_Account) AS Account_Name,
  m2.Main_Category,
  m2.Sub_Category,
  m2.Detail_Category,
  m1.Division,
  m1.Team,
  CASE
    WHEN t.Cost_Center_Class = '판매직접' THEN '직접'
    WHEN t.Cost_Center_Class = '판매간접'
      AND t.Sending_Cost_Center = 'Data Business'
      AND t.Cost_Account LIKE '%페이드 마케팅%' THEN '직접'
    ELSE mc.Indirect_Cost_Class
  END AS Indirect_Cost_Class,
  CASE
    WHEN t.Cost_Center_Class = '판매직접' THEN '판매직접'
    WHEN t.Cost_Center_Class = '판매간접'
      AND t.Sending_Cost_Center = 'Data Business'
      AND t.Cost_Account LIKE '%페이드 마케팅%' THEN '판매직접'
    WHEN t.Cost_Center_Class = '판매간접' AND t.Sending_Cost_Center IN (
      'BC', 'BCM', 'BCM_BEA', 'BP', 'BXD', 'CBO', 'CBO Staff', 'CEO', 'CFO',
      'Corporate Planning', 'CP', 'Data Business', 'Distribution LOG_수출관리',
      'FD_파운더스', 'FI', 'GM Department', 'Internal Audit', 'IT', 'LOG',
      'People', 'Sales Operation', 'SCM(판)', 'UMMA_개발', '리테일', '리테일_브랜드전략',
      '법무•컴플라이언스 본부', '운영전략1_운영전략', '유통2본부', '유통구매'
    ) THEN '판매간접'
    WHEN t.Cost_Center_Class = '배부내역' AND t.Department IN (
      '뉴비지니스_뉴비즈1', '뉴비지니스_뉴비즈2', '리테일_리테일1', '리테일_리테일2',
      '리테일_리테일3', '영업1', '영업2', '코스트코', 'BCM_플래그십 파트',
      'GM CBT', 'GM EAST 1', 'GM EAST 2', 'GM JBT', 'GM KBT', 'GM WEST Ecomm', 'GM WEST MKT',
      'DD_Distribution 2_Part 1', 'DD_Distribution 2_Part 2', 'DD_Distribution 2_Part 3'
    ) THEN '배부내역'
  END AS Cost_Class
FROM unified t
LEFT JOIN `{DATASET}.FI_Matching2` m2 ON t.Cost_Account = m2.Cost_Account
LEFT JOIN `{DATASET}.FI_Matching1` m1 ON t.Department = m1.Cost_Center
LEFT JOIN `{DATASET}.FI_Matching1` mc ON t.Sending_Cost_Center = mc.Cost_Center
"""

FI_FINAL_SM_SQL = f"""
CREATE OR REPLACE TABLE `{DATASET}.FI_Final_SM` AS

-- ① FI_Final 손익을 Department×월로 집계 → 롱 포맷 전개
WITH pnl AS (
  SELECT Department, Year_Month,
         SUM(Sales_Amount)     AS Sales_Amount,
         SUM(Cost_of_Sales)    AS Cost_of_Sales,
         SUM(Gross_Profit)     AS Gross_Profit,
         SUM(Operating_Income) AS Operating_Income
  FROM `{DATASET}.FI_Final`
  GROUP BY Department, Year_Month
),
-- FI_SM 간접비분류별 판관비 합계 (직접이익·공헌이익 파생에 사용)
sga_class AS (
  SELECT Department, Year_Month,
    SUM(CASE WHEN Indirect_Cost_Class = '직접'    THEN Amount ELSE 0 END) AS sga_direct,
    SUM(CASE WHEN Indirect_Cost_Class = '조직간접' THEN Amount ELSE 0 END) AS sga_org_indirect
  FROM `{DATASET}.FI_SM`
  GROUP BY Department, Year_Month
),
pnl_long AS (
  SELECT p.Department, p.Year_Month, item.name AS Item, item.amt AS Amount
  FROM pnl p
  LEFT JOIN sga_class sc ON p.Department = sc.Department AND p.Year_Month = sc.Year_Month,
  UNNEST([
    STRUCT('매출액'    AS name, p.Sales_Amount     AS amt),
    STRUCT('매출원가',          p.Cost_of_Sales),
    STRUCT('매출총이익',        p.Gross_Profit),
    STRUCT('직접이익',          p.Gross_Profit - COALESCE(sc.sga_direct, 0)),
    STRUCT('공헌이익',          p.Gross_Profit - COALESCE(sc.sga_direct, 0) - COALESCE(sc.sga_org_indirect, 0)),
    STRUCT('영업이익',          p.Operating_Income)
  ]) AS item
)

-- ② 판관비: FI_SM 계정 디테일 그대로
SELECT
  '판관비' AS Item_Class,
  s.Cost_Center_Class,
  s.Department,
  s.Sending_Cost_Center,
  s.Cost_Account,
  s.Amount,
  s.Year_Month,
  s.Account_Name,
  s.Main_Category,
  s.Sub_Category,
  s.Detail_Category,
  s.Division,
  s.Team,
  s.Indirect_Cost_Class,
  s.Cost_Class
FROM `{DATASET}.FI_SM` s

UNION ALL

-- ③ 손익 항목: 매출액/매출원가/매출총이익/영업이익 (판관비는 FI_SM 행이 담당 — 중복 없음)
SELECT
  pl.Item AS Item_Class,
  CAST(NULL AS STRING) AS Cost_Center_Class,
  pl.Department,
  CAST(NULL AS STRING) AS Sending_Cost_Center,
  pl.Item AS Cost_Account,
  pl.Amount,
  pl.Year_Month,
  pl.Item AS Account_Name,
  pl.Item AS Main_Category,
  pl.Item AS Sub_Category,
  pl.Item AS Detail_Category,
  m1.Division,
  m1.Team,
  CAST(NULL AS STRING) AS Indirect_Cost_Class,
  CAST(NULL AS STRING) AS Cost_Class
FROM pnl_long pl
LEFT JOIN `{DATASET}.FI_Matching1` m1 ON pl.Department = m1.Cost_Center
"""

FI_SGA_EXTENDED_SQL = f"""
-- FI_SGA_Extended: FI_Final 차원 × FI_SM 원가계정 확장 테이블
--
-- 배분 방식
--   allocated_amount = FI_SM.Amount × (이 행의 SG_and_A_Expenses / 부서 전체 SGA 합계)
--
-- 비율 컬럼 읽는 법
--   row_allocation_ratio : 이 개별 행(고객×제품×국가)에 실제 적용된 배분 비율
--   country_ratio        : 이 국가가 해당 부서·월 SGA에서 차지하는 비율
--   continent1_ratio     : 이 권역(Continent1) 비율
--   continent2_ratio     : 이 대륙(Continent2) 비율
--   brand_ratio          : 이 브랜드(SK/UM/Others) 비율
--   line_ratio           : 이 라인 비율
--   category_ratio       : 이 카테고리 비율
--   sales_type_ratio     : 이 판매유형(B2B/B2C) 비율

CREATE OR REPLACE TABLE `{DATASET}.FI_SGA_Extended` AS

WITH

dept_sga AS (
  SELECT Department, Year_Month, SUM(SG_and_A_Expenses) AS dept_sga_total
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month
),
country_sga AS (
  SELECT Department, Year_Month, Country, SUM(SG_and_A_Expenses) AS country_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Country
),
continent1_sga AS (
  SELECT Department, Year_Month, Continent1, SUM(SG_and_A_Expenses) AS continent1_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Continent1
),
continent2_sga AS (
  SELECT Department, Year_Month, Continent2, SUM(SG_and_A_Expenses) AS continent2_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Continent2
),
brand_sga AS (
  SELECT Department, Year_Month, Brand, SUM(SG_and_A_Expenses) AS brand_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Brand
),
line_sga AS (
  SELECT Department, Year_Month, Line, SUM(SG_and_A_Expenses) AS line_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Line
),
category_sga AS (
  SELECT Department, Year_Month, Category, SUM(SG_and_A_Expenses) AS category_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Category
),
sales_type_sga AS (
  SELECT Department, Year_Month, Sales_Type, SUM(SG_and_A_Expenses) AS sales_type_sga
  FROM `{DATASET}.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Sales_Type
)

SELECT
  f.Year_Month,
  f.Department,

  f.Country,
  f.Continent1,
  f.Continent2,
  f.`Group`         AS Sales_Group,
  f.Brand,
  f.Line,
  f.Category,
  f.Sales_Type,
  f.Customer,
  f.Product_Name,
  f.Product_Code,
  f.Specification,

  s.Indirect_Cost_Class,
  s.Cost_Class,
  s.Cost_Center_Class,
  s.Cost_Account,
  s.Account_Name,
  s.Main_Category   AS SM_Main_Category,
  s.Sub_Category    AS SM_Sub_Category,
  s.Detail_Category AS SM_Detail_Category,
  s.Division,
  s.Team,
  s.Sending_Cost_Center,

  s.Amount                 AS sm_account_dept_total,
  f.SG_and_A_Expenses      AS fi_row_sga,
  d.dept_sga_total,

  ROUND(SAFE_DIVIDE(f.SG_and_A_Expenses, d.dept_sga_total), 8)
    AS row_allocation_ratio,
  ROUND(s.Amount * SAFE_DIVIDE(f.SG_and_A_Expenses, d.dept_sga_total), 0)
    AS allocated_amount,

  ROUND(SAFE_DIVIDE(cs.country_sga,    d.dept_sga_total), 6) AS country_ratio,
  ROUND(SAFE_DIVIDE(c1.continent1_sga, d.dept_sga_total), 6) AS continent1_ratio,
  ROUND(SAFE_DIVIDE(c2.continent2_sga, d.dept_sga_total), 6) AS continent2_ratio,
  ROUND(SAFE_DIVIDE(br.brand_sga,      d.dept_sga_total), 6) AS brand_ratio,
  ROUND(SAFE_DIVIDE(ls.line_sga,       d.dept_sga_total), 6) AS line_ratio,
  ROUND(SAFE_DIVIDE(ca.category_sga,   d.dept_sga_total), 6) AS category_ratio,
  ROUND(SAFE_DIVIDE(st.sales_type_sga, d.dept_sga_total), 6) AS sales_type_ratio

FROM `{DATASET}.FI_Final`       f
JOIN  dept_sga d
  ON  f.Department = d.Department AND f.Year_Month = d.Year_Month
JOIN  `{DATASET}.FI_SM`         s
  ON  f.Department = s.Department AND f.Year_Month = s.Year_Month
LEFT JOIN country_sga    cs ON f.Department = cs.Department AND f.Year_Month = cs.Year_Month AND f.Country    = cs.Country
LEFT JOIN continent1_sga c1 ON f.Department = c1.Department AND f.Year_Month = c1.Year_Month AND f.Continent1 = c1.Continent1
LEFT JOIN continent2_sga c2 ON f.Department = c2.Department AND f.Year_Month = c2.Year_Month AND f.Continent2 = c2.Continent2
LEFT JOIN brand_sga      br ON f.Department = br.Department AND f.Year_Month = br.Year_Month AND f.Brand      = br.Brand
LEFT JOIN line_sga       ls ON f.Department = ls.Department AND f.Year_Month = ls.Year_Month AND f.Line       = ls.Line
LEFT JOIN category_sga   ca ON f.Department = ca.Department AND f.Year_Month = ca.Year_Month AND f.Category   = ca.Category
LEFT JOIN sales_type_sga st ON f.Department = st.Department AND f.Year_Month = st.Year_Month AND f.Sales_Type = st.Sales_Type
WHERE f.Product_Code IS NOT NULL AND f.Product_Code != ''
"""

FI_SGA_AGG_SQL = f"""
-- FI_SGA_Agg: FI_SGA_Extended 집계 뷰
--   거래처·제품 차원을 제외한 최소 분석 단위로 집계
--   → 지역(Country/Continent1/Continent2) × 채널(Brand/Line/Category/Sales_Type) × 원가계정 (Cost_Account) 조합
--
-- 핵심 컬럼
--   allocated_amount     : 이 조합에 배분된 판관비 금액
--   sm_account_dept_total: 해당 계정의 부서·월 전체 금액 (FI_SM 원본)
--   dept_sga_total       : 부서·월 전체 SGA (분모)
--   alloc_pct_of_dept    : 부서 판관비 중 이 조합 비중 (%)
--   alloc_pct_of_acct    : 해당 계정 금액 중 이 조합으로 배분된 비중 (%)
--   *_ratio              : 각 차원별 SGA 비율 (부서 전체 대비)

CREATE OR REPLACE TABLE `{DATASET}.FI_SGA_Agg` AS

SELECT
  -- ── 시간 / 부서 키 ────────────────────────────────────────────────────
  Year_Month,
  Department,

  -- ── FI_Final 지역·채널 차원 (거래처·제품 제외) ───────────────────────
  Country,
  Continent1,
  Continent2,
  Sales_Group,
  Brand,
  Line,
  Category,
  Sales_Type,

  -- ── FI_SM 원가계정 차원 (최대 세분화) ────────────────────────────────
  Cost_Class,
  Indirect_Cost_Class,
  Cost_Center_Class,
  Sending_Cost_Center,
  Division,
  Team,
  Cost_Account,
  Account_Name,
  SM_Main_Category,
  SM_Sub_Category,
  SM_Detail_Category,

  -- ── 집계 금액 ──────────────────────────────────────────────────────────
  SUM(allocated_amount)                                               AS allocated_amount,
  MAX(sm_account_dept_total)                                          AS sm_account_dept_total,
  MAX(dept_sga_total)                                                 AS dept_sga_total,

  -- ── 비중 파생 컬럼 ─────────────────────────────────────────────────────
  ROUND(SAFE_DIVIDE(SUM(allocated_amount), MAX(dept_sga_total))  * 100, 4)
                                                                      AS alloc_pct_of_dept,
  ROUND(SAFE_DIVIDE(SUM(allocated_amount), MAX(sm_account_dept_total)) * 100, 4)
                                                                      AS alloc_pct_of_acct,

  -- ── 차원별 비율 ────────────────────────────────────────────────────────
  MAX(country_ratio)                                                  AS country_ratio,
  MAX(continent1_ratio)                                               AS continent1_ratio,
  MAX(continent2_ratio)                                               AS continent2_ratio,
  MAX(brand_ratio)                                                    AS brand_ratio,
  MAX(line_ratio)                                                     AS line_ratio,
  MAX(category_ratio)                                                 AS category_ratio,
  MAX(sales_type_ratio)                                               AS sales_type_ratio

FROM `{DATASET}.FI_SGA_Extended`
GROUP BY
  Year_Month, Department,
  Country, Continent1, Continent2, Sales_Group, Brand, Line, Category, Sales_Type,
  Cost_Class, Indirect_Cost_Class, Cost_Center_Class, Sending_Cost_Center,
  Division, Team, Cost_Account, Account_Name,
  SM_Main_Category, SM_Sub_Category, SM_Detail_Category
"""

log_lines = []
def log(*a):
    s = ' '.join(str(x) for x in a)
    log_lines.append(s)
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('cp949', 'replace').decode('cp949'))


def load_matching():
    m1 = pd.read_excel('FI_Matching.xlsx', sheet_name='1', header=0)
    m1.columns = ['Cost_Center', 'CC_Class', 'Indirect_Cost_Class', 'Division', 'Team']
    m1 = m1.dropna(subset=['Cost_Center'])
    m1['Cost_Center'] = m1['Cost_Center'].astype(str).str.strip()

    m2 = pd.read_excel('FI_Matching.xlsx', sheet_name='2', header=0)
    m2.columns = ['Cost_Account', 'Account_Name', 'Main_Category', 'Sub_Category', 'Detail_Category']
    m2 = m2.dropna(subset=['Cost_Account'])
    m2['Cost_Account'] = m2['Cost_Account'].astype(str).str.strip()
    m2['Account_Name'] = m2['Account_Name'].fillna(m2['Cost_Account'])
    return m1, m2


def load_direct(n):
    """직접비 N월: [코스트센터분류, 코스트센터, 원가계정과목, 공통여부, 금액] (헤더 2행째)"""
    f = f'직접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=1)
    df.columns = ['Cost_Center_Class', 'Cost_Center', 'Cost_Account', 'Common_YN', 'Amount']
    total = pd.to_numeric(df.loc[df['Cost_Center_Class'] == 'TOTAL', 'Amount'], errors='coerce').sum()
    df = df[(df['Cost_Center_Class'] != 'TOTAL') & df['Cost_Center'].notna()].copy()
    for c in ['Cost_Center_Class', 'Cost_Center', 'Cost_Account']:
        df[c] = df[c].astype(str).str.strip()
    df['Common_YN'] = pd.to_numeric(df['Common_YN'], errors='coerce').fillna(0).astype('int64')
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    diff = df['Amount'].sum() - total
    log(f'[직접비 {n}월] rows={len(df)} sum={df["Amount"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return df


def load_dashboard(n):
    """요소별수익성분석조회 N월 → FI_Dashboard 행
    포맷A (1-4월): row0=헤더, row1+=데이터 (TOTAL 없음)
    포맷B (5월~): row0=제목, row1=헤더, row2=소헤더, row3=TOTAL, row4+=데이터
    """
    yyyymm = f'{YEAR}{n:02d}'
    fname  = f'요소별수익성분석조회_{yyyymm}.xlsx'
    cols   = ['Department', 'Customer', 'Product_Name', 'Product_Code', 'Specification',
              'Sales_Quantity', 'Sales_Amount', 'Cost_of_Sales', 'Gross_Profit',
              'SG_and_A_Expenses', 'Operating_Income']
    raw = pd.read_excel(fname, sheet_name=0, header=None)
    # 포맷 감지: row0의 첫 셀이 '부서'이면 포맷A, 아니면 포맷B
    first_cell = str(raw.iloc[0, 0]).strip()
    if first_cell == '부서':
        # 포맷A: row0=헤더, row1+=데이터
        df          = raw.iloc[1:].copy()
        total_sales = None
    else:
        # 포맷B: row0=제목, row1=헤더, row2=소헤더, row3=TOTAL, row4+=데이터
        total_sales = pd.to_numeric(raw.iloc[3, 6], errors='coerce')
        df          = raw.iloc[4:].copy()
    df.columns = cols
    # Product_Code 없는 소계/합계 행 제거
    df = df[df['Product_Code'].notna() & (df['Product_Code'].astype(str).str.strip() != '')].copy()
    for c in ['Department', 'Customer', 'Product_Name', 'Product_Code', 'Specification']:
        df[c] = df[c].astype(str).str.strip()
    df['Specification'] = df['Specification'].replace('nan', '')
    df['Sales_Quantity'] = pd.to_numeric(df['Sales_Quantity'], errors='coerce').fillna(0).round(0).astype('int64')
    for c in ['Sales_Amount', 'Cost_of_Sales', 'Gross_Profit', 'SG_and_A_Expenses', 'Operating_Income']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).round(0).astype('int64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    total_str = f'TOTAL={total_sales:,.0f}' if total_sales is not None else 'TOTAL=없음'
    log(f'[요소별 {n}월] rows={len(df)} 매출액={df["Sales_Amount"].sum():,.0f} {total_str}')
    if total_sales is not None:
        diff = df['Sales_Amount'].sum() - total_sales
        assert abs(diff) < 10, f'{fname} 매출액 합계 불일치 ({diff:,.0f})'
    return df


def load_indirect(n):
    """간접비 N월: [원가계정과목, 보내는 코스트센터, 보내는금액, 비율, 받는 코스트센터, 배부받은금액, 비율] (헤더 3행째)"""
    f = f'간접비 {n}월.xlsx'
    df = pd.read_excel(f, sheet_name=0, header=2)
    df.columns = ['Cost_Account', 'Sending_Cost_Center', 'Sent_Amount', 'Sent_Ratio',
                  'Receiving_Cost_Center', 'Allocated_Amount', 'Allocated_Ratio']
    total = pd.to_numeric(df.loc[df['Cost_Account'] == 'TOTAL', 'Allocated_Amount'], errors='coerce').sum()
    df = df[(df['Cost_Account'] != 'TOTAL') & df['Receiving_Cost_Center'].notna()].copy()
    for c in ['Cost_Account', 'Sending_Cost_Center', 'Receiving_Cost_Center']:
        df[c] = df[c].astype(str).str.strip()
    df['Sent_Amount'] = pd.to_numeric(df['Sent_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    df['Allocated_Amount'] = pd.to_numeric(df['Allocated_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    for c in ['Sent_Ratio', 'Allocated_Ratio']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype('float64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    diff = df['Allocated_Amount'].sum() - total
    log(f'[간접비 {n}월] rows={len(df)} sum={df["Allocated_Amount"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return df


def load_common_cost(n):
    """전사공통비 N월 (파일 없으면 빈 DataFrame 반환)"""
    _empty_cols = ['Cost_Account', 'Sending_Cost_Center', 'Sent_Amount', 'Sent_Ratio',
                   'Receiving_Cost_Center', 'Allocated_Amount', 'Allocated_Ratio', 'Year_Month']
    f = f'전사공통비 {n}월.xlsx'
    if not os.path.exists(f):
        log(f'[전사공통비 {n}월] 파일 없음, 스킵')
        df = pd.DataFrame(columns=_empty_cols)
        for c in ['Sent_Amount', 'Allocated_Amount']:
            df[c] = df[c].astype('int64')
        for c in ['Sent_Ratio', 'Allocated_Ratio']:
            df[c] = df[c].astype('float64')
        return df
    df = pd.read_excel(f, sheet_name=0, header=2)
    df.columns = ['Cost_Account', 'Sending_Cost_Center', 'Sent_Amount', 'Sent_Ratio',
                  'Receiving_Cost_Center', 'Allocated_Amount', 'Allocated_Ratio']
    total = pd.to_numeric(df.loc[df['Cost_Account'] == 'TOTAL', 'Allocated_Amount'], errors='coerce').sum()
    df = df[(df['Cost_Account'] != 'TOTAL') & df['Receiving_Cost_Center'].notna()].copy()
    for c in ['Cost_Account', 'Sending_Cost_Center', 'Receiving_Cost_Center']:
        df[c] = df[c].astype(str).str.strip()
    df['Sent_Amount'] = pd.to_numeric(df['Sent_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    df['Allocated_Amount'] = pd.to_numeric(df['Allocated_Amount'], errors='coerce').fillna(0).round(0).astype('int64')
    for c in ['Sent_Ratio', 'Allocated_Ratio']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0).astype('float64')
    df['Year_Month'] = f'{YEAR}-{n:02d}'
    diff = df['Allocated_Amount'].sum() - total
    log(f'[전사공통비 {n}월] rows={len(df)} sum={df["Allocated_Amount"].sum():,.0f} TOTAL={total:,.0f} diff={diff:,.0f}')
    assert abs(diff) < 1, f'{f} 합계 불일치'
    return df


def build():
    m1, m2    = load_matching()
    dashboard = pd.concat([load_dashboard(n)   for n in MONTHS], ignore_index=True)
    direct    = pd.concat([load_direct(n)      for n in MONTHS], ignore_index=True)
    indirect  = pd.concat([load_indirect(n)    for n in MONTHS], ignore_index=True)
    common    = pd.concat([load_common_cost(n) for n in MONTHS], ignore_index=True)
    expected  = direct['Amount'].sum() + indirect['Allocated_Amount'].sum() + common['Allocated_Amount'].sum()
    log(f'[로컬 검증] 직접비 {len(direct)}행 + 간접비 {len(indirect)}행 + 전사공통비 {len(common)}행, '
        f'예상 FI_SM 합계 {expected:,}')
    log(f'[요소별 합계] 전체 {len(dashboard)}행, 월별: '
        + ', '.join(f'{m}월={len(dashboard[dashboard["Year_Month"]==f"{YEAR}-{m:02d}"])}행' for m in MONTHS))
    return direct, indirect, common, m1, m2, dashboard


def bq_client():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import config
    creds = service_account.Credentials.from_service_account_file(config.BQ_KEY_PATH)
    return bigquery, bigquery.Client(project=config.BQ_PROJECT, credentials=creds)


def upload_table(bigquery, client, name, df):
    """CSV + 명시적 스키마 로드 (Parquet은 비ASCII 이슈 전력이 있어 CSV 위치 매핑 사용)"""
    import io
    def bq_type(dtype):
        s = str(dtype)
        if s.startswith('int'):
            return 'INTEGER'
        if s.startswith('float'):
            return 'FLOAT'
        return 'STRING'
    table_id = f'{DATASET}.{name}'
    client.delete_table(table_id, not_found_ok=True)
    jc = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(c, bq_type(df[c].dtype)) for c in df.columns],
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        write_disposition='WRITE_TRUNCATE',
    )
    buf = io.BytesIO(df.to_csv(index=False).encode('utf-8'))
    client.load_table_from_file(buf, table_id, job_config=jc).result()
    t = client.get_table(table_id)
    log(f'[업로드] {table_id}: {t.num_rows}행, {len(t.schema)}컬럼')


def run(direct, indirect, common, m1, m2, dashboard):
    bigquery, client = bq_client()
    upload_table(bigquery, client, 'FI_Dashboard',    dashboard)
    upload_table(bigquery, client, 'FI_Direct_Cost',  direct)
    upload_table(bigquery, client, 'FI_Indirect_Cost', indirect)
    upload_table(bigquery, client, 'FI_Common_Cost', common)
    # FI_Matching1은 _load_codebook.py로 별도 관리 — 빌드 시 덮어쓰지 않음
    upload_table(bigquery, client, 'FI_Matching2', m2)

    log('[쿼리] CREATE OR REPLACE TABLE FI_SM 실행…')
    client.query(FI_SM_SQL).result()

    # 검증: 행수/합계 + 매칭 누락
    q = client.query(f'''
        SELECT COUNT(*) n, SUM(Amount) amt,
               COUNTIF(Main_Category IS NULL) no_acct,
               COUNTIF(Indirect_Cost_Class IS NULL) no_cc
        FROM `{DATASET}.FI_SM`''').result()
    r = list(q)[0]
    expected = direct['Amount'].sum() + indirect['Allocated_Amount'].sum() + common['Allocated_Amount'].sum()
    log(f'[FI_SM] {r[0]}행, 합계 {r[1]:,} (예상 {expected:,}, 일치={r[1]==expected}), '
        f'계정 미매칭 {r[2]}건, 코스트센터 미매칭 {r[3]}건')

    log('[쿼리] CREATE OR REPLACE TABLE FI_Final_SM 실행…')
    client.query(FI_FINAL_SM_SQL).result()

    # 정합 검증: 원시데이터 탭(FI_Final RAW)과 합계 대조
    q = client.query(f'''
        WITH f AS (SELECT SUM(Sales_Amount) sales, SUM(Cost_of_Sales) cogs,
                          SUM(Gross_Profit) gp, SUM(SG_and_A_Expenses) sga,
                          SUM(Operating_Income) oi
                   FROM `{DATASET}.FI_Final`),
             c AS (SELECT SUM(IF(Item_Class='매출액',   Amount, 0)) sales,
                          SUM(IF(Item_Class='매출원가',  Amount, 0)) cogs,
                          SUM(IF(Item_Class='매출총이익', Amount, 0)) gp,
                          SUM(IF(Item_Class='판관비',    Amount, 0)) sga,
                          SUM(IF(Item_Class='영업이익',  Amount, 0)) oi
                   FROM `{DATASET}.FI_Final_SM`)
        SELECT f.sales, c.sales, f.cogs, c.cogs, f.gp, c.gp, f.sga, c.sga, f.oi, c.oi FROM f, c''').result()
    r = list(q)[0]
    for i, name in enumerate(['매출액', '매출원가', '매출총이익', '판관비', '영업이익']):
        a, b = r[i*2], r[i*2+1]
        log(f'[정합] {name}: FI_Final={a:,} / FI_Final_SM={b:,} 일치={a==b}')

    log('[쿼리] CREATE OR REPLACE TABLE FI_SGA_Extended 실행…')
    client.query(FI_SGA_EXTENDED_SQL).result()

    # 검증: 계정별 배분 합계 = FI_SM 원본 합계
    q = client.query(f'''
        WITH sm AS (
          SELECT Department, Year_Month, Cost_Account, SUM(Amount) AS sm_total
          FROM `{DATASET}.FI_SM`
          GROUP BY Department, Year_Month, Cost_Account
        ),
        ext AS (
          SELECT Department, Year_Month, Cost_Account,
                 SUM(allocated_amount) AS alloc_total,
                 COUNT(*) AS row_cnt
          FROM `{DATASET}.FI_SGA_Extended`
          GROUP BY Department, Year_Month, Cost_Account
        )
        SELECT
          COUNT(*) AS acct_groups,
          SUM(ext.row_cnt) AS total_rows,
          COUNTIF(ABS(sm.sm_total - ext.alloc_total) > 1) AS mismatch_cnt,
          MAX(ABS(sm.sm_total - ext.alloc_total)) AS max_diff
        FROM sm JOIN ext USING (Department, Year_Month, Cost_Account)
    ''').result()
    r = list(q)[0]
    log(f'[FI_SGA_Extended] 계정그룹 {r[0]}개, 전체행 {r[1]:,}, '
        f'배분오차>1원 {r[2]}건, 최대오차 {r[3]}원')

    log('[쿼리] CREATE OR REPLACE TABLE FI_SGA_Agg 실행…')
    client.query(FI_SGA_AGG_SQL).result()

    # 검증: FI_SGA_Agg 합계 = FI_SGA_Extended 합계
    q = client.query(f'''
        SELECT
          (SELECT COUNT(*) FROM `{DATASET}.FI_SGA_Agg`)    AS agg_rows,
          (SELECT SUM(allocated_amount) FROM `{DATASET}.FI_SGA_Agg`)      AS agg_total,
          (SELECT SUM(allocated_amount) FROM `{DATASET}.FI_SGA_Extended`) AS ext_total
    ''').result()
    r = list(q)[0]
    log(f'[FI_SGA_Agg] {r[0]:,}행, 합계 {r[1]:,} (Extended={r[2]:,}, '
        f'일치={abs((r[1] or 0)-(r[2] or 0)) <= 1})')


if __name__ == '__main__':
    with open('fi_sm_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_SM_SQL.strip() + '\n')
    with open('fi_final_sm_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_FINAL_SM_SQL.strip() + '\n')
    with open('fi_sga_extended_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_SGA_EXTENDED_SQL.strip() + '\n')
    with open('fi_sga_agg_query.sql', 'w', encoding='utf-8') as fh:
        fh.write(FI_SGA_AGG_SQL.strip() + '\n')
    direct, indirect, common, m1, m2, dashboard = build()
    if '--dry-run' in sys.argv:
        log('[dry-run] BQ 업로드/쿼리 생략')
    else:
        run(direct, indirect, common, m1, m2, dashboard)
    with open('_build_fi_sm_log.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(log_lines))
