# ComfyUI Ultimate Director

ComfyUI 的 AI 影片分鏡與 MiniMax H3 工作流工具集。專案提供劇本與時間軸處理、角色參考圖整理、H3 鏡頭群組、影片段落銜接，以及可選的修臉、SelfLift 和 latent 放大節點。

> 專案仍在積極開發中。模型、ComfyUI 與其他節點版本會影響相容性和輸出結果；本專案不保證固定的畫質、生成時間或最低顯存需求。DLSS 5 不屬於此公開版本。

## 安裝

1. 確認 ComfyUI 已安裝，並依照你使用的工作流安裝所需的模型、VAE、文字編碼器及相依自訂節點。此儲存庫不包含模型權重。
2. 將此儲存庫放入 ComfyUI 的 `custom_nodes` 目錄：

   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/samyeh621109/ComfyUI-Ultimate-Director.git
   ```

3. 重新啟動 ComfyUI。若啟動記錄顯示缺少 Python 套件，請先確認錯誤來自哪個可選功能，再依該套件及你的 ComfyUI Python 環境安裝；本專案目前沒有統一的 `requirements.txt`。
4. 從 `example_workflows/` 載入範例工作流。若節點顯示缺失，請依 ComfyUI 記錄安裝相應的上游節點，並確認 H3 相關模型與工作流版本相容。

## 功能

- 劇本、角色和分鏡時間軸整理
- MiniMax H3 I2V / R2V 鏡頭群組與段落生成工具
- 分段連續性、預覽及影片輸出輔助
- 可選的人臉修復、SelfLift、分段 LoRA 與 latent 放大節點

詳細操作與工作流說明請見 [`MANUAL.md`](MANUAL.md) 及 [`DOCS_AI_FILM_PIPELINE.md`](DOCS_AI_FILM_PIPELINE.md)。兩份文件涵蓋特定工作流與設定；實際節點、模型相容性及效能請以你安裝的版本和 ComfyUI 記錄為準。

## 回報問題與貢獻

遇到問題時，請到 [GitHub Issues](https://github.com/samyeh621109/ComfyUI-Ultimate-Director/issues) 提交。請附上：

- 作業系統、ComfyUI 版本與本專案 commit
- 相關自訂節點、模型名稱及版本
- 重現步驟、預期結果與實際結果
- 移除私人路徑、API 金鑰及其他敏感資訊後的錯誤記錄

修正或功能提案可用 Pull Request 提交；大型變更建議先開 Issue 討論範圍與相容性。

## 授權

本專案採用 MIT License。部分整合程式碼的上游授權與聲明見 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
