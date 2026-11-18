"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues = []
    lf_cfg = cfg["label_format"]
    overflow_tol = lf_cfg["overflow_tol"]
    min_box_px = lf_cfg["min_box_px"]
    max_box_frac = lf_cfg["max_box_frac"]
    dup_box_iou = lf_cfg["dup_box_iou"]
    n_classes = len(ds.classes)

    for p in ds.image_files():
        stem = p.stem
        lines = ds.read_label_lines(stem)
        if lines is None:
            continue

        size = ds.image_size(stem)
        valid_prev_boxes = []  # list of (c, (cx, cy, w, h), line_no)

        for line_no, text in lines:
            try:
                c, cx, cy, w, h = parse_yolo_line(text)
            except ValueError as e:
                issues.append(Issue("label_format", ERROR, "BAD_FORMAT", stem, f"sai định dạng: {e}", line=line_no))
                continue

            if c < 0 or c >= n_classes:
                issues.append(Issue("label_format", ERROR, "BAD_CLASS_ID", stem, f"id lớp {c} không hợp lệ (0..{n_classes-1})", line=line_no))
                continue

            if w <= 0 or h <= 0:
                issues.append(Issue("label_format", ERROR, "BOX_ZERO", stem, f"kích thước không dương: w={w}, h={h}", line=line_no))
                continue

            x1 = cx - w / 2.0
            x2 = cx + w / 2.0
            y1 = cy - h / 2.0
            y2 = cy + h / 2.0
            overflow = max(0.0, -x1, x2 - 1.0, -y1, y2 - 1.0)
            if overflow > overflow_tol:
                issues.append(Issue("label_format", ERROR, "BOX_OUT_OF_IMAGE", stem, f"box tràn ảnh {overflow:.4f} > {overflow_tol}", line=line_no, extra={"overflow": overflow}))

            box = (cx, cy, w, h)
            # DUP_BOX: cùng lớp với một dòng trước đó và IoU > dup_box_iou
            for prev_c, prev_box, _ in valid_prev_boxes:
                if prev_c == c and iou_xywh(box, prev_box) > dup_box_iou:
                    issues.append(Issue("label_format", ERROR, "DUP_BOX", stem, "trùng box với dòng trước", line=line_no))
                    break

            valid_prev_boxes.append((c, box, line_no))

            # BOX_TINY
            if size:
                W, H = size
                short_side = min(w * W, h * H)
                if short_side < min_box_px:
                    issues.append(Issue("label_format", WARN, "BOX_TINY", stem, f"cạnh ngắn {short_side:.1f}px < {min_box_px}px", line=line_no))

            # BOX_HUGE
            if w * h > max_box_frac:
                issues.append(Issue("label_format", WARN, "BOX_HUGE", stem, f"diện tích {w*h:.3f} > {max_box_frac}", line=line_no))

    return issues
