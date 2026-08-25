# HƯỚNG DẪN DEPLOY TOÀN DIỆN EXOTICMORPH LÊN CLOUD MIỄN PHÍ

Tài liệu này hướng dẫn chi tiết từng bước triển khai hệ thống **ExoticMorph** lên môi trường Production hoàn toàn miễn phí:
- **Backend (FastAPI & OpenXML Morph Engine):** Triển khai lên **Render.com** (qua Dockerfile).
- **Frontend (Next.js & Tailwind CSS):** Triển khai lên **Vercel.com**.

---

## MỤC LỤC
1. [Chuẩn bị Repository GitHub](#1-chuẩn-bị-repository-github)
2. [Bước 1: Triển khai Backend lên Render.com](#2-bước-1-triển-khai-backend-lên-rendercom)
3. [Bước 2: Triển khai Frontend lên Vercel.com](#3-bước-2-triển-khai-frontend-lên-vercelcom)
4. [Bước 3: Kiểm thử và Xác thực liên kết CORS](#4-bước-3-kiểm-thử-và-xác-thực-liên-kết-cors)
5. [Lưu ý về "Cold Start" và Tối ưu hóa trên Free Tier](#5-lưu-ý-về-cold-start-và-tối-ưu-hóa-trên-free-tier)

---

## 1. Chuẩn bị Repository GitHub

Đảm bảo mã nguồn dự án của bạn đã được đẩy lên GitHub (ví dụ: `https://github.com/YourUsername/ExoticMorph`).

Cấu trúc Repository:
```text
ExoticMorph/
├── exoticmorph-backend/         # Thư mục chứa FastAPI Backend & Dockerfile
│   ├── Dockerfile
│   ├── render.yaml
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── config.py
│       └── ...
├── src/                         # Mã nguồn Next.js Frontend
├── vercel.json                  # Cấu hình bảo mật Vercel
├── package.json
└── ...
```

---

## 2. Bước 1: Triển khai Backend lên Render.com

### 2.1. Tạo Web Service mới
1. Đăng nhập vào [Render.com Dashboard](https://dashboard.render.com).
2. Nhấn nút **New +** ở góc trên bên phải &rarr; Chọn **Web Service**.
3. Chọn **Build and deploy from a Git repository** &rarr; Kết nối tài khoản GitHub và chọn repository `ExoticMorph`.

### 2.2. Cấu hình thông số Web Service
- **Name:** `exoticmorph-backend` (hoặc tên tùy thích).
- **Region:** `Singapore` (để tối ưu độ trễ cho người dùng tại Việt Nam) hoặc `Oregon (US West)`.
- **Branch:** `main` (hoặc branch làm việc của bạn).
- **Root Directory:** `exoticmorph-backend` (⚠️ **Bắt buộc nhập** để Render chỉ build thư mục backend).
- **Runtime:** Chọn **Docker** (Render sẽ tự động đọc `exoticmorph-backend/Dockerfile`).
- **Instance Type:** Chọn gói **Free** ($0/tháng).

### 2.3. Cấu hình Biến Môi Trường (Environment Variables)
Cuộn xuống phần **Environment Variables** &rarr; Thêm các cặp Key-Value sau:

| Key | Value Mẫu | Ghi chú |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `openai` | Chọn `openai`, `gemini` hoặc `mock` |
| `OPENAI_API_KEY` | `sk-proj-xxxx...` | Khóa API OpenAI của bạn (bỏ trống nếu dùng `mock`) |
| `OPENAI_MODEL` | `gpt-4o` | Model AI tạo slide |
| `ALLOWED_ORIGINS` | `https://*.vercel.app,http://localhost:3000` | Cho phép các domain Vercel gọi API |
| `DEBUG` | `false` | Tắt chế độ debug trên Production |

### 2.4. Cấu hình Health Check Path
- Mở rộng phần **Advanced** &rarr; Tại ô **Health Check Path**, điền: `/health`.
- Nhấn **Create Web Service**.

Render sẽ tiến hành build Docker container và cấp cho bạn một đường link công khai:
`https://exoticmorph-backend.onrender.com`

---

## 3. Bước 2: Triển khai Frontend lên Vercel.com

### 3.1. Import Dự án vào Vercel
1. Đăng nhập vào [Vercel Dashboard](https://vercel.com/dashboard).
2. Nhấn nút **Add New...** &rarr; Chọn **Project**.
3. Tìm và nhấn **Import** cạnh repository `ExoticMorph`.

### 3.2. Cấu hình Build & Environment Variables
- **Project Name:** `exoticmorph` (hoặc tùy chọn).
- **Framework Preset:** `Next.js` (Tự động nhận diện).
- **Root Directory:** `./` (hoặc để trống nếu `package.json` nằm ở root).
- **Environment Variables:**
  - Thêm biến sau:
    - **NAME:** `NEXT_PUBLIC_API_URL`
    - **VALUE:** `https://exoticmorph-backend.onrender.com` *(Thay bằng URL Render thực tế ở Bước 1)*.

### 3.3. Deploy
- Nhấn nút **Deploy**.
- Vercel sẽ tự động chạy `npm run build` và bàn giao tên miền trực tiếp:
  `https://exoticmorph.vercel.app`

---

## 4. Bước 3: Kiểm thử và Xác thực liên kết CORS

1. Truy cập vào trang web Frontend trên Vercel: `https://exoticmorph.vercel.app`.
2. Quan sát badge trên Hero banner:
   - Nếu hiển thị **"Backend Online"** màu xanh lá: Frontend đã kết nối thành công với Render API!
3. Nhập một prompt bất kỳ (hoặc click vào Quick Prompt mẫu) và nhấn **"Tạo Slide với Morph"**:
   - Hệ thống chuyển sang trạng thái Loading Bar.
   - Nhận Slide Preview tương tác.
   - Bấm nút **"Tải file .pptx có Morph"** để tải file PowerPoint hoàn chỉnh về máy.

---

## 5. Lưu ý về "Cold Start" và Tối ưu hóa trên Free Tier

- **Hiện tượng Cold Start:** Gói Render Free Tier sẽ tự động tạm dừng container nếu không có truy cập trong 15 phút. Khi có request mới, Render sẽ mất khoảng **30 - 50 giây** để khởi động lại máy chủ.
- **Giải pháp giữ ấm Server (Keep-Alive Ping miễn phí):**
  1. Đăng ký tài khoản miễn phí tại [Cron-job.org](https://cron-job.org) hoặc [UptimeRobot.com](https://uptimerobot.com).
  2. Tạo một lịch kiểm tra (Monitor) gọi đến URL: `https://exoticmorph-backend.onrender.com/health`.
  3. Đặt tần suất gửi request: **Mỗi 10 phút một lần**.
  4. Như vậy, máy chủ Render Backend sẽ luôn ở trạng thái Online 24/7 và phản hồi tức thì cho người dùng Vercel!
