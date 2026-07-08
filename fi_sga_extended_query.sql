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

CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SGA_Extended` AS

WITH

dept_sga AS (
  SELECT Department, Year_Month, SUM(SG_and_A_Expenses) AS dept_sga_total
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month
),
country_sga AS (
  SELECT Department, Year_Month, Country, SUM(SG_and_A_Expenses) AS country_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Country
),
continent1_sga AS (
  SELECT Department, Year_Month, Continent1, SUM(SG_and_A_Expenses) AS continent1_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Continent1
),
continent2_sga AS (
  SELECT Department, Year_Month, Continent2, SUM(SG_and_A_Expenses) AS continent2_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Continent2
),
brand_sga AS (
  SELECT Department, Year_Month, Brand, SUM(SG_and_A_Expenses) AS brand_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Brand
),
line_sga AS (
  SELECT Department, Year_Month, Line, SUM(SG_and_A_Expenses) AS line_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Line
),
category_sga AS (
  SELECT Department, Year_Month, Category, SUM(SG_and_A_Expenses) AS category_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month, Category
),
sales_type_sga AS (
  SELECT Department, Year_Month, Sales_Type, SUM(SG_and_A_Expenses) AS sales_type_sga
  FROM `skin1004-319714.Sales_Integration.FI_Final`
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

FROM `skin1004-319714.Sales_Integration.FI_Final`       f
JOIN  dept_sga d
  ON  f.Department = d.Department AND f.Year_Month = d.Year_Month
JOIN  `skin1004-319714.Sales_Integration.FI_SM`         s
  ON  f.Department = s.Department AND f.Year_Month = s.Year_Month
LEFT JOIN country_sga    cs ON f.Department = cs.Department AND f.Year_Month = cs.Year_Month AND f.Country    = cs.Country
LEFT JOIN continent1_sga c1 ON f.Department = c1.Department AND f.Year_Month = c1.Year_Month AND f.Continent1 = c1.Continent1
LEFT JOIN continent2_sga c2 ON f.Department = c2.Department AND f.Year_Month = c2.Year_Month AND f.Continent2 = c2.Continent2
LEFT JOIN brand_sga      br ON f.Department = br.Department AND f.Year_Month = br.Year_Month AND f.Brand      = br.Brand
LEFT JOIN line_sga       ls ON f.Department = ls.Department AND f.Year_Month = ls.Year_Month AND f.Line       = ls.Line
LEFT JOIN category_sga   ca ON f.Department = ca.Department AND f.Year_Month = ca.Year_Month AND f.Category   = ca.Category
LEFT JOIN sales_type_sga st ON f.Department = st.Department AND f.Year_Month = st.Year_Month AND f.Sales_Type = st.Sales_Type
