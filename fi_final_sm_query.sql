CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_Final_SM` AS

-- ① FI_Final 손익을 Department×월로 집계 → 롱 포맷 전개
WITH pnl AS (
  SELECT Department, Year_Month,
         SUM(Sales_Amount)     AS Sales_Amount,
         SUM(Cost_of_Sales)    AS Cost_of_Sales,
         SUM(Gross_Profit)     AS Gross_Profit,
         SUM(Operating_Income) AS Operating_Income
  FROM `skin1004-319714.Sales_Integration.FI_Final`
  GROUP BY Department, Year_Month
),
-- FI_SM 간접비분류별 판관비 합계 (직접이익·공헌이익 파생에 사용)
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
  s.Indirect_Cost_Class
FROM `skin1004-319714.Sales_Integration.FI_SM` s

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
  CAST(NULL AS STRING) AS Indirect_Cost_Class
FROM pnl_long pl
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON pl.Department = m1.Cost_Center
