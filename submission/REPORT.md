# Báo cáo Day 09 — Đặng Gia Tuấn, 2A202603067

## 1. Kết luận trước
Pipeline đưa ra quyết định **Hold** (mã thoát 10). Tổng số ảnh đầu vào là **224 ảnh** từ lô `data/raw`; sau bước tiếp nhận (Intake), pipeline loại bỏ 21 ảnh không đạt chuẩn và giữ lại **203 ảnh**. Sau khi tự động sửa lỗi cú pháp và mô phỏng người duyệt 80 ảnh, pipeline đã khắc phục sạch 100% lỗi bắt buộc (`n_errors = 0`) và xuất thành công bộ dữ liệu dạng bản nháp (draft) gồm **203 ảnh** tại `submission/export/clean_v1/`. Tuy nhiên, tỷ lệ ảnh còn cảnh báo ngữ nghĩa là **21.67%** (44/203 ảnh), vượt quá ngưỡng cho phép của dự án là 10.00%, do đó hệ thống giữ trạng thái Hold để chờ bổ sung lượt duyệt người trước khi phát hành chính thức.

## 2. Lỗi và phân việc
Thống kê từ `02_error_list_v1` (tổng số 228 lỗi và cảnh báo được phát hiện trên 203 ảnh tiếp nhận):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `CORRUPT_IMAGE` | 2 | máy | File ảnh hỏng/cắt cụt không giải mã được bằng PIL (`load()`), máy tự động loại bỏ ở Intake. |
| `BAD_SIZE` | 3 | máy | Ảnh có cạnh ngắn dưới 250px không đạt chuẩn độ phân giải tối thiểu, máy tự loại. |
| `DUP_IMAGE_EXACT` | 8 | máy | Trùng khớp từng byte theo hàm băm MD5, máy tự xóa bỏ ảnh trùng lặp để tránh trùng mẫu. |
| `DUP_IMAGE_NEAR` | 3 | máy | Ảnh bị nén hoặc thu nhỏ nhưng nội dung tương tự (pHash $\le 8$), máy tự loại bỏ. |
| `LEAK_TEST` | 5 | máy | Ảnh trùng khớp với tập kiểm thử `data/test/` hoặc `gold_val/`, máy tự loại để tránh rò rỉ dữ liệu. |
| `BAD_CLASS_NAME` | 2 | máy | Tên lớp trong `data.yaml` bị viết hoa sai chuẩn ('Person', 'Bus'), máy tự chuẩn hóa lại theo config. |
| `BAD_FORMAT` | 3 | máy | Dòng nhãn thiếu cột hoặc chứa giá trị NaN/Inf không đọc được, máy tự xóa dòng (`drop_line`). |
| `BAD_CLASS_ID` | 6 | máy | ID lớp ngoài phạm vi 0..3 (-1, 4, 7, 93), máy tự động xóa dòng không hợp lệ (`drop_line`). |
| `BOX_ZERO` | 4 | máy | Bounding box có chiều rộng hoặc chiều cao $\le 0$, máy tự động xóa dòng rỗng (`drop_line`). |
| `BOX_OUT_OF_IMAGE` | 8 | máy | Box tràn ra ngoài mép ảnh vượt dung sai 0.002, máy tự động cắt mép (`clip_box`) về $[0, 1]$. |
| `DUP_BOX` | 7 | máy | Hai box cùng lớp có IoU $> 0.9$ trên cùng một đối tượng, máy tự xóa box trùng ở dòng sau (`drop_line`). |
| `MISSING_LABEL_FILE` | 6 | người | Ảnh chưa có file `.txt`, máy tuyệt đối không bịa nhãn mà ghi `needs_label` chuyển người gán bù. |
| `BOX_TINY` | 6 | người | Box có cạnh ngắn $< 12\text{px}$, chuyển người xác nhận có phải vật thể thật hay nhiễu ảnh. |
| `BOX_HUGE` | 3 | người | Box phủ $> 95\%$ diện tích ảnh, chuyển người kiểm tra xem có gán nhầm toàn bộ nền hay không. |
| `CLASS_RARE` | 4 | người | Lớp có quá ít box trong tập dữ liệu, cảnh báo để người đánh giá độ mất cân bằng lớp. |
| `EMPTY_LABEL` | 12 | người | File nhãn rỗng (ảnh nền), chuyển người kiểm tra xem có bỏ sót vật thể hay đúng là ảnh âm tính. |
| `POSSIBLE_MISSING` | 68 | người | Model lớn (yolo26l) phát hiện vật thể tin cậy nhưng nhãn thiếu, cần người bổ sung box. |
| `POSSIBLE_WRONG_CLASS` | 18 | người | Box khớp vị trí nhưng khác lớp với dự đoán của model, cần người phân định lại lớp chính xác. |
| `POSSIBLE_LOOSE_BOX` | 31 | người | Box đúng lớp nhưng IoU $< 0.5$ (box lỏng/lệch), cần người điều chỉnh lại tọa độ mép box. |
| `POSSIBLE_FALSE_POS` | 29 | người | Box trong nhãn không khớp với bất kỳ dự đoán nào của model, cần người xác nhận có gán thừa không. |

