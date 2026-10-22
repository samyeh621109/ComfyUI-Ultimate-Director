# -*- coding: utf-8 -*-
"""Ultimate Director - Krea2 & Cinematic Style Manager.

Scans and indexes professional visual styles from /sample/styles or custom directories,
allowing the Story Engine and AutoCast Generator to apply 4000+ cinematic, photographic,
anime, and 3D render aesthetics seamlessly.
"""

import os
import json
import logging
from typing import Dict, List, Tuple, Optional

log = logging.getLogger("UltimateDirector.StyleManager")

_STYLE_SEARCH_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "sample", "styles"),
    os.path.join(os.path.dirname(__file__), "styles"),
]

# Built-in curated master presets for instant selection
_BUILTIN_STYLES: Dict[str, Dict[str, str]] = {
    "Cinematic Realism (頂級電影寫實光影)": {
        "prompt": "Style: hyper-realistic 35mm film photography, cinematic lighting, rich skin textures, natural catchlights, dramatic chiaroscuro, sharp focus, 8k uhd, masterwork. Subject:{prompt}",
        "negative": "ugly, deformed, disfigured, poor anatomy, bad hands, missing fingers, extra limbs, low quality, blurry, text, watermark, logo",
    },
    "Cinema-Tone (好萊塢電影色調)": {
        "prompt": "Style: cinematic scale, high-contrast atmospheric perspective, moody film tone, rich depth of field, refined portrait craftsmanship, 35mm anamorphic lens. Subject:{prompt}",
        "negative": "low quality, cartoon, flat lighting, oversaturated, watermark, text",
    },
    "Photo-Real Studio (8K商業攝影寫實)": {
        "prompt": "Style: high-end commercial studio portraiture, soft key lighting, clean background separation, ultra-detailed facial pores and fabric weave, Vogue editorial aesthetics. Subject:{prompt}",
        "negative": "illustration, 3d render, painting, blurry, distorted anatomy, text",
    },
    "Cyberpunk Neon (賽博龐克高對比霓虹)": {
        "prompt": "Style: neo-noir cyberpunk aesthetics, high-contrast cyan and magenta rim lighting, wet reflective surfaces, volumetric fog, glowing circuit traces, moody night atmosphere. Subject:{prompt}",
        "negative": "daylight, flat colors, washed out, low contrast, text, watermark",
    },
    "Eastern Myth & Fantasy (東方神話仙俠玄幻)": {
        "prompt": "Style: majestic eastern epic cinematic lighting, celestial mist, ethereal golden aura, intricate traditional craftsmanship and dragon-scale armor, 8k resolution masterwork. Subject:{prompt}",
        "negative": "western armor, modern clothing, blurry, low resolution, watermark, text",
    },
    "Anime Masterpiece (新海誠日系動漫電影)": {
        "prompt": "Style: Makoto Shinkai anime aesthetic, breathtaking sky illumination, vibrant saturated pastel colors, luminous particle dust, clean outlines, emotional depth. Subject:{prompt}",
        "negative": "photorealistic, 3d, realistic skin, deformed, text, watermark",
    },
    "Pixar 3D Render (皮克斯頂級3D動畫)": {
        "prompt": "Style: Pixar and Disney 3D animation style, Unreal Engine 5 render, subsurface scattering on skin, expressive stylized anatomy, charming lighting and rich textures. Subject:{prompt}",
        "negative": "flat 2d, live action photo, noisy, ugly, low quality, text",
    },
    "Gothic Mystery (暗黑哥德神秘油畫)": {
        "prompt": "Style: dramatic chiaroscuro, low-key lighting, moody desaturated tones, velvet and antique textures, mysterious Rembrandt shadow, evocative depth. Subject:{prompt}",
        "negative": "bright happy colors, flat lighting, cartoon, low resolution, text",
    },
}


class StyleManager:
    """Manages indexing, loading and applying Krea2 visual style libraries."""

    def __init__(self):
        self._categories: Dict[str, str] = {}  # display_name -> file_path
        self._cache: Dict[str, List[dict]] = {}
        self._scan_directories()

    def _scan_directories(self):
        self._categories.clear()
        self._cache.clear()
        for base_path in _STYLE_SEARCH_PATHS:
            if os.path.isdir(base_path):
                try:
                    for fname in sorted(os.listdir(base_path)):
                        if fname.lower().endswith(".json"):
                            clean_name = os.path.splitext(fname)[0]
                            # Clean up common prefixes for cleaner UI display
                            display_name = clean_name.replace("Krea2_moodboard_", "").replace("krea2_397styles-", "")
                            self._categories[display_name] = os.path.join(base_path, fname)
                except Exception as e:
                    log.warning("掃描風格目錄失敗 %s: %s", base_path, e)

        log.info("StyleManager 成功索引 %d 個外卡風格庫", len(self._categories))

    def get_category_list(self) -> List[str]:
        builtin_names = list(_BUILTIN_STYLES.keys())
        scanned_names = [f"📁 {k}" for k in self._categories.keys()]
        return ["Auto (自動匹配故事題材風格)", "None (不加風格前綴)"] + builtin_names + scanned_names

    def get_style_entry(self, category_display: str) -> Optional[dict]:
        """Returns prompt template and negative prompt for the selected category."""
        if category_display in ("None (不加風格前綴)", "Auto (自動匹配故事題材風格)"):
            return None

        if category_display in _BUILTIN_STYLES:
            return _BUILTIN_STYLES[category_display]

        # Check scanned categories
        clean_key = category_display.replace("📁 ", "").strip()
        if clean_key in self._categories:
            file_path = self._categories[clean_key]
            if clean_key not in self._cache:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._cache[clean_key] = json.load(f)
                except Exception as e:
                    log.warning("讀取風格檔案失敗 %s: %s", file_path, e)
                    return None

            items = self._cache.get(clean_key, [])
            if items:
                # Return the primary/first style item in this category file
                return items[0]

        return None

    def apply_style(
        self,
        subject_prompt: str,
        style_choice: str = "Auto (自動匹配故事題材風格)",
        default_suffix: str = "",
    ) -> Tuple[str, str]:
        """Applies style formatting to subject_prompt.

        Returns: (final_positive_prompt, final_negative_prompt)
        """
        entry = self.get_style_entry(style_choice)
        if not entry:
            # Fallback to standard cinematic suffix
            suffix = default_suffix.strip() if default_suffix.strip() else "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography"
            pos = f"{subject_prompt}，{suffix}, absolutely no text, no watermarks"
            neg = "ugly, deformed, disfigured, poor anatomy, bad hands, missing fingers, extra limbs, low quality, blurry, text, watermark, logo"
            return pos, neg

        template = entry.get("prompt", "")
        neg = entry.get("negative_prompt", "") or "ugly, deformed, disfigured, poor anatomy, bad hands, missing fingers, extra limbs, low quality, blurry, text, watermark, logo"

        if "Subject:{prompt}" in template or "{prompt}" in template:
            pos = template.replace("Subject:{prompt}", f"Subject:{subject_prompt}").replace("{prompt}", subject_prompt)
        elif "Subject:" in template:
            pos = f"{template} {subject_prompt}"
        else:
            pos = f"{template}，[{subject_prompt}]"

        pos = f"{pos}, absolutely no text, no watermarks"
        return pos, neg


# Global instance
style_manager = StyleManager()
