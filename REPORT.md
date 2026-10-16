# REPORT — Lab Day 12

> Điền **bằng lời và số liệu của chính bạn** (lấy từ màn hình và từ `evidence/*.json`). Mỗi câu 4–8 dòng là đủ. Số không có trong bằng chứng của bạn sẽ bị trừ điểm. Báo cáo công khai trên GitHub; giảng viên đối chiếu với `evidence/` và với bài của các bạn khác.

| | |
|---|---|
| Họ và tên | Phạm Hoàng Anh Khôi |
| MSSV (đúng bằng `--student-id` bạn đã chạy) | 2A202602404 |
| GitHub | anhkhoi130605 |
| Seed chia dữ liệu / seed mô hình (xem `evidence/closedloop.json`, mục `student`) | 5760 / 7490 |
| Số seed huấn luyện bạn dùng (`--seeds`) | 5 |

## Kết quả cuối

Điền từ `evidence/closedloop.json`, `openloop.json`, `gate.json` (cho mỗi mô hình học, lấy **dải qua các seed**).

| Bộ điều khiển | L2 vòng hở (m) | Va chạm vòng kín trên log (%) | Quyết định cổng |
|---|---|---|---|
| constant-velocity | 1.235 | 19.3 | BLOCK |
| IDM | 1.508 | 0.1 | (baseline) |
| EgoMLP | 0.755 ± 0.002 | 15.3 .. 27.3 | BLOCK |
| PercMLP | 0.613 ± 0.002 | 0.4 .. 1.6 | BLOCK |
| PercMLP+ (sau khi sửa) | 0.796 ± 0.010 | 0.1 .. 0.2 | RELEASE |

## Câu 1 · Dữ liệu
Bước 0 bạn phát hiện những vấn đề gì ở dữ liệu? Vì sao không dùng cột `Acc_LV`, và bạn thay bằng gì? Bao nhiêu quỹ đạo bị loại vì trùng, và vì sao chia theo quỹ đạo?

Ở bước 0, qua `evidence/data_audit.json`, tôi phát hiện ba vấn đề then chốt: (1) Cột `Acc_LV` (gia tốc xe dẫn) có tương quan với đạo hàm vận tốc (`acc_lead_column_corr_with_dv_dt`) chỉ là 0.0454, gần như bằng 0 (trong khi của xe theo sau là 0.9291), cho thấy cảm biến đo gia tốc xe dẫn bị nhiễu nặng hoặc ghi sai giá trị. Do đó ta không thể dùng `Acc_LV` mà phải thay bằng đạo hàm bậc nhất của vận tốc `Speed_LV` đã được làm mượt qua bộ lọc (`lead_decel_smoothed`). (2) Có 383 quỹ đạo trùng khớp hoàn toàn (`exact_duplicates_removed` = 383, từ 9993 còn 9610 quỹ đạo) nằm ở các ID cách xa nhau; nếu không lọc bỏ, chúng sẽ gây rò rỉ dữ liệu (data leakage) nghiêm trọng giữa tập train và test. (3) Dữ liệu bắt buộc phải chia theo quỹ đạo (trajectory) thay vì theo từng khung hình (frame), bởi vì các khung hình trong cùng một quỹ đạo có tương quan thời gian rất cao (temporal autocorrelation). Nếu chia theo khung hình ngẫu nhiên, mô hình chỉ việc "học vẹt" nội suy giữa các khung liền kề, làm mất đi khả năng đánh giá độ tổng quát hóa trên các hành trình mới.

## Câu 2 · Phát lại
Bản refactor float32 khác bit ở bao nhiêu đoạn, vượt dung sai ở bao nhiêu? Thay đổi AEB làm lệch bao nhiêu đoạn, và vì sao lệch ở đúng những khung đó (mở một đoạn ra xem)? Phát theo thời gian thật làm lộ ra điều gì mà phát nhanh nhất che đi?

Từ `evidence/replay.json`, bản refactor float32 khác bit ở toàn bộ 600/600 đoạn (`not_bit_identical` = 600) do hiện tượng làm tròn số thực dấu phẩy động và tính chất phép cộng float32 không có tính kết hợp. Tuy nhiên, 0 đoạn nào vượt dung sai (`differ_beyond_tol` = 0) với ngưỡng `atol=1e-3, rtol=1e-3` (độ lệch tuyệt đối lớn nhất `max_abs_diff` chỉ là 0.000122 m/s²), khẳng định bản refactor hoạt động hoàn toàn chính xác về mặt kỹ thuật. Khi thay đổi chức năng phanh khẩn cấp AEB, chỉ có đúng 11/600 đoạn bị lệch vượt dung sai (`differ_beyond_tol` = 11, ví dụ các đoạn 77, 124, 168, 245, 308) với `max_abs_diff` đạt 1.454 m/s². Khi mở đoạn 124 ra kiểm tra, sự sai khác chỉ xuất hiện ở các khung hình có TTC < 1.5 s và xe đang tiến gần (`closing > 0`), nơi thuật toán AEB chủ động can thiệp phanh bổ sung để tránh va chạm; các khung lái xe bình thường khác vẫn giữ nguyên lệnh điều khiển. Cuối cùng, việc phát lại theo thời gian thực (`realtime`) làm lộ ra 577 khung hình bị rớt (`dropped` = 577) và 583 khung hình bị trễ hạn (`late` = 583), gây lệch 377 đoạn vượt dung sai. Trong khi đó, chế độ phát nhanh nhất (`fastest`) giả định việc tính toán và truyền tin diễn ra tức thời (zero latency), do đó che giấu hoàn toàn 0 late / 0 dropped, tạo ra ảo tưởng sai lệch về độ tin cậy của thuật toán.

