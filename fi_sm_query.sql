CREATE OR REPLACE TABLE `skin1004-319714.Sales_Integration.FI_SM` AS
WITH unified AS (
  -- 직접비: 자기 코스트센터를 Sending_Cost_Center로 → Indirect_Cost_Class='직접' 매핑
  SELECT
    Cost_Center_Class,
    Cost_Center AS Department,
    Cost_Center AS Sending_Cost_Center,
    Cost_Account,
    Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Direct_Cost`

  UNION ALL

  -- 판매간접: 받는 코스트센터→Department, 배부받은금액→Amount
  SELECT
    '판매간접' AS Cost_Center_Class,
    Receiving_Cost_Center AS Department,
    Sending_Cost_Center,
    Cost_Account,
    Allocated_Amount AS Amount,
    Year_Month
  FROM `skin1004-319714.Sales_Integration.FI_Indirect_Cost`

  UNION ALL

  -- 전사공통비: 받는 코스트센터→Department, 배부받은금액→Amount (판매간접과 동일 패턴)
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
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching2` m2 ON t.Cost_Account = m2.Cost_Account
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` m1 ON t.Department = m1.Cost_Center
LEFT JOIN `skin1004-319714.Sales_Integration.FI_Matching1` mc ON t.Sending_Cost_Center = mc.Cost_Center
