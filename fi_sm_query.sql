CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SM` AS
WITH unified AS (
  -- 직접비: 원본 컬럼 그대로 (보내는 코스트센터 없음 → NULL)
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    CAST(NULL AS STRING) AS Sending_Cost_Center,
    Cost_Account,
    Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Direct_Cost`

  UNION ALL

  -- 간접비: 분류='판매간접', 받는 코스트센터→Department, 배부받은금액→Amount
  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Indirect_Cost`
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
  mc.Indirect_Cost_Class
FROM unified t
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching2` m2 ON t.Cost_Account = m2.Cost_Account
-- 본부/팀: 귀속(받는/보유) 코스트센터 기준
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON t.Department = m1.Cost_Center
-- 간접비분류: 보내는 코스트센터 기준 (직접비는 보내는 쪽이 없으므로 자기 코스트센터 → '직접')
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` mc ON COALESCE(t.Sending_Cost_Center, t.Department) = mc.Cost_Center
