CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SM` AS
WITH unified AS (
  -- 직접비: 원본 컬럼 그대로
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    Cost_Account,
    Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Direct_Cost`

  UNION ALL

  -- 간접비: 분류='판매간접', 받는 코스트센터→Department, 배부받은금액→Amount
  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Indirect_Cost`
)
SELECT
  t.Cost_Center_Class,
  t.Department,
  t.Cost_Account,
  t.Amount,
  t.Year_Month,
  IFNULL(m2.Account_Name, t.Cost_Account) AS Account_Name,
  m2.Main_Category,
  m2.Sub_Category,
  m2.Detail_Category,
  m1.Division,
  m1.Team,
  m1.Indirect_Cost_Class
FROM unified t
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching2` m2 ON t.Cost_Account = m2.Cost_Account
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON t.Department = m1.Cost_Center
