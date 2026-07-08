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

CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SGA_Agg` AS

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

FROM `skin1004-319714.Sales_Integration.FI_SGA_Extended`
GROUP BY
  Year_Month, Department,
  Country, Continent1, Continent2, Sales_Group, Brand, Line, Category, Sales_Type,
  Cost_Class, Indirect_Cost_Class, Cost_Center_Class, Sending_Cost_Center,
  Division, Team, Cost_Account, Account_Name,
  SM_Main_Category, SM_Sub_Category, SM_Detail_Category