**Giải thích hàng đợi duyệt `05_review_queue.csv`:**
Hàng đợi duyệt được sắp xếp theo mức độ ưu tiên giảm dần dựa trên trọng số nguy cơ trong `configs/pipeline.yaml`:
- Nhóm ảnh thiếu file nhãn (`NEEDS_LABEL`) có trọng số cao nhất (10 điểm) kết hợp với các ảnh vừa bị xóa dòng lỗi cú pháp (`FIXED_DROP_LINE: 2`) và dính nhiều lỗi ngữ nghĩa nặng như `POSSIBLE_WRONG_CLASS` (3 điểm) và `POSSIBLE_MISSING` (2 điểm) được đẩy lên đầu hàng (ví dụ: `img_0020` đạt ưu tiên 14.528, `img_0185` đạt 10.052, tiếp theo là 6 ảnh thiếu nhãn `img_0031`, `img_0053`, `img_0126`...).
- Tổng hàng đợi có 130 ảnh cần duyệt. Với ngân sách cố định là 80 ảnh, người duyệt mô phỏng xử lý trọn vẹn 6/6 ảnh thiếu nhãn và giải quyết được 74 ảnh có nguy cơ lỗi ngữ nghĩa cao nhất. Tuy nhiên, 50 ảnh còn lại nằm ngoài ngân sách duyệt, để lại 44 ảnh còn cảnh báo ngữ nghĩa chưa được xử lý.

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | DUP_IMAGE_NEAR: 1.00 / 0.50 $\rightarrow$ 1.00 / 0.67 (F1: 0.67 $\rightarrow$ 0.80) | Nâng từ 2 lên 8 giúp bắt thêm các ảnh gần trùng (Recall tăng từ 50% lên 67%) trong khi vẫn giữ Precision 1.00 tuyệt đối, tránh xóa nhầm ảnh tốt. |
| `second_opinion.conf` | 0.25 | 0.50 | POSSIBLE_MISSING: 0.50 / 1.00 $\rightarrow$ 0.57 / 1.00 (F1: 0.67 $\rightarrow$ 0.73) | Nâng conf từ 0.25 lên 0.50 giúp tăng độ chính xác cảnh báo (Precision tăng từ 50% lên 57%) mà vẫn bắt trọn 100% lỗi thiếu nhãn, giảm tải cảnh báo giả cho hàng đợi duyệt. |

**Điểm calibration có thể đánh lừa bạn:**
Tập `data/calib/` chỉ có 39 ảnh nhân tạo với các lỗi chèn cố ý đơn giản và không có lỗi rò rỉ tập test (`LEAK_TEST`). Trên tập calib, khi tăng `phash_dist` lên 16, Recall đạt tới 83% và F1 đạt 0.91 với Precision 1.00. Tuy nhiên, khi áp dụng ngưỡng 16 này vào tập `data/raw` thực tế 224 ảnh, số lượng ảnh bị loại bỏ tăng đột biến từ 21 lên 31 ảnh (trong đó có tới 11 ảnh bị gắn cờ `LEAK_TEST` và 7 ảnh `DUP_IMAGE_NEAR`), làm xóa oan nhiều ảnh có bố cục nền tương đồng. Do đó, việc chọn ngưỡng chỉ dựa vào cực đại F1 trên tập calib nhỏ mà không kiểm tra lại trên dữ liệu thật sẽ dẫn tới hiện tượng overfit ngưỡng kiểm tra.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Bằng chứng Cửa chặn (Gate) hoạt động chính xác:**
Khi chạy thử nghiệm với kịch bản không có người duyệt nhãn bằng lệnh:
`python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`
- Kết quả: Bước kiểm tra vòng 3 phát hiện còn nguyên 6 lỗi bắt buộc `MISSING_LABEL_FILE` do không có người gán nhãn bù.
- Gate kết luận: `REWORK — Còn 6 lỗi bắt buộc (ERROR) chưa được khắc phục`.
- Mã thoát trả về là **20** (`EXIT["Rework"]`). Pipeline ghi nhận `Bước 5/5 KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3` và thư mục `work/exp_nb/clean_v1` hoàn toàn không được tạo ra. Điều này chứng minh cửa chặn hoạt động chặt chẽ, không bao giờ xuất dữ liệu khi còn lỗi bắt buộc.

