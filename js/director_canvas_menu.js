import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "UltimateDirector.CanvasMenu",
    async setup() {
        const createButton = () => {
            const menu = document.querySelector(".comfy-menu");
            if (!menu || document.getElementById("btn-ultimate-director-canvas")) {
                return;
            }

            const canvasBtn = document.createElement("button");
            canvasBtn.id = "btn-ultimate-director-canvas";
            canvasBtn.textContent = "🎬 短劇無限畫布 (Canvas)";
            canvasBtn.className = "comfyui-button primary";
            canvasBtn.style.background = "linear-gradient(135deg, #6366f1, #8b5cf6)";
            canvasBtn.style.color = "#ffffff";
            canvasBtn.style.fontWeight = "bold";
            canvasBtn.style.margin = "4px 0";
            canvasBtn.style.padding = "6px 12px";
            canvasBtn.style.borderRadius = "6px";
            canvasBtn.style.cursor = "pointer";
            canvasBtn.style.border = "none";
            canvasBtn.style.boxShadow = "0 2px 8px rgba(99, 102, 241, 0.4)";
            canvasBtn.title = "開啟 AI 短劇無限畫布 (Infinite Drama Canvas Studio)";

            canvasBtn.onmouseenter = () => {
                canvasBtn.style.background = "linear-gradient(135deg, #4f46e5, #7c3aed)";
            };
            canvasBtn.onmouseleave = () => {
                canvasBtn.style.background = "linear-gradient(135deg, #6366f1, #8b5cf6)";
            };

            canvasBtn.onclick = () => {
                window.open("/director_canvas/index.html", "_blank");
            };

            menu.append(canvasBtn);
        };

        // Try immediately and watch for menu insertion
        createButton();
        const observer = new MutationObserver(() => createButton());
        observer.observe(document.body, { childList: true, subtree: true });
    }
});