## Câu 3 · Kịch bản
Lưới của bạn (tốc độ cruise, giới hạn khoảng cách, số ô): bao nhiêu % ô **không ai tránh được**? Độ trễ phản ứng 0 → 0,6 s làm vùng đâm của IDM tăng bao nhiêu? Log có phủ vùng khó không? (dẫn giới hạn phanh mạnh nhất của người lái trong log, và phần lưới đòi hỏi hơn thế)

Lưới kiểm thử kịch bản cắt vào (`evidence/scenarios.json`) được thiết lập ở tốc độ cruise 10.0 m/s, cự ly khoảng cách 2.76 m – 59.31 m, tốc độ tiến gần 0.0 – 10.0 m/s với tổng cộng 2700 ô lưới. Tại độ trễ phản ứng `t_react = 0.0 s`, có 0.96% số ô là bất khả thi về mặt vật lý (`unavoidable`). Khi độ trễ phản ứng tăng lên 0.6 s, tỷ lệ ô không ai tránh được tăng vọt lên 5.15% (tức tăng thêm 4.19% diện tích lưới). Đối với bộ điều khiển IDM, tỷ lệ va chạm trên lưới ở trễ 0.0 s là 0.96% và ở trễ 0.6 s là 5.15%, trùng khớp 100% với biên bất khả thi lý thuyết (`attributable_area` = 0.0%). Điều này chứng minh IDM không mắc bất kỳ sai lầm nào có thể tránh được; vùng đâm tăng thêm hoàn toàn là do giới hạn vật lý khi phản ứng bị chậm trễ. Về độ bao phủ, dữ liệu log thực tế không bao phủ được các tình huống ngặt nghèo: giới hạn phanh gấp của người lái trong log ở percentile 99.9 chỉ là 3.62 m/s² (trung vị phanh là 2.53 m/s²), trong khi lưới kiểm thử có tới 5.22% số ô đòi hỏi gia tốc hãm vượt quá giới hạn này. 614 sự kiện phanh khai thác được từ log hầu hết chỉ là phanh êm dịu hàng ngày, không chứa các tình huống nguy kịch ở biên vật lý.

## Câu 4 · Vòng hở và vòng kín
Dán bảng L2 và tỷ lệ va chạm của bốn bộ điều khiển (kèm hạng ở mỗi cách chấm). Cặp nào đổi thứ tự? Vì sao IDM có L2 như vậy mà vẫn lái tốt? Vì sao EgoMLP có L2 tốt hơn constant-velocity mà vẫn đâm?

Bảng so sánh 4 bộ điều khiển (`evidence/closedloop.json`):
- PercMLP: L2 vòng hở = 0.613 m (Hạng 1) | Va chạm vòng kín = 1.1% (Hạng 2)
- EgoMLP: L2 vòng hở = 0.755 m (Hạng 2) | Va chạm vòng kín = 21.4% (Hạng 4)
- constant-velocity: L2 vòng hở = 1.235 m (Hạng 3) | Va chạm vòng kín = 19.3% (Hạng 3)
- IDM: L2 vòng hở = 1.508 m (Hạng 4) | Va chạm vòng kín = 0.1% (Hạng 1)

Có tới 4 cặp bị đảo thứ hạng giữa vòng hở và vòng kín: `('const-vel', 'IDM')`, `('const-vel', 'EgoMLP')`, `('IDM', 'EgoMLP')`, `('IDM', 'PercMLP')`. IDM có điểm L2 vòng hở kém nhất (1.508 m) vì nó là bộ điều khiển dựa trên quy tắc an toàn vật lý, không được tối ưu hóa để khớp từng chi tiết quỹ đạo ngẫu nhiên của con người; nhưng trong vòng kín nó lái tốt nhất (chỉ 0.1% va chạm) nhờ vòng lặp phản hồi khép kín (closed-loop feedback) liên tục điều chỉnh theo khoảng cách thực tế. Ngược lại, EgoMLP có L2 vòng hở tốt hơn nhiều so với constant-velocity (0.755 m vs 1.235 m) nhưng khi tự lái vòng kín lại đâm nhiều nhất (21.4% vs 19.3%). Lý do là EgoMLP hoàn toàn mù về nhận thức xung quanh (không quan sát `gap` và `v_lead`). Trong vòng kín, các sai số dự báo nhỏ tích lũy qua từng bước thời gian (compounding error) dẫn tới trôi dạt phân bố (distribution shift), khiến xe lao vào các trạng thái nguy hiểm mà không hề biết để phanh.

