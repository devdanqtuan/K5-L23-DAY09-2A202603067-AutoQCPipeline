"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg["second_opinion"]
    conf_thresh = so_cfg["conf"]
    min_area_px = so_cfg["min_area_px"]
    fp_conf = so_cfg["fp_conf"]
    iou_missing = so_cfg["iou_missing"]
    iou_match = so_cfg["iou_match"]
    iou_loose = so_cfg["iou_loose"]

    issues = []

    for p in ds.image_files():
        stem = p.stem
        # Bỏ qua ảnh không có trong preds hoặc không có file nhãn
        if stem not in preds or not ds.label_path(stem).exists():
            continue

        all_preds = preds[stem]
        size = ds.image_size(stem)
        W, H = size if size else (640, 640)

        # 1. Lọc dự đoán có conf >= conf VÀ diện tích px >= min_area_px
        filtered_preds = [
            r for r in all_preds
            if r[1] >= conf_thresh and (r[4] * W) * (r[5] * H) >= min_area_px
        ]

        valid_boxes = ds.valid_boxes(stem)

        # Duyệt từng dự đoán theo thứ tự trong preds[stem]
        for r in filtered_preds:
            r_cls = int(r[0])
            r_conf = float(r[1])
            r_box = (r[2], r[3], r[4], r[5])

            cands = []
            for l_box_info in valid_boxes:
                l_cls = int(l_box_info[0])
                l_box = (l_box_info[1], l_box_info[2], l_box_info[3], l_box_info[4])
                iou = iou_xywh(r_box, l_box)
                if iou >= iou_missing:
                    cands.append((l_cls, l_box, iou))

            if not cands:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_MISSING", stem,
                    f"model thấy {ds.classes[r_cls]} (conf {r_conf:.2f}) nhưng nhãn thiếu",
                    line=None,
                    extra={"conf": r_conf, "class": r_cls}
                ))
            else:
                same_cands = [c for c in cands if c[0] == r_cls]
                if same_cands:
                    best_same = max(same_cands, key=lambda c: c[2])
                    if best_same[2] < iou_loose:
                        issues.append(Issue(
                            "second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                            f"đúng lớp {ds.classes[r_cls]} nhưng box lỏng (IoU {best_same[2]:.2f} < {iou_loose})",
                            line=None,
                            extra={"conf": r_conf, "iou": round(best_same[2], 3), "class": r_cls}
                        ))
                else:
                    diff_cands = [c for c in cands if c[0] != r_cls]
                    best_diff = max(diff_cands, key=lambda c: c[2])
                    if best_diff[2] >= iou_match:
                        issues.append(Issue(
                            "second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                            f"vị trí khớp (IoU {best_diff[2]:.2f}) nhưng khác lớp: model={ds.classes[r_cls]} vs nhãn={ds.classes[best_diff[0]]}",
                            line=None,
                            extra={"conf": r_conf, "iou": round(best_diff[2], 3), "pred_class": r_cls, "label_class": best_diff[0]}
                        ))

        # 2. Kiểm tra POSSIBLE_FALSE_POS cho từng dòng nhãn hợp lệ
        fp_preds = [r for r in all_preds if r[1] >= fp_conf]
        raw_lines = ds.read_label_lines(stem) or []
        for line_no, text in raw_lines:
            try:
                c, cx, cy, w, h = parse_yolo_line(text)
            except ValueError:
                continue
            if not (0 <= c < len(ds.classes)):
                continue

            l_box = (cx, cy, w, h)
            # Nếu IoU với MỌI dự đoán (conf >= fp_conf) đều < iou_missing
            matches_any = False
            for r in fp_preds:
                r_box = (r[2], r[3], r[4], r[5])
                if iou_xywh(l_box, r_box) >= iou_missing:
                    matches_any = True
                    break

            if not matches_any:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                    f"box nhãn không khớp dự đoán nào của model (conf >= {fp_conf})",
                    line=line_no,
                    extra={"class": c}
                ))

    return issues
