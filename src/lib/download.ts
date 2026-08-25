/**
 * File Download Utilities for ExoticMorph
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }

  // 2. Bắt filename="filename.pptx" hoặc filename=filename.pptx
  const standardMatch = header.match(/filename="?([^";]+)"?/i);
  if (standardMatch && standardMatch[1]) {
    return standardMatch[1].trim();
  }

  return fallbackName;
}

/**
 * Tự động kích hoạt tải file Blob về máy người dùng và dọn dẹp RAM (revokeObjectURL)
 *
 * @param blob - Dữ liệu nhị phân của file PPTX
 * @param filename - Tên file cần lưu khi tải về
 */
export function downloadBlob(blob: Blob, filename: string): void {
  // Kiểm tra môi trường Browser
  if (typeof window === "undefined") return;

  // Tạo URL tạm thời trỏ đến vùng nhớ Blob
  const blobUrl = window.URL.createObjectURL(blob);

  // Tạo thẻ <a> ẩn để trigger sự kiện download
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  link.style.display = "none";

  document.body.appendChild(link);
  link.click();

  // Dọn dẹp DOM và giải phóng bộ nhớ RAM sau khi đã kích hoạt tải
  document.body.removeChild(link);
  setTimeout(() => {
    window.URL.revokeObjectURL(blobUrl);
  }, 1500);
}
