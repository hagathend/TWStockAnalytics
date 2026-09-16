"""打包完成後，用「打包出來的 Python」跑的冒煙測試。

確認的是「使用者裝好之後能不能動」，不是邏輯正確性（那是 tests/ 的工作）：
- 所有模組都 import 得到（套件沒漏裝）
- 安裝版標記生效，資料會放在程式資料夾以外
- App 首次開啟（空資料庫）不會出錯，並且預設進到「開始使用」
- 內附的 Chromium 能產生含中文的 PDF
- 啟動器能把伺服器叫起來並通過健康檢查

用法：build\\app\\python\\python.exe packaging\\smoke_test.py build\\app
"""

import importlib
import importlib.machinery
import os
import sys
import tempfile
from pathlib import Path


def main(app_dir: Path) -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="twstock-smoke-"))
    os.environ["TWSTOCK_DATA_DIR"] = str(data_dir)  # 冒煙測試不碰使用者真正的資料
    sys.path.insert(0, str(app_dir))

    from src import config

    assert config.IS_INSTALLED, "缺少 .installed 標記"
    assert config.DATA_DIR == data_dir, config.DATA_DIR
    assert not str(config.DATA_DIR).startswith(str(app_dir)), "資料不可以放在程式資料夾裡"
    print("[ok] 安裝版標記與資料位置")

    for path in sorted((app_dir / "src").rglob("*.py")):
        module = ".".join(path.relative_to(app_dir).with_suffix("").parts)
        if module.endswith("__init__") or module == "src.app":
            continue
        importlib.import_module(module)
    print("[ok] 所有模組可匯入")

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(app_dir / "src" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    rendered = " ".join(m.value for m in at.markdown)
    assert "開始使用" in rendered, "空資料庫時應預設顯示「開始使用」"
    print("[ok] App 首次開啟")

    from src.report_pdf import markdown_to_pdf

    pdf = markdown_to_pdf("# 台股每日報告\n\n中文字型測試：台積電 2330 外資買超")
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000, "PDF 產生失敗"
    print(f"[ok] 內附 Chromium 產生 PDF（{len(pdf):,} bytes）")

    launcher = importlib.machinery.SourceFileLoader("launcher", str(app_dir / "launcher.pyw")).load_module()
    port = launcher.choose_port(8765)
    process = launcher.start_server(port)
    try:
        assert launcher.wait_until_ready(process, port, timeout=120), "伺服器沒有在時間內啟動"
        assert launcher.running_port() == port
        print(f"[ok] 啟動器啟動伺服器（port {port}）")
    finally:
        process.terminate()
        process.wait(timeout=30)

    print("冒煙測試全部通過")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
