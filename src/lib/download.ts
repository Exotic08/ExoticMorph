/**
 * File Download Utilities for ExoticMorph
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * Tiện ích xử lý tải file nhị phân (Blob) từ trình duyệt và tự động giải phóng bộ nhớ.
 */

/**
 * Trích xuất tên file từ HTTP header 'Content-Disposition'
 * Hỗ trợ cả định dạng chuẩn RFC 6266 (filename*=UTF-8''...) và filename thông thường.
 */
export function extractFilenameFromDisposition(
  header: string | null,
  fallbackName: string = "exoticmorph_presentation.pptx"
): string {
  if (!header) return fallbackName;

  // 1. Thử bắt chuẩn UTF-8 filename*=UTF-8''filename.pptx
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return sanitizeFilename(decodeURIComponent(utf8Match[1].trim()), fallbackName);
    } catch {
      // Chuỗi percent-encoding hỏng -> dùng nguyên bản đã strip
      return sanitizeFilename(utf8Match[1].trim(), fallbackName);
    }
  }

  // 2. Bắt filename="filename.pptx" hoặc filename=filename.pptx
  const standardMatch = header.match(/filename="?([^";]+)"?/i);
  if (standardMatch && standardMatch[1]) {
    return sanitizeFilename(standardMatch[1].trim(), fallbackName);
  }

  return fallbackName;
}

/**
 * Làm sạch tên file trước khi gán vào <a download>:
 * - Loại ký tự separator đường dẫn (/ \) và ký tự không hợp lệ trên Windows,
 *   tránh trình duyệt hiểu nhầm thành path hoặc từ chối download.
 */
function sanitizeFilename(name: string, fallbackName: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|]+/g, "_").trim();
  return cleaned.length > 0 ? cleaned : fallbackName;
}

/**
 * Tự động kích hoạt tải file Blob về máy người dùng và dọn dẹp RAM (revokeObjectURL)
 *
 * @param blob - Dữ liệu nhị phân của file PPTX
 * @param filename - Tên file cần lưu khi tải về
 */
export function downloadBlob(blob: Blob, filename: string): void {
  // Chỉ chạy trong môi trường Browser (tránh crash khi SSR render component)
  if (typeof window === "undefined" || typeof document === "undefined") return;

  // Tạo URL tạm thời trỏ đến vùng nhớ Blob
  const blobUrl = window.URL.createObjectURL(blob);

  // Tạo thẻ <a> ẩn để trigger sự kiện download
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = sanitizeFilename(filename, "exoticmorph_presentation.pptx");
  link.rel = "noopener";
  link.style.display = "none";

  document.body.appendChild(link);
  link.click();

  // Dọn dẹp DOM ngay lập tức (thẻ <a> không còn tác dụng sau click)
  document.body.removeChild(link);

  // GIẢI PHÓNG BỘ NHỚ (tránh rò rỉ RAM khi người dùng tải nhiều lần):
  // Deliberately để hẹn giờ 10s thay vì 1.5s như bản cũ — revoke quá sớm có thể
  // cắt ngang stream download của file .pptx lớn trên trình duyệt/chậm hoặc
  // mạng chậm (Chrome chưa kịp đọc hết blob). 10s là đủ an toàn cho file vài MB
  // nhưng vẫn đảm bảo không tích tụ object URL giữa các lần tải liên tiếp.
  setTimeout(() => {
    window.URL.revokeObjectURL(blobUrl);
  }, 10_000);
}
