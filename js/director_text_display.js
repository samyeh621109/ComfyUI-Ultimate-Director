// -*- coding: utf-8 -*-
/**
 * Ultimate Director: Interactive Text Display & Script Viewer
 * Modern ComfyUI DOM Widget supporting full text inspection, selection, and 1-click clipboard copy.
 */

const { app } = window.comfyAPI.app;

app.registerExtension({
    name: "UltimateDirector.TextDisplay",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "UltimateDirectorTextDisplay" || nodeData.name === "ShowText|pysssss") {
            const originalCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const res = originalCreated?.apply(this, arguments);
                this._initTextDisplay();
                return res;
            };

            const originalConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (info) {
                const res = originalConfigure?.apply(this, arguments);
                this._initTextDisplay();
                if (info?.widgets_values?.[0]) {
                    this._setText(info.widgets_values[0]);
                }
                return res;
            };

            const originalExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const res = originalExecuted?.apply(this, arguments);
                if (message?.text || message?.string) {
                    const raw = message.text || message.string;
                    const text = Array.isArray(raw) ? raw.join("\n") : String(raw);
                    this._setText(text);
                }
                return res;
            };

            nodeType.prototype._initTextDisplay = function () {
                if (this._textContainer) return;

                const wrap = document.createElement("div");
                wrap.style.display = "flex";
                wrap.style.flexDirection = "column";
                wrap.style.width = "100%";
                wrap.style.height = "100%";
                wrap.style.boxSizing = "border-box";
                wrap.style.padding = "6px";
                wrap.style.gap = "6px";

                const topBar = document.createElement("div");
                topBar.style.display = "flex";
                topBar.style.justifyContent = "space-between";
                topBar.style.alignItems = "center";

                const title = document.createElement("span");
                title.textContent = "📜 劇本 / 提示詞預覽 (可直接選取複製)";
                title.style.fontSize = "12px";
                title.style.fontWeight = "bold";
                title.style.color = "#8b949e";
                title.style.fontFamily = "sans-serif";

                const copyBtn = document.createElement("button");
                copyBtn.textContent = "📋 複製提示詞 (Copy)";
                copyBtn.style.padding = "4px 12px";
                copyBtn.style.fontSize = "12px";
                copyBtn.style.fontWeight = "bold";
                copyBtn.style.borderRadius = "4px";
                copyBtn.style.border = "1px solid #388bfd44";
                copyBtn.style.backgroundColor = "#21262d";
                copyBtn.style.color = "#58a6ff";
                copyBtn.style.cursor = "pointer";
                copyBtn.addEventListener("mouseenter", () => {
                    copyBtn.style.backgroundColor = "#30363d";
                });
                copyBtn.addEventListener("mouseleave", () => {
                    copyBtn.style.backgroundColor = "#21262d";
                });
                copyBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (this._textarea && this._textarea.value) {
                        navigator.clipboard.writeText(this._textarea.value).then(() => {
                            copyBtn.textContent = "✅ 已複製到剪貼簿！";
                            copyBtn.style.color = "#7ee787";
                            setTimeout(() => {
                                copyBtn.textContent = "📋 複製提示詞 (Copy)";
                                copyBtn.style.color = "#58a6ff";
                            }, 2000);
                        });
                    }
                });

                topBar.append(title, copyBtn);

                const textarea = document.createElement("textarea");
                textarea.style.width = "100%";
                textarea.style.height = "260px";
                textarea.style.fontSize = "12px";
                textarea.style.fontFamily = "monospace";
                textarea.style.lineHeight = "1.5";
                textarea.style.color = "#7ee787";
                textarea.style.backgroundColor = "#0d1117";
                textarea.style.border = "1px solid #30363d";
                textarea.style.borderRadius = "6px";
                textarea.style.padding = "8px";
                textarea.style.resize = "vertical";
                textarea.style.boxSizing = "border-box";
                textarea.placeholder = "等待執行生成劇本與提示詞...";

                wrap.append(topBar, textarea);
                this._textarea = textarea;
                this._textContainer = wrap;

                if (typeof this.addDOMWidget === "function") {
                    this.addDOMWidget("text_display_widget", "text_display_widget", wrap, {
                        hideOnZoom: false,
                        getMinHeight: () => 300,
                        getValue: () => this._textarea?.value || "",
                        setValue: (val) => this._setText(val),
                    });
                }

                const currentSize = this.size || [520, 360];
                this.setSize([
                    Math.max(currentSize[0], 520),
                    Math.max(currentSize[1], 360)
                ]);
            };

            nodeType.prototype._setText = function (text) {
                if (!this._textContainer) this._initTextDisplay();
                if (this._textarea) {
                    this._textarea.value = text || "";
                }
                if (this.widgets_values) {
                    this.widgets_values[0] = text || "";
                }
            };
        }
    }
});