## Câu 5 · Một lần chạy chưa đủ
EgoMLP dao động bao nhiêu giữa các seed? Khoảng tin cậy Wilson nói gì? Nếu bạn chỉ chạy đúng một seed thì có thể báo kết quả nào, và vì sao điều đó nguy hiểm?

Kết quả từ `evidence/closedloop.json` cho thấy tỷ lệ va chạm của EgoMLP dao động rất lớn giữa các seed huấn luyện: từ 15.3% ở seed 7490 đến 27.3% ở seed 7491 (chênh lệch tới 12.0%). Khoảng tin cậy Wilson 95% ở seed xấu nhất là [25.7%, 28.9%] (với n = 2883 quỹ đạo, k = 786 vụ va chạm), hoàn toàn tách rời và không giao thoa với khoảng tin cậy ở seed tốt nhất [14.0%, 16.7%] (k = 441). Tương tự, PercMLP cũng dao động từ 0.4% (seed 7490, k = 12) đến 1.6% (seed 7492, k = 46), gấp 4 lần nhau. Nếu ta chỉ chạy duy nhất một seed, ta hoàn toàn có thể vô tình chọn trúng seed tốt nhất (15.3% cho EgoMLP hoặc 0.4% cho PercMLP) rồi báo cáo rằng mô hình hoạt động ổn định và an toàn. Điều này cực kỳ nguy hiểm trong công nghiệp xe tự hành, vì nó che giấu tính bất ổn định nội tại do khởi tạo trọng số ngẫu nhiên, dẫn đến rủi ro phát hành một mô hình kém an toàn ra thế giới thực mà không hề hay biết.

## Câu 6 · Tác nhân phản ứng
Dán bảng "xe sau phát lại" và "xe sau phản ứng". `T` bạn hiệu chỉnh là bao nhiêu, xe sau chân thực đến mức nào so với xe không phản ứng? Vì sao IDM bị tính "va chạm giả" khi xe sau chỉ phát lại, và điều này làm đổi kết luận về bộ điều khiển ra sao?

Từ `evidence/agents.json`, bảng so sánh tổng va chạm (kèm tỷ lệ đâm đuôi) tại `t_react = 0.6 s`:
- constant-velocity: Xe sau phát lại = 73.4% (đâm đuôi 0.0%) | Xe sau phản ứng = 73.4% (đâm đuôi 0.0%)
- IDM: Xe sau phát lại = 70.1% (đâm đuôi 64.9%) | Xe sau phản ứng = 5.1% (đâm đuôi 0.0%)
- EgoMLP: Xe sau phát lại = 75.4% (đâm đuôi 0.0%) | Xe sau phản ứng = 75.4% (đâm đuôi 0.0%)
- PercMLP: Xe sau phát lại = 77.9% (đâm đuôi 52.1%) | Xe sau phản ứng = 25.8% (đâm đuôi 0.0%)

Thông số thời khoảng cách an toàn `T` hiệu chỉnh tối ưu cho xe sau là 1.4 s, đạt khoảng cách phân bố Wasserstein W1 = 0.352 so với người lái thực tế (có median headway 1.87 s), chân thực hơn nhiều so với tác nhân không bao giờ phản ứng (W1 = 0.876). Khi xe sau chỉ là "băng phát lại" (open-loop replay), nó mù quáng di chuyển theo dữ liệu ghi hình cũ. Khi xe thử nghiệm (IDM) phát hiện tình huống nguy hiểm và phanh kịp thời, xe sau không hề biết để giảm tốc nên đâm thẳng vào đuôi xe thử nghiệm, tạo ra 64.9% "va chạm giả" từ phía sau. Khi chuyển sang môi trường xe sau biết phản ứng, 100% va chạm đuôi biến mất (0.0%). Nếu chỉ dùng môi trường phát lại ngây thơ, ta sẽ rút ra kết luận sai lầm rằng constant-velocity an toàn gần ngang IDM (73.4% vs 70.1%), trong khi thực tế constant-velocity không hề phanh và đâm nát đầu xe phía trước.

