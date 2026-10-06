# LoopGen Studio v0.9.0 — Full Video Localization

Bản dựng lại sạch theo đúng mục tiêu: **dịch nguyên video nguồn**, không cắt ngắn, không tự thêm hook/card, không biến video thành một Reel mới.

## Nguyên tắc v0.9

- Giữ nguyên hình ảnh, thời lượng và nhịp dựng của video nguồn.
- Lời nói: ASR tiếng Trung → dịch Việt ngắn gọn theo đúng slot thời gian → voice Việt.
- Chữ trên màn hình: OCR local theo timeline → track thành object → Gemini phân loại một lần/video.
- Chỉ dịch tên bài tập, hướng dẫn tư thế, cảnh báo/kỹ thuật và text fitness có nghĩa.
- Giữ nguyên số thứ tự, timer, rep counter (`01`, `00:30`, `3/10`...).
- Bỏ logo/watermark/hashtag, chữ trên chai/hộp/quần áo và subtitle hội thoại ở vùng đáy.
- Mỗi thời điểm tối đa 2 cụm chữ Việt; không tạo card AI ngoài nội dung gốc.
- Preserve source resolution/FPS để render nhanh hơn và gần bản dịch thủ công.
- Auto Pipeline chạy tuần tự một project nặng tại một thời điểm để tránh 3 video tranh CPU.
- Nút **Hủy & Xóa** hoạt động cả khi project đang chạy.

## Pipeline

1. ASR tiếng Trung
2. Dịch lời thoại
3. Localize chữ màn hình (OCR → track → classify/translate)
4. Tạo voice Việt
5. Dựng overlay text replacement
6. Render full video

## Cài trên macOS

Yêu cầu: Python 3.11+, FFmpeg.

```bash
chmod +x setup_loopgen.command run_loopgen.command
./setup_loopgen.command
./run_loopgen.command
```

Mở `http://127.0.0.1:8765`.

## Tốc độ

Khác các bản v0.8.x, Gemini không còn được gọi trên từng frame. RapidOCR chạy local ~1 fps để bắt onset chữ, sau đó các detection được track/merge và **toàn bộ track được gửi lên Gemini trong 1 batch**. Việc này giảm mạnh network latency/quota và vẫn giữ timing chữ trong khoảng ~0.5 giây.

## Git branch

Bản v0.9 được xây trên branch `loopgen-v0.9` của repo này.
