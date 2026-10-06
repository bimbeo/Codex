# LoopGen Studio v0.9.0 — Reference-Guided Full Localization

Đây là rewrite kiến trúc sau khi đối chiếu các video gốc với bản dịch thủ công.

## Khác v0.8.x

- Không còn Content Plan/hook/card/CTA trong pipeline mặc định.
- Không cắt ngắn video: output giữ nguyên full timeline nguồn.
- Không ép 1080×1920 nếu nguồn đã có resolution phù hợp; preserve source resolution/FPS để nhanh và gần bản thủ công.
- OCR không gửi frame liên tục lên Gemini. RapidOCR chạy local 1 fps, detection được track thành text object, sau đó semantic classify + dịch trong **một batch Gemini/video**.
- Subtitle hội thoại Trung ở đáy không được burn lại; lời nói đã được xử lý bởi voice Việt.
- Timer/số thứ tự thuần số luôn giữ nguyên.
- Logo/watermark/hashtag/non-Chinese bị lọc trước Gemini.
- Renderer tối đa 2 text Việt cùng lúc, ưu tiên graphic lớn/ổn định, chống OCR fragment chồng nhau.
- Text Việt bám vùng text gốc bằng replacement box thay vì card rải rác trên màn hình.
- Voice dùng Edge TTS tiếng Việt trước, fallback voice hệ thống; timeline mix bằng Python, không dùng giant FFmpeg amix graph.
- Chỉ một heavy project chạy tại một thời điểm; các project còn lại hiển thị hàng đợi.
- Hủy & Xóa hoạt động cả khi project đang chạy.

## Pipeline mới

ASR → Dịch lời thoại → Visual Localization → Voice → Overlay → Render full video.
