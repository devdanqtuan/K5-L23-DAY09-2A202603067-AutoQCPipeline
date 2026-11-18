"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |
"""
from collections import defaultdict
from pathlib import Path

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {"DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
DROP_LINE_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def fix(ds, issues, cfg):
    fixes = []
    # Chỉ xử lý các lỗi có severity ERROR
    err_issues = [i for i in issues if i.severity == ERROR]
    if not err_issues:
        return fixes

    # 1. BAD_CLASS_NAME -> sửa data.yaml
    bad_class_issues = [i for i in err_issues if i.code == "BAD_CLASS_NAME"]
    if bad_class_issues:
        yaml_path = ds.yaml_path
        before_names = ds.yaml_names()
        classes = list(cfg["classes"])
        data = {}
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        data["names"] = classes
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        fixes.append({
            "image": "data.yaml",
            "line": "",
            "action": "rename_classes",
            "before": str(before_names),
            "after": str(classes),
        })

    # 2. Xoá ảnh hỏng / trùng / rò rỉ
    removed_images = set()
    for i in err_issues:
        if i.code in REMOVE_IMAGE_CODES and i.image not in removed_images:
            removed_images.add(i.image)
            p_img = ds.image_path(i.image)
            if p_img and p_img.exists():
                p_img.unlink()
            p_lbl = ds.label_path(i.image)
            if p_lbl and p_lbl.exists():
                p_lbl.unlink()
            fixes.append({
                "image": i.image,
                "line": "",
                "action": "remove_image",
                "before": "có trong dataset",
                "after": "đã xóa",
            })

    # 3. MISSING_LABEL_FILE -> ghi nhận needs_label (không tạo file)
    for i in err_issues:
        if i.code == "MISSING_LABEL_FILE" and i.image not in removed_images:
            fixes.append({
                "image": i.image,
                "line": "",
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán",
            })

    # 4. Sửa các lỗi dòng nhãn
    # Gom theo image stem
    file_issues = defaultdict(list)
    for i in err_issues:
        if i.image in removed_images or i.image in ("data.yaml", "<dataset>"):
            continue
        if i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE":
            if i.line is not None:
                file_issues[i.image].append(i)

    for stem, stem_issues in file_issues.items():
        lbl_path = ds.label_path(stem)
        if not lbl_path.exists():
            continue

        raw_lines = lbl_path.read_text(encoding="utf-8").splitlines()
        n_lines = len(raw_lines)

        # Gom issue theo từng dòng gốc (1-based)
        line_to_issues = defaultdict(list)
        for iss in stem_issues:
            line_to_issues[iss.line].append(iss)

        drop_line_set = set()
        clip_line_dict = {}  # line_no -> (new_line_str, before_str)

        for line_no, l_issues in line_to_issues.items():
            if not (1 <= line_no <= n_lines):
                continue
            orig_text = raw_lines[line_no - 1]
            codes = {iss.code for iss in l_issues}

            # Nếu dòng có bất kỳ lỗi drop_line nào, drop_line luôn thắng
            if codes & DROP_LINE_CODES:
                drop_line_set.add(line_no)
            elif "BOX_OUT_OF_IMAGE" in codes:
                # Thử clip box
                try:
                    c, cx, cy, w, h = parse_yolo_line(orig_text)
                    x1 = cx - w / 2.0
                    x2 = cx + w / 2.0
                    y1 = cy - h / 2.0
                    y2 = cy + h / 2.0

                    nx1 = max(0.0, min(1.0, x1))
                    nx2 = max(0.0, min(1.0, x2))
                    ny1 = max(0.0, min(1.0, y1))
                    ny2 = max(0.0, min(1.0, y2))

                    nw = nx2 - nx1
                    nh = ny2 - ny1

                    if nw <= 1e-6 or nh <= 1e-6:
                        # Box nằm hẳn ngoài ảnh -> xoá dòng
                        drop_line_set.add(line_no)
                    else:
                        ncx = (nx1 + nx2) / 2.0
                        ncy = (ny1 + ny2) / 2.0
                        clipped_str = f"{c} {ncx:.6f} {ncy:.6f} {nw:.6f} {nh:.6f}"
                        clip_line_dict[line_no] = (clipped_str, orig_text)
                except ValueError:
                    drop_line_set.add(line_no)

        # Ghi các bản ghi fix theo thứ tự dòng
        all_touched_lines = sorted(drop_line_set | set(clip_line_dict.keys()))
        for line_no in all_touched_lines:
            orig_text = raw_lines[line_no - 1]
            if line_no in drop_line_set:
                fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "drop_line",
                    "before": orig_text,
                    "after": "(đã xoá)",
                })
            elif line_no in clip_line_dict:
                clipped_str, _ = clip_line_dict[line_no]
                fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "clip_box",
                    "before": orig_text,
                    "after": clipped_str,
                })

        # Tạo nội dung file mới
        new_lines = []
        for line_no, orig_text in enumerate(raw_lines, 1):
            if line_no in drop_line_set:
                continue
            elif line_no in clip_line_dict:
                new_lines.append(clip_line_dict[line_no][0])
            else:
                new_lines.append(orig_text)

        lbl_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")

    return fixes
