# -*- coding: utf-8 -*-
"""Storyboard & Character Sheet Splitter for Ultimate Director.

1. Splits 4-column Character Sheet (1536x1024) into:
   - face_closeup (高保真臉部特寫，第一欄)
   - body_front (正面全身，第二欄)
   - body_side (側面全身，第三欄)
   - body_back (背面全身，第四欄)
2. Splits multi-panel storyboard grids (2x2, 3x2, 3x3) into individual shot images.
"""
from __future__ import annotations

import re
import torch

def _grid_dims(layout: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(layout or ""), re.I)
    if match:
        return max(1, int(match.group(1))), max(1, int(match.group(2)))
    return 3, 2

def split_storyboard_grid(
    images: torch.Tensor | None, 
    layout: str = "3x2", 
    crop_strength: float = 1.0
) -> list[torch.Tensor]:
    """Splits a single storyboard grid image into a list of cell tensors [1, H, W, C]."""
    if images is None or images.shape[0] == 0:
        return []
    
    cols, rows = _grid_dims(layout)
    count = cols * rows
    
    if int(images.shape[0]) > 1:
        return [images[i : i + 1] for i in range(min(count, int(images.shape[0])))]

    source = images[:1]
    _, height, width, _ = source.shape
    strength = max(0.0, min(3.0, float(crop_strength)))
    result = []
    
    for index in range(count):
        col = index % cols
        row = index // cols
        x0 = int(round(col * width / cols))
        x1 = int(round((col + 1) * width / cols))
        y0 = int(round(row * height / rows))
        y1 = int(round((row + 1) * height / rows))
        
        inset_x = int(round((x1 - x0) * 0.015 * strength))
        inset_y = int(round((y1 - y0) * 0.015 * strength))
        if x1 - x0 > inset_x * 2 + 16:
            x0, x1 = x0 + inset_x, x1 - inset_x
        if y1 - y0 > inset_y * 2 + 16:
            y0, y1 = y0 + inset_y, y1 - inset_y
            
        result.append(source[:, y0:y1, x0:x1, :])
        
    return result


def split_character_sheet(
    image: torch.Tensor | None,
    crop_strength: float = 1.0,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Splits a 4-column Character Sheet (1536x1024) into 4 distinct views."""
    if image is None or image.shape[0] == 0:
        empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        return empty, empty, empty, empty

    source = image[:1]
    _, height, width, _ = source.shape
    cols = 4
    strength = max(0.0, min(3.0, float(crop_strength)))
    views = []

    for c in range(cols):
        x0 = int(round(c * width / cols))
        x1 = int(round((c + 1) * width / cols))
        y0 = 0
        y1 = height
        
        # Border crop to remove divider lines
        inset_x = int(round((x1 - x0) * 0.015 * strength))
        if x1 - x0 > inset_x * 2 + 16:
            x0, x1 = x0 + inset_x, x1 - inset_x
            
        views.append(source[:, y0:y1, x0:x1, :])

    return views[0], views[1], views[2], views[3]


class UltimateDirectorCharacterSheetSplitterNode:
    """Splits a 4-column Character Sheet into High-Resolution Face Closeup, Front, Side, and Back."""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_sheet_image": ("IMAGE", {"tooltip": "Krea2 / SD / Flux 生成的 4 欄橫向並列角色四視圖大圖。"}),
                "crop_border_strength": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 3.0,
                    "step": 0.1,
                    "tooltip": "邊框裁切力度（消除四欄分界線與邊緣雜色）。"
                }),
            }
        }
        
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("face_closeup", "body_front", "body_side", "body_back", "all_batch")
    FUNCTION = "split_char"
    CATEGORY = "UltimateDirector/Character"
    
    def split_char(self, character_sheet_image, crop_border_strength):
        face, front, side, back = split_character_sheet(character_sheet_image, crop_border_strength)
        all_batch = torch.cat([face, front, side, back], dim=0)
        return (face, front, side, back, all_batch)


class UltimateDirectorStoryboardGridNode:
    """Splits a multi-panel storyboard grid image into individual shot reference images."""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "storyboard_image": ("IMAGE", {"tooltip": "Krea2 / SD / Flux 生成的宮格故事板大圖。"}),
                "grid_layout": (["3x2 (6格)", "2x2 (4格)", "3x3 (9格)", "4x2 (8格)"], {
                    "default": "3x2 (6格)",
                    "tooltip": "故事板宮格排列格式。"
                }),
                "crop_border_strength": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 3.0,
                    "step": 0.1,
                    "tooltip": "邊框裁切力度（消除宮格分界線與縫隙雜邊）。"
                }),
            }
        }
        
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "INT")
    RETURN_NAMES = ("grid_batch", "pic_1", "pic_2", "pic_3", "pic_4", "pic_5", "pic_6", "cell_count")
    FUNCTION = "split_grid"
    CATEGORY = "UltimateDirector/Storyboard"
    
    def split_grid(self, storyboard_image, grid_layout, crop_border_strength):
        cells = split_storyboard_grid(storyboard_image, grid_layout, crop_border_strength)
        if not cells:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, empty, empty, empty, empty, empty, empty, 0)
            
        ref_h, ref_w = cells[0].shape[1], cells[0].shape[2]
        resized_cells = []
        for cell in cells:
            if cell.shape[1] != ref_h or cell.shape[2] != ref_w:
                perm = cell.permute(0, 3, 1, 2)
                resized = torch.nn.functional.interpolate(perm, size=(ref_h, ref_w), mode="bilinear", align_corners=False)
                resized_cells.append(resized.permute(0, 2, 3, 1))
            else:
                resized_cells.append(cell)
                
        batch = torch.cat(resized_cells, dim=0)
        
        def get_cell(idx):
            if idx < len(cells):
                return cells[idx]
            return cells[-1]
            
        p1 = get_cell(0)
        p2 = get_cell(1)
        p3 = get_cell(2)
        p4 = get_cell(3)
        p5 = get_cell(4)
        p6 = get_cell(5)
        
        return (batch, p1, p2, p3, p4, p5, p6, len(cells))
