-- ================================================================
-- FI 통합 빌드 스크립트 (BQ 콘솔에서 순서대로 실행)
-- 실행 순서: FI_Adjustment 보정 → FI_Final → FI_SM → FI_Final_SM → FI_SGA_Extended → FI_SGA_Agg
-- ================================================================


-- ────────────────────────────────────────────────────────────────
-- 0. FI_Adjustment 보정 (엑셀 수익성분석 정합성 맞춤)
--
-- [케이스 1] GM EAST 1/2 2026-04
--   원인: FI_Dashboard(=Sales_Project)에 이미 ERP 대비 ±2,203,646 차이 반영됨.
--         Sales_Diff를 0으로 설정 → FI_Final = FI_Dashboard = 엑셀값
--   * COGS_Diff는 건드리지 않음 (COGS는 엑셀과 이미 일치)
--
-- [케이스 2] 영업1 2026-02
--   원인: FI_Dashboard(14,606,590,095) - 엑셀(14,481,588,235) = 125,001,860 차이
--         Sales_Diff를 -125,001,860으로 설정 → FI_Final = 14,481,588,235 = 엑셀값
--   기존: -119,509,100 (= Sales_Project - Sales_ERP)
--   변경: -125,001,860 (= 엑셀값 - FI_Dashboard)
-- ────────────────────────────────────────────────────────────────
UPDATE `skin1004-319714.Sales_Integration.FI_Adjustment`
SET Sales_Diff = 0
WHERE Year_Month = '2026-04'
  AND Department IN ('GM EAST 1', 'GM EAST 2');

UPDATE `skin1004-319714.Sales_Integration.FI_Adjustment`
SET Sales_Diff = -125001860
WHERE Year_Month = '2026-02'
  AND Department = '영업1';