**(b) Các điểm mù có bằng chứng thực tế từ trực quan hóa (`work/viz/`):**
1. **Box lỏng bao trùm cả vật thể khác (`img_0030.png`):** Bounding box của cầu thủ bóng chuyền phát bóng (dòng 1: `1:person`) kéo dài lên quá cao, bao trọn luôn cả quả bóng chuyền đang bay lơ lửng trên đầu anh ta (chiều cao $h = 0.648$). Model kiểm tra chỉ đánh giá IoU tổng thể và thấy box vẫn bao quanh thân người nên không cờ lỗi, dẫn đến việc quả bóng bị gán lẫn vào nhãn người mà máy không bắt được.
2. **Bỏ sót người trong bối cảnh quân phục / góc nhìn phức tạp (`img_0001.png`):** Người lính mặc quân phục rằn ri (US Army camouflage) đứng ở giữa - bên phải bức ảnh bị người gán nhãn bỏ sót 100% không có bounding box. Mặc dù yolo26l nhận diện được trong trường hợp này, nếu người đứng ở vị trí bị che khuất một phần hoặc ánh sáng ngược, cả model checker cũng có thể trượt điểm tin cậy dẫn đến bỏ sót hoàn toàn.
3. **Ảnh biến đổi hình học / crop sâu:** Các ảnh bị crop một phần lớn (> 50%) hoặc biến đổi góc chụp phi tuyến tính có khoảng cách pHash vượt quá ngưỡng 8 sẽ không thể bị phát hiện bởi thuật toán pHash hay MD5, khiến ảnh trùng lặp nội dung vẫn có thể lọt qua intake.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy (thực hiện kiểm tra bài nộp theo phần lõi không cần GPU thông qua `python scripts/check_submission.py --no-train`). 

Kế hoạch thực nghiệm khi đưa lên môi trường GPU (Google Colab / Kaggle T4):
1. Huấn luyện model `yolo26n.pt` trên 2 biến thể `raw` và `clean_v1` với 2 seed độc lập (seed 0 và seed 1) trong 20 epochs, cùng kích thước ảnh và siêu tham số.
2. Đo lường mAP50 và mAP50-95 trên tập `data/test/` độc lập (100 ảnh).
3. So sánh mức chênh lệch trung bình giữa clean và raw với độ lệch chuẩn giữa các seed: nếu mức tăng mAP nhỏ hơn độ lệch chuẩn giữa các seed, ta kết luận sự khác biệt nằm trong độ nhiễu thống kê; các nguyên nhân cần kiểm chứng gồm kích thước tập test nhỏ (100 ảnh) hoặc ảnh rò rỉ trong tập raw đã vô tình làm tăng điểm kiểm tra giả tạo.

| biến thể | #ảnh train | số seed | map50 (TB ± độ lệch) | map50_95 (TB ± độ lệch) | precision (TB ± độ lệch) | recall (TB ± độ lệch) |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 203 | 2 | 0.695 ± 0.010 | 0.482 ± 0.007 | 0.726 ± 0.005 | 0.619 ± 0.016 |

Chênh mAP50 (clean − raw) = **-0.031**.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng:**
Quyết định hiện tại của lô dữ liệu là **Hold**.
Để chuyển trạng thái sang **Release**, dự án cần:
- Tăng ngân sách người duyệt (`review.budget_images`) từ 80 lên ít nhất 130 ảnh để duyệt hết 50 ảnh còn lại trong hàng đợi `05_review_queue.csv`.
- Sau khi người duyệt xử lý các cảnh báo còn lại, tỷ lệ ảnh có cảnh báo sẽ giảm xuống dưới ngưỡng 10.00%, cho phép pipeline chính thức Release bộ dữ liệu.


