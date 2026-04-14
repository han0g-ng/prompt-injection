1. Model phi3 mini chạy được số ít các lệnh thành công -> phân tích lý do (điểm nó hơn ở các model nhỏ khác). Tuy nhiên vẫn có những câu bị tấn công thành công -> phân tích lý do -> chỉ ra thực chất chỉ cần 1 vài đoạn prompt bị tấn công thành công là đã nguy hiểm
2. Một số model mỏng nhẹ thì thậm chỉ yếu tới mức không biết phải thực hiện các câu lệnh làm rối trong prompt thế nào -> vô nghĩa
3. Mỗi model thì yếu theo một kiểu tấn công riêng -> tập trung phân tích làm rõ

4. Hiện label 1 đang chứa khoảng 980 dòng (dùng metaprompt cũ), label 2 thì khoảng 900 dòng

5. Dữ liệu chạy để trích ra các token không phải là key thường có tỉ lệ cao hơn các loại khác (ví dụ để lộ email, tiền lương dễ thành công hơn) -> tại sao thì hỏi gemini

