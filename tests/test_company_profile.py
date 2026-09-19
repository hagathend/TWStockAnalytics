import unittest
from unittest.mock import MagicMock, patch

import requests

from src.collectors import company_profile

HTML = """<table>
<tr><td>本資料由 (上市公司) 台積電 公司提供</td></tr>
<tr><th>股票代號</th><td>2330</td><th>產業類別</th><td>半導體業</td></tr>
<tr><th>公司名稱</th><td>台灣積體電路製造股份有限公司</td><th>總機</th><td>03-5636688</td></tr>
<tr><th>董事長</th><td>魏哲家</td><th>總經理</th><td>總裁: 魏哲家</td></tr>
<tr><th>主要經營業務</th><td>依客戶之訂單從事製造與銷售積體電
路以及 IC design service 之電腦輔助設計</td></tr>
<tr><th>公司成立日期</th><td>76/02/21</td><th>實收資本額</th><td>259,323,700,670元</td></tr>
<tr><th>上櫃日期</th><td>&nbsp</td><th>興櫃日期</th><td>&nbsp</td></tr>
<tr><th>已發行普通股數或
TDR原股發行股數</th><td>25,932,370,067股
(含私募  0股)</td></tr>
<tr><th>本公司</th><td>無</td><th>特別股發行</th><th>本公司</th><td>有</td></tr>
</table>"""


class CompanyProfileTest(unittest.TestCase):
    def test_parse(self):
        profile = company_profile.parse(HTML)
        self.assertEqual(profile["industry"], "半導體業")
        self.assertEqual(profile["founded"], "1987-02-21")
        self.assertEqual(profile["listed_tpex"], "")
        self.assertEqual(profile["shares"], "25,932,370,067股")
        self.assertEqual(profile["business"], "依客戶之訂單從事製造與銷售積體電路以及IC design service之電腦輔助設計")
        self.assertEqual(profile["listed_twse"], "")  # 頁面沒有這一欄

    def test_not_found(self):
        self.assertIsNone(company_profile.parse("<html><body>查無資料</body></html>"))

    def test_fetch_errors_are_messages(self):
        with patch.object(company_profile.requests, "post", side_effect=requests.ConnectionError("down")):
            ok, message = company_profile.fetch("2330")
        self.assertFalse(ok)
        self.assertIn("連線失敗", message)
        resp = MagicMock(text="<html></html>")
        with patch.object(company_profile.requests, "post", return_value=resp):
            self.assertEqual(company_profile.fetch("0050")[0], False)


if __name__ == "__main__":
    unittest.main()