## Câu 7 · Cổng phát hành và sửa
Quy tắc nào chặn PercMLP và nguyên nhân gốc là gì (dẫn số)? Bạn sửa bằng gì và vì sao nó chữa đúng nguyên nhân? Sau khi qua cổng, PercMLP+ có **tốt hơn** IDM không? Nó có nên được phát hành không, và bạn đề xuất làm gì trước khi quyết định?

PercMLP bị cổng chặn ở 5/7 quy tắc: R2_closed_loop_logs (cận trên 95% là 2.12% > baseline 0.07% + 1%), R3_braking_slice (7.3%, cận trên 12.1% > baseline 0.6% + 5%), R4_scenario_grid (diện tích va chạm tránh được 20.67% > 2.0%), R5_seed_stability (dao động 0.4%..1.6%, chênh 1.2% > 1.0%), và R6_reactive_world (25.8% > baseline 5.1% + 2.0%). Hai nguyên nhân gốc: (1) Thiếu bao phủ kịch bản ngoài phân bố: log lái xe thông thường không chứa các ca cắt đầu gấp ở cự ly hẹp (gây trượt R4, R6). (2) Sai số tích lũy trong vòng kín (covariate shift): mô hình chỉ bắt chước trạng thái con người đi qua, khi bị lệch nhẹ không biết cách khôi phục lại (gây trượt R2, R3, R5). Tôi đã sửa bằng hai phương pháp kết hợp: (a) Bổ sung 196,840 cửa sổ từ 20,000 kịch bản cắt vào mô phỏng gắn nhãn IDM để lấp đầy điểm mù phân bố; (b) Áp dụng thuật toán DAgger qua 2 vòng lặp, cho mô hình tự lái trên 6,700 quỹ đạo huấn luyện, ghi lại các trạng thái nó tự rơi vào và gắn nhãn bằng dự báo của chuyên gia IDM. Sau khi sửa, PercMLP+ đã vượt qua cổng phát hành (`RELEASE`, R2 cận trên giảm về 0.45%, R4 diện tích giảm về 0.11%, R5 chênh lệch chỉ 0.1%). Tuy nhiên, PercMLP+ KHÔNG HỀ tốt hơn IDM (va chạm log 0.19% vs 0.07%, cắt vào 0.11% vs 0.0%), bởi vì nó học trực tiếp từ IDM nên về bản chất chỉ tiệm cận mức "không kém hơn" (non-inferior). Không nên phát hành ngay lập tức; cần kiểm thử thêm trên mô phỏng 3D tích hợp trễ cảm biến, kiểm tra độ bám đường thời tiết xấu và chạy trên bãi thử kín (proving ground) trước khi đưa ra quyết định thương mại.

## Câu 8 · Bài lab này không chứng minh được gì
Chọn **ít nhất ba** giới hạn quan trọng nhất đối với việc quyết định phát hành và giải thích vì sao mỗi cái làm kết luận của bạn kém chắc chắn. Điều gì cần làm tiếp để thu hẹp khoảng cách đến thế giới thật?

Ba giới hạn quan trọng nhất làm kết luận phát hành kém chắc chắn gồm: (1) Giả định chuyển động 1 chiều dọc (1D longitudinal motion): Bài lab chỉ xét tăng/giảm tốc trên một làn thẳng, bỏ qua hoàn toàn chuyển động ngang (lateral), đánh lái né vật cản (steering/swerving) và giới hạn ma sát cung tròn của lốp xe (friction circle). Trên thực tế, nhiều ca phanh khẩn cấp đòi hỏi chuyển làn hoặc kết hợp phanh - lái đồng thời. (2) Cảm biến và nhận thức quá lý tưởng: Mô hình nhận được khoảng cách và vận tốc tương đối hoàn hảo (hoặc chỉ thêm nhiễu Gaussian tĩnh), bỏ qua các lỗi sống còn của hệ thống perception thực tế như hiện tượng che khuất (occlusion), nhận diện nhầm vật cản ảo (phantom/ghost braking), trễ pipeline xử lý camera/LiDAR 100–200 ms, và mất dấu vật thể (tracking loss). (3) Chuyên gia IDM không phải là chân lý tối thượng: PercMLP+ học hoàn toàn từ luật IDM, do đó nó sẽ kế thừa mọi giả định đơn giản hóa của IDM (như gia tốc không đổi, không dự đoán ý định con người, không xử lý hành vi xe máy lạng lách hay người đi bộ cắt ngang). Để thu hẹp khoảng cách đến thế giới thật, bước tiếp theo cần làm là: đưa mô hình vào các bộ mô phỏng 3D vật lý độ trung thực cao (như CARLA hoặc rFpro) với mô phỏng cảm biến quang học chi tiết; thực hiện kiểm thử phần cứng trong vòng lặp (Hardware-in-the-Loop - HIL); và triển khai thử nghiệm thực địa trên sa hình khép kín với tài xế an toàn giám sát liên tục.