-- ────────────────────────────────────────────────────────────────
-- 1. FI_Final: 손익 원천 (FI_Dashboard + 고객/SKU/국가 매핑)
--
-- [조정 로직] FI_Adjustment(부서×월 단위) 조정값을
--   Product_Name='(조정)', Product_Code=NULL 인 별도 행으로 추가.
--   조정 행은 Country/Continent='기타' 고정 (부서 단위 조정이므로 국가 배분 불필요).
--   → Sales_Adj / COGS_Adj 컬럼 없음.
--
-- [Continent 보정] 멕시코는 SALES_ALL_Backup 매핑 오류 방지를 위해
--   Continent1='중미', Continent2='중앙아메리카'로 강제 override.
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_Final` AS
WITH
Dept_Map AS (
  SELECT * FROM UNNEST([
    STRUCT('GM EAST 1'        AS Department, 'Nirvasian_틱톡_필리핀'                AS Customer, '필리핀'      AS Country),
    STRUCT('GM EAST 1',        'FAST BEAUTY_쇼피',                     '인도네시아'),
    STRUCT('GM EAST 1',        'Nirvasian_쇼피_필리핀',                '필리핀'),
    STRUCT('GM EAST 1',        'FAST BEAUTY_틱톡',                     '인도네시아'),
    STRUCT('GM EAST 2',        '[스킨1004]쇼피_싱가폴B2C',             '싱가폴'),
    STRUCT('GM EAST 2',        'STORE N GO SDN. BHD_말레이시아_쇼피',  '말레이시아'),
    STRUCT('GM EAST 2',        'STORE N GO SDN. BHD_말레이시아_틱톡',  '말레이시아'),
    STRUCT('GM WEST Ecomm',    'AMAZON_미국',                         '미국'),
    STRUCT('GM WEST Ecomm',    'Craver USA 법인',                     '미국'),
    STRUCT('GM WEST Ecomm',    'AMAZON_호주',                         '호주'),
    STRUCT('GM WEST Ecomm',    '비욘드어스 주식회사',                 '한국'),
    STRUCT('GM WEST Ecomm',    'Walmart(B2C)',                        '미국'),
    STRUCT('GM WEST MKT',      'Stylevana_AU',                        '글로벌_플랫폼'),
    STRUCT('GM WEST MKT',      '실리콘투',                            '글로벌_플랫폼'),
    STRUCT('GM WEST MKT',      'Craver USA 법인',                     '글로벌_플랫폼'),
    STRUCT('GM WEST MKT',      '씨제이올리브영',                      '글로벌_플랫폼'),
    STRUCT('GM WEST MKT',      '예스아시아닷컴코리아',                '글로벌_플랫폼'),
    STRUCT('GM WEST MKT',      'Stylevana',                           '글로벌_플랫폼'),
    STRUCT('BCM_플래그십 파트', '명동플래그십',                        '한국'),
    STRUCT('BCM_플래그십 파트', 'Craver USA 법인',                     '미국')
  ])
),
Dept_Only_Map AS (
  SELECT * FROM UNNEST([
    STRUCT('GM CBT' AS Department, '중국' AS Country),
    STRUCT('GM JBT', '일본'),
    STRUCT('GM KBT', '한국'),
    STRUCT('전사',   '기타'),
    STRUCT('FI',     '기타')
  ])
),
Group_Map AS (
  SELECT * FROM UNNEST([
    STRUCT('리테일_리테일3'           AS Department, 'UM'     AS `Group`),
    STRUCT('리테일_리테일1',           'UM'),
    STRUCT('리테일_리테일2',           'UM'),
    STRUCT('뉴비지니스_뉴비즈1',       'UM'),
    STRUCT('GM CBT',                   'GM'),
    STRUCT('코스트코',                 'UM'),
    STRUCT('영업2',                    'B2B'),
    STRUCT('GM EAST 2',                'GM'),
    STRUCT('영업1',                    'B2B'),
    STRUCT('GM JBT',                   'GM'),
    STRUCT('GM EAST 1',                'GM'),
    STRUCT('GM WEST Ecomm',            'GM'),
    STRUCT('BCM_플래그십 파트',         'PR'),
    STRUCT('GM KBT',                   'GM'),
    STRUCT('전사',                     'Others'),
    STRUCT('뉴비지니스_뉴비즈2',       'UM'),
    STRUCT('GM WEST MKT',              'GM'),
    STRUCT('DD_Distribution 2_Part 2', 'UM'),
    STRUCT('DD_Distribution 2_Part 1', 'UM'),
    STRUCT('Sales Operation',          'Others'),
    STRUCT('FI',                       'Others'),
    STRUCT('DD_Distribution 2_Part 3', 'UM'),
    STRUCT('B2B1',                     'B2B'),
    STRUCT('B2B2',                     'B2B'),
    STRUCT('B2B3',                     'B2B'),
    STRUCT('UMMA',                     'UM')
  ])
),
Brand_Map AS (
  SELECT * FROM UNNEST([
    STRUCT('리테일_리테일1'           AS Department, 'UM'     AS Brand),
    STRUCT('리테일_리테일3',           'UM'),
    STRUCT('GM EAST 1',                'SK'),
    STRUCT('리테일_리테일2',           'UM'),
    STRUCT('BCM_플래그십 파트',         'SK'),
    STRUCT('뉴비지니스_뉴비즈1',       'UM'),
    STRUCT('영업2',                    'SK'),
    STRUCT('GM WEST MKT',              'SK'),
    STRUCT('영업1',                    'SK'),
    STRUCT('GM KBT',                   'SK'),
    STRUCT('GM EAST 2',                'SK'),
    STRUCT('코스트코',                 'UM'),
    STRUCT('GM CBT',                   'SK'),
    STRUCT('GM JBT',                   'SK'),
    STRUCT('GM WEST Ecomm',            'SK'),
    STRUCT('전사',                     'Others'),
    STRUCT('뉴비지니스_뉴비즈2',       'UM'),
    STRUCT('DD_Distribution 2_Part 3', 'UM'),
    STRUCT('DD_Distribution 2_Part 1', 'UM'),
    STRUCT('DD_Distribution 2_Part 2', 'UM'),
    STRUCT('FI',                       'Others'),
    STRUCT('Sales Operation',          'Others'),
    STRUCT('B2B1',                     'SK'),
    STRUCT('B2B2',                     'SK'),
    STRUCT('B2B3',                     'SK'),
    STRUCT('UMMA',                     'UM')
  ])
),
B_Company AS (
  SELECT Company_Name, Sales_Type, Country, Team_NEW
  FROM (
    SELECT Company_Name, Sales_Type, Country, Team_NEW,
           ROW_NUMBER() OVER (
             PARTITION BY Company_Name
             ORDER BY (Sales_Type IS NULL), (Country IS NULL), Date DESC
           ) AS rn
    FROM `skin1004-319714.Sales_Integration.SALES_ALL_Backup`
    WHERE Company_Name IS NOT NULL AND Company_Name != ''
  )
  WHERE rn = 1
),
B_SKU AS (
  SELECT SKU, Line, Category
  FROM (
    SELECT SKU, Line, Category,
           ROW_NUMBER() OVER (
             PARTITION BY SKU
             ORDER BY (Line IS NULL), (Category IS NULL), Date DESC
           ) AS rn
    FROM `skin1004-319714.Sales_Integration.SALES_ALL_Backup`
    WHERE SKU IS NOT NULL AND SKU != ''
  )
  WHERE rn = 1
),
FI_Match AS (
  SELECT Product_Code, Line, Category
  FROM (
    SELECT Product_Code, Line, Category,
           ROW_NUMBER() OVER (
             PARTITION BY Product_Code
             ORDER BY (Line IS NULL), (Category IS NULL)
           ) AS rn
    FROM `skin1004-319714.Sales_Integration.FI_Matching`
    WHERE Product_Code IS NOT NULL AND Product_Code != ''
  )
  WHERE rn = 1
),
ERP_Country AS (
  SELECT CustName, CountryName
  FROM (
    SELECT CustName, CountryName,
           ROW_NUMBER() OVER (
             PARTITION BY CustName
             ORDER BY InvoiceDate DESC
           ) AS rn
    FROM `skin1004-319714.Sales_RAW.ERP_DB`
    WHERE CustName    IS NOT NULL AND CustName    != ''
      AND CountryName IS NOT NULL AND CountryName != ''
  )
  WHERE rn = 1
),
B_Continent AS (
  SELECT Country, Continent1, Continent2
  FROM (
    SELECT Country, Continent1, Continent2,
           ROW_NUMBER() OVER (
             PARTITION BY Country
             ORDER BY (Continent1 IS NULL), (Continent2 IS NULL), Date DESC
           ) AS rn
    FROM `skin1004-319714.Sales_Integration.SALES_ALL_Backup`
    WHERE Country IS NOT NULL AND Country != ''
  )
  WHERE rn = 1
)

-- ── 일반 거래 행 ─────────────────────────────────────────────────
SELECT
  base.Year_Month,
  base.Customer,
  base.Product_Name,
  base.Product_Code,
  base.Specification,
  base.Sales_Quantity,
  base.SG_and_A_Expenses,
  base.Sales_Type,
  base.Dept_Resolved                                                    AS Department,
  CASE
    WHEN bm.Brand = 'UM' THEN 'UM'
    WHEN base.Line IS NULL OR base.Line = '' OR base.Line IN ('ZB', 'C_Line') THEN 'Others'
    ELSE base.Line
  END                                                                   AS Line,
  CASE
    WHEN bm.Brand = 'UM' THEN 'UM'
    WHEN base.Category IS NULL OR base.Category = '' THEN 'Others'
    ELSE base.Category
  END                                                                   AS Category,
  ROUND(base.Sales_Amount,     0)                                       AS Sales_Amount,
  ROUND(base.Cost_of_Sales,    0)                                       AS Cost_of_Sales,
  ROUND(base.Gross_Profit,     0)                                       AS Gross_Profit,
  ROUND(base.Operating_Income, 0)                                       AS Operating_Income,
  IFNULL(base.Country,    'Others')                                     AS Country,
  CASE WHEN base.Country = '멕시코' THEN '중미'
       ELSE IFNULL(cont.Continent1, 'Others') END                       AS Continent1,
  CASE WHEN base.Country = '멕시코' THEN '중앙아메리카'
       ELSE IFNULL(cont.Continent2, 'Others') END                       AS Continent2,
  gm.`Group`                                                            AS `Group`,
  bm.Brand                                                              AS Brand
FROM (
  SELECT
    a.*,
    IFNULL(bc.Sales_Type, 'B2C') AS Sales_Type,
    a.Department                  AS Dept_Resolved,
    COALESCE(NULLIF(bs.Line, ''),     fm.Line)     AS Line,
    COALESCE(NULLIF(bs.Category, ''), fm.Category) AS Category,
    COALESCE(
      dm.Country,
      dom.Country,
      CASE
        WHEN a.Department = '영업1' AND bc.Team_NEW = 'B2B1' THEN bc.Country
        WHEN a.Department = '영업2' AND bc.Team_NEW = 'B2B2' THEN bc.Country
      END,
      NULLIF(bc.Country, ''),
      NULLIF(erp.CountryName, '')
    ) AS Country
  FROM `skin1004-319714.Sales_Integration.FI_Dashboard` a
  LEFT JOIN B_Company     bc  ON a.Customer     = bc.Company_Name
  LEFT JOIN B_SKU         bs  ON a.Product_Code = bs.SKU
  LEFT JOIN FI_Match      fm  ON a.Product_Code = fm.Product_Code
  LEFT JOIN ERP_Country   erp ON a.Customer     = erp.CustName
  LEFT JOIN Dept_Map      dm  ON a.Department   = dm.Department AND a.Customer = dm.Customer
  LEFT JOIN Dept_Only_Map dom ON a.Department   = dom.Department
) base
LEFT JOIN B_Continent  cont ON base.Country       = cont.Country
LEFT JOIN Group_Map    gm   ON base.Dept_Resolved = gm.Department
LEFT JOIN Brand_Map    bm   ON base.Dept_Resolved = bm.Department

UNION ALL

-- ── 조정 행 (부서×월 단위, Country/Continent='기타' 고정) ─────────
-- Product_Code IS NULL & Product_Name='(조정)' 으로 식별
SELECT
  adj.Year_Month,
  NULL                                     AS Customer,
  '(조정)'                                 AS Product_Name,
  NULL                                     AS Product_Code,
  NULL                                     AS Specification,
  CAST(NULL AS INT64)                      AS Sales_Quantity,
  0                                        AS SG_and_A_Expenses,
  '기타'                                   AS Sales_Type,
  adj.Department,
  NULL                                     AS Line,
  NULL                                     AS Category,
  ROUND(adj.Sales_Diff, 0)                 AS Sales_Amount,
  ROUND(adj.COGS_Diff,  0)                 AS Cost_of_Sales,
  ROUND(adj.Sales_Diff - adj.COGS_Diff, 0) AS Gross_Profit,
  ROUND(adj.Sales_Diff - adj.COGS_Diff, 0) AS Operating_Income,
  '기타'                                   AS Country,
  '기타'                                   AS Continent1,
  '기타'                                   AS Continent2,
  COALESCE(gm2.`Group`, 'Others')          AS `Group`,
  COALESCE(bm2.Brand,   'Others')          AS Brand
FROM `skin1004-319714.Sales_Integration.FI_Adjustment` adj
LEFT JOIN Group_Map gm2 ON adj.Department = gm2.Department
LEFT JOIN Brand_Map bm2 ON adj.Department = bm2.Department
WHERE adj.Department NOT IN ('전체', '매출원가가감계정')
  AND (adj.Sales_Diff != 0 OR adj.COGS_Diff != 0);


-- ────────────────────────────────────────────────────────────────
-- 2. FI_SM: 판매직접 + 판매간접 + 전사공통비 배부내역
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SM` AS
WITH unified AS (
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    Cost_Center AS Sending_Cost_Center,
    Cost_Account,
    Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Direct_Cost`

  UNION ALL

  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Indirect_Cost`

  UNION ALL

  SELECT
    '전사공통비' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Common_Cost`
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
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching2` m2 ON t.Cost_Account        = m2.Cost_Account
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON t.Department          = m1.Cost_Center
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` mc ON t.Sending_Cost_Center = mc.Cost_Center;


-- ────────────────────────────────────────────────────────────────
-- 3. FI_Final_SM: 판관비(FI_SM) + 손익 6항목 (변경 없음)
--    FI_Final에 조정 행이 포함되므로 SUM 집계 시 자동 반영됨
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_Final_SM` AS
WITH pnl AS (
  SELECT Department, Year_Month,
         SUM(Sales_Amount)     AS Sales_Amount,
         SUM(Cost_of_Sales)    AS Cost_of_Sales,
         SUM(Gross_Profit)     AS Gross_Profit,
         SUM(Operating_Income) AS Operating_Income
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month
),
sga_class AS (
  SELECT Department, Year_Month,
    SUM(CASE WHEN Indirect_Cost_Class = '직접'    THEN Amount ELSE 0 END) AS sga_direct,
    SUM(CASE WHEN Indirect_Cost_Class = '조직간접' THEN Amount ELSE 0 END) AS sga_org_indirect
  FROM `skin1004-319714.Sales_Integration.FI_SM`
  GROUP BY Department, Year_Month
),
pnl_long AS (
  SELECT p.Department, p.Year_Month, item.name AS Item, item.amt AS Amount
  FROM pnl p
  LEFT JOIN sga_class sc ON p.Department = sc.Department AND p.Year_Month = sc.Year_Month,
  UNNEST([
    STRUCT('매출액'    AS name, p.Sales_Amount                                                          AS amt),
    STRUCT('매출원가',           p.Cost_of_Sales),
    STRUCT('매출총이익',         p.Gross_Profit),
    STRUCT('직접이익',           p.Gross_Profit - COALESCE(sc.sga_direct, 0)),
    STRUCT('공헌이익',           p.Gross_Profit - COALESCE(sc.sga_direct, 0) - COALESCE(sc.sga_org_indirect, 0)),
    STRUCT('영업이익',           p.Operating_Income)
  ]) AS item
)
SELECT
  '판관비' AS Item_Class,
  s.Cost_Center_Class, s.Department, s.Sending_Cost_Center,
  s.Cost_Account, s.Amount, s.Year_Month, s.Account_Name,
  s.Main_Category, s.Sub_Category, s.Detail_Category,
  s.Division, s.Team, s.Indirect_Cost_Class, s.Cost_Class
FROM `skin1004-319714.Sales_Integration.FI_SM` s

UNION ALL

SELECT
  pl.Item AS Item_Class,
  CAST(NULL AS STRING), pl.Department, CAST(NULL AS STRING),
  pl.Item, pl.Amount, pl.Year_Month, pl.Item, pl.Item, pl.Item, pl.Item,
  m1.Division, m1.Team, CAST(NULL AS STRING), CAST(NULL AS STRING)
FROM pnl_long pl
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON pl.Department = m1.Cost_Center;


-- ────────────────────────────────────────────────────────────────
-- 4. FI_SGA_Extended: FI_Final 차원 × FI_SM 원가계정 확장 테이블
--    조정 행(Product_Code IS NULL) 제외 후 판관비 배분 비율 계산
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SGA_Extended` AS
WITH
dept_sga AS (
  SELECT Department, Year_Month, SUM(SG_and_A_Expenses) AS dept_sga_total
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month
),
country_sga AS (
  SELECT Department, Year_Month, Country, SUM(SG_and_A_Expenses) AS country_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Country
),
continent1_sga AS (
  SELECT Department, Year_Month, Continent1, SUM(SG_and_A_Expenses) AS continent1_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Continent1
),
continent2_sga AS (
  SELECT Department, Year_Month, Continent2, SUM(SG_and_A_Expenses) AS continent2_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Continent2
),
brand_sga AS (
  SELECT Department, Year_Month, Brand, SUM(SG_and_A_Expenses) AS brand_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Brand
),
line_sga AS (
  SELECT Department, Year_Month, Line, SUM(SG_and_A_Expenses) AS line_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Line
),
category_sga AS (
  SELECT Department, Year_Month, Category, SUM(SG_and_A_Expenses) AS category_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Category
),
sales_type_sga AS (
  SELECT Department, Year_Month, Sales_Type, SUM(SG_and_A_Expenses) AS sales_type_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  WHERE Product_Code IS NOT NULL AND Product_Code != ''
  GROUP BY Department, Year_Month, Sales_Type
)
SELECT
  f.Year_Month,
  f.Department,
  f.Country,
  f.Continent1,
  f.Continent2,
  f.`Group`        AS Sales_Group,
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
  ROUND(SAFE_DIVIDE(f.SG_and_A_Expenses, d.dept_sga_total), 8) AS row_allocation_ratio,
  ROUND(s.Amount * SAFE_DIVIDE(f.SG_and_A_Expenses, d.dept_sga_total), 0) AS allocated_amount,
  ROUND(SAFE_DIVIDE(cs.country_sga,    d.dept_sga_total), 6) AS country_ratio,
  ROUND(SAFE_DIVIDE(c1.continent1_sga, d.dept_sga_total), 6) AS continent1_ratio,
  ROUND(SAFE_DIVIDE(c2.continent2_sga, d.dept_sga_total), 6) AS continent2_ratio,
  ROUND(SAFE_DIVIDE(br.brand_sga,      d.dept_sga_total), 6) AS brand_ratio,
  ROUND(SAFE_DIVIDE(ls.line_sga,       d.dept_sga_total), 6) AS line_ratio,
  ROUND(SAFE_DIVIDE(ca.category_sga,   d.dept_sga_total), 6) AS category_ratio,
  ROUND(SAFE_DIVIDE(st.sales_type_sga, d.dept_sga_total), 6) AS sales_type_ratio
FROM `skin1004-319714.Sales_Integration.FI_Final`  f
JOIN  dept_sga d
  ON  f.Department = d.Department AND f.Year_Month = d.Year_Month
JOIN  `skin1004-319714.Sales_Integration.FI_SM`    s
  ON  f.Department = s.Department AND f.Year_Month = s.Year_Month
LEFT JOIN country_sga    cs ON f.Department = cs.Department AND f.Year_Month = cs.Year_Month AND f.Country    = cs.Country
LEFT JOIN continent1_sga c1 ON f.Department = c1.Department AND f.Year_Month = c1.Year_Month AND f.Continent1 = c1.Continent1
LEFT JOIN continent2_sga c2 ON f.Department = c2.Department AND f.Year_Month = c2.Year_Month AND f.Continent2 = c2.Continent2
LEFT JOIN brand_sga      br ON f.Department = br.Department AND f.Year_Month = br.Year_Month AND f.Brand      = br.Brand
LEFT JOIN line_sga       ls ON f.Department = ls.Department AND f.Year_Month = ls.Year_Month AND f.Line       = ls.Line
LEFT JOIN category_sga   ca ON f.Department = ca.Department AND f.Year_Month = ca.Year_Month AND f.Category   = ca.Category
LEFT JOIN sales_type_sga st ON f.Department = st.Department AND f.Year_Month = st.Year_Month AND f.Sales_Type = st.Sales_Type
WHERE f.Product_Code IS NOT NULL AND f.Product_Code != '';


-- ────────────────────────────────────────────────────────────────
-- 5. FI_SGA_Agg: FI_SGA_Extended 집계 뷰 (변경 없음)
-- ────────────────────────────────────────────────────────────────
CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SGA_Agg` AS
SELECT
  Year_Month,
  Department,
  Country,
  Continent1,
  Continent2,
  Sales_Group,
  Brand,
  Line,
  Category,
  Sales_Type,
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
  SUM(allocated_amount)                                                AS allocated_amount,
  MAX(sm_account_dept_total)                                           AS sm_account_dept_total,
  MAX(dept_sga_total)                                                  AS dept_sga_total,
  ROUND(SAFE_DIVIDE(SUM(allocated_amount), MAX(dept_sga_total))        * 100, 4) AS alloc_pct_of_dept,
  ROUND(SAFE_DIVIDE(SUM(allocated_amount), MAX(sm_account_dept_total)) * 100, 4) AS alloc_pct_of_acct,
  MAX(country_ratio)                                                   AS country_ratio,
  MAX(continent1_ratio)                                                AS continent1_ratio,
  MAX(continent2_ratio)                                                AS continent2_ratio,
  MAX(brand_ratio)                                                     AS brand_ratio,
  MAX(line_ratio)                                                      AS line_ratio,
  MAX(category_ratio)                                                  AS category_ratio,
  MAX(sales_type_ratio)                                                AS sales_type_ratio
FROM `skin1004-319714.Sales_Integration.FI_SGA_Extended`
GROUP BY
  Year_Month, Department,
  Country, Continent1, Continent2, Sales_Group, Brand, Line, Category, Sales_Type,
  Cost_Class, Indirect_Cost_Class, Cost_Center_Class, Sending_Cost_Center,
  Division, Team, Cost_Account, Account_Name,
  SM_Main_Category, SM_Sub_Category, SM_Detail_Category;
